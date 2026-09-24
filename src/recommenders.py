"""All recommendation modes for Reel Radar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import networkx as nx
import numpy as np
from sklearn.cluster import KMeans

from .catalog import runtime_ok, year_in_decade
from .events import session_not_interested
from .features import TasteProfile, FeatureSpace, genre_ids, mood_tags, year_of
from .quality import bayesian_rating, is_recommendable
from .ranking import Explanation, ScoreBreakdown, blocked_ids, score_candidate
from .tmdb import TMDBClient


@dataclass
class VibeExplanation:
    vibe_sim: float
    quality_sim: float
    def as_rows(self) -> list[tuple[str, float]]:
        return [
            ("vibe match", self.vibe_sim),
            ("quality", self.quality_sim),
        ]


@dataclass
class DnaExplanation:
    roles: dict[str, float]   # e.g. {"Director": 3.0, "DOP": 2.2, "Composer": 2.0}
    def as_rows(self) -> list[tuple[str, float]]:
        # Return sorted by value desc, only items with abs value >= 0.5
        return sorted(
            [(k, v) for k, v in self.roles.items() if abs(v) >= 0.5],
            key=lambda t: t[1], reverse=True
        )


@dataclass
class GroupExplanation:
    per_watcher: dict[str, float]  # label -> sim
    mean: float
    min: float
    std: float
    def as_rows(self) -> list[tuple[str, float]]:
        rows = [(label, sim) for label, sim in self.per_watcher.items()]
        rows.append(("mean", self.mean))
        rows.append(("min", self.min))
        return rows


@dataclass
class RecItem:
    movie: dict[str, Any]
    score: float
    role: str
    reason: str
    breakdown: "ScoreBreakdown | None" = None      # existing — for margin-scored modes
    contributions: str = ""                       # existing — pre-formatted line
    explanation: "Explanation | None" = None      # NEW — the rendering protocol target


ENERGY_GENRE_BIAS = {
    "cozy": {35: 1.2, 10751: 1.3, 10749: 1.2, 16: 1.1, 99: 0.8, 27: 0.2, 53: 0.4},
    "tense": {53: 1.4, 27: 1.3, 80: 1.2, 9648: 1.2, 28: 1.1, 35: 0.5, 10751: 0.3},
    "brain-on": {878: 1.3, 9648: 1.3, 99: 1.2, 18: 1.1, 36: 1.1, 28: 0.7},
    "adrenaline": {28: 1.4, 12: 1.3, 53: 1.2, 878: 1.1, 10749: 0.4, 99: 0.4},
    "melancholy": {18: 1.4, 10749: 1.1, 36: 1.1, 35: 0.4, 28: 0.5},
}


def _eligible(movie: dict[str, Any], blocked: set[int]) -> bool:
    return movie.get("id") not in blocked and is_recommendable(movie)


def _genre_boost(movie: dict[str, Any], energy: str) -> float:
    bias = ENERGY_GENRE_BIAS.get(energy, {})
    gids = genre_ids(movie)
    if not gids:
        return 1.0
    return float(np.mean([bias.get(g, 1.0) for g in gids]))


def _hard_no_hit(movie: dict[str, Any], hard_nos: set[int]) -> bool:
    return any(g in hard_nos for g in genre_ids(movie))


def tonight_decoder(
    space: FeatureSpace,
    profile: TasteProfile,
    catalog: list[dict[str, Any]],
    *,
    max_minutes: int,
    energy: str,
    hard_no_genres: list[int],
) -> list[RecItem]:
    """Contextual picks for this exact night (margin rank + explanations)."""
    hard_nos = set(hard_no_genres)
    candidates: list[RecItem] = []
    # Block rated films + explicit not-interested skips from the product loop.
    blocked = blocked_ids(profile, session_not_interested())

    for i, movie in enumerate(space.movies):
        if not _eligible(movie, blocked):
            continue
        if _hard_no_hit(movie, hard_nos):
            continue
        if not runtime_ok(movie, max_minutes):
            continue
        boost = _genre_boost(movie, energy)
        bd = score_candidate(
            space,
            profile,
            i,
            energy_boost=boost,
            max_minutes=max_minutes,
        )
        contrib = bd.format_line()
        reason = (
            f"Fits a {energy} night within ~{max_minutes}m. "
            f"Score breakdown: {contrib}."
        )
        candidates.append(
            RecItem(
                movie,
                bd.total,
                "tonight",
                reason,
                breakdown=bd,
                contributions=contrib,
                explanation=bd,
            )
        )

    candidates.sort(key=lambda r: r.score, reverse=True)
    # Diversify top 3 by genre overlap
    picked: list[RecItem] = []
    used_genres: set[int] = set()
    for rec in candidates:
        g = set(genre_ids(rec.movie))
        if picked and len(g & used_genres) >= max(1, len(g)):
            continue
        picked.append(rec)
        used_genres |= g
        if len(picked) == 3:
            break
    while len(picked) < 3 and len(picked) < len(candidates):
        for rec in candidates:
            if rec not in picked:
                picked.append(rec)
            if len(picked) == 3:
                break
    return picked


def anti_bubble(
    space: FeatureSpace,
    profile: TasteProfile,
) -> list[RecItem]:
    """Comfort + stretch + delicious risk (margin taste, dislike-aware)."""
    blocked = blocked_ids(profile, session_not_interested())
    indexed: list[tuple[int, ScoreBreakdown, dict[str, Any]]] = []
    for i, movie in enumerate(space.movies):
        if not _eligible(movie, blocked):
            continue
        bd = score_candidate(space, profile, i)
        indexed.append((i, bd, movie))
    indexed.sort(key=lambda t: t[1].total, reverse=True)
    if not indexed:
        return []

    comfort = indexed[0]
    # stretch: mid taste similarity, high quality
    stretch_pool = [t for t in indexed if 0.08 < t[1].taste < 0.40]
    stretch_pool.sort(key=lambda t: (t[1].quality, t[1].total), reverse=True)
    stretch = stretch_pool[0] if stretch_pool else indexed[len(indexed) // 3]

    # risk: low taste pull but still quality, not in avoid cone
    risk_pool = [t for t in indexed if t[1].taste < 0.18 and t[1].avoid < 0.25]
    risk_pool.sort(key=lambda t: (t[1].quality * (1.0 - t[1].taste)), reverse=True)
    risk = risk_pool[0] if risk_pool else indexed[-1]

    def _item(slot, role: str, blurb: str) -> RecItem:
        bd = slot[1]
        return RecItem(
            slot[2],
            bd.total,
            role,
            f"{blurb} {bd.format_line()}.",
            breakdown=bd,
            contributions=bd.format_line(),
            explanation=bd,
        )

    return [
        _item(comfort, "comfort", "Safe harbor — strongest margin fit."),
        _item(stretch, "stretch", "Adjacent curiosity — related but not a clone."),
        _item(risk, "risk", "Controlled whiplash — distant, still watchable."),
    ]


def taste_twin(
    space: FeatureSpace,
    profile: TasteProfile,
    target_decade: int,
    top_k: int = 5,
) -> list[RecItem]:
    """Map modern taste onto another decade."""
    liked = blocked_ids(profile, session_not_interested())
    scored: list[RecItem] = []
    for i, movie in enumerate(space.movies):
        if not _eligible(movie, liked):
            continue
        if not year_in_decade(movie, target_decade):
            continue
        g_boost = 1.0
        for gid in genre_ids(movie):
            g_boost += 0.35 * profile.genre_affinity.get(gid, 0.0)
        bd = score_candidate(space, profile, i, energy_boost=g_boost)
        y = year_of(movie)
        reason = (
            f"Your taste twin in the {target_decade}s "
            f"({y}) — same vibe DNA, different decade. {bd.format_line()}."
        )
        scored.append(
            RecItem(
                movie,
                bd.total,
                "twin",
                reason,
                breakdown=bd,
                contributions=bd.format_line(),
                explanation=bd,
            )
        )
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]


def vibe_match(
    space: FeatureSpace,
    vibe_text: str,
    liked_ids: set[int] | None = None,
    top_k: int = 6,
) -> list[RecItem]:
    """Match a free-text vibe / scene description into the catalog."""
    liked_ids = liked_ids or set()
    query_movie = {
        "id": -1,
        "title": "",
        "overview": vibe_text,
        "genre_ids": [],
        "popularity": 50,
        "vote_average": 7.0,
        "vote_count": 500,
        "runtime": 110,
        "release_date": "2000-01-01",
    }
    q = space.vector_for(query_movie)
    if q is None or space.matrix is None:
        return []
    # Prefer dense semantic block when available
    if space._dense is not None:
        from .embeddings import encode_query

        dense_q = encode_query(vibe_text)
        if dense_q is not None:
            sims = space._dense @ dense_q
        else:
            sims = space.matrix @ q
    else:
        sims = space.matrix @ q
    order = np.argsort(-sims)
    out: list[RecItem] = []
    for idx in order:
        movie = space.movies[int(idx)]
        if not _eligible(movie, liked_ids):
            continue
        base = float(sims[int(idx)])
        score = 0.85 * base + 0.15 * (bayesian_rating(movie) / 10.0)
        quality_sim = bayesian_rating(movie) / 10.0
        tags = ", ".join(mood_tags(movie)[:3])
        out.append(
            RecItem(
                movie,
                score,
                "vibe",
                f"Semantic overlap with your vibe ({base:.2f}). Mood tags: {tags}.",
                explanation=VibeExplanation(vibe_sim=base, quality_sim=quality_sim),
            )
        )
        if len(out) >= top_k:
            break
    return out


def cinematic_dna(
    client: TMDBClient,
    seed: dict[str, Any],
    top_k: int = 6,
) -> list[RecItem]:
    """Recommend via shared craftspeople (director / DOP / composer / writers / cast)."""
    detail = seed if seed.get("credits") else client.movie(seed["id"])
    credits = detail.get("credits") or {}
    crew = credits.get("crew") or []
    cast = credits.get("cast") or []

    roles_of_interest = {
        "Director",
        "Director of Photography",
        "Original Music Composer",
        "Screenplay",
        "Writer",
        "Editor",
    }
    people: list[tuple[str, int, str]] = []
    for c in crew:
        if c.get("job") in roles_of_interest and c.get("id"):
            people.append((c["job"], c["id"], c.get("name") or "Unknown"))
    for c in cast[:5]:
        if c.get("id"):
            people.append(("Cast", c["id"], c.get("name") or "Unknown"))

    graph = nx.Graph()
    seed_id = detail["id"]
    graph.add_node(("movie", seed_id), title=detail.get("title"), kind="movie")

    tallies: dict[int, dict[str, Any]] = {}
    for job, pid, pname in people[:12]:
        graph.add_node(("person", pid), name=pname, kind="person")
        graph.add_edge(("movie", seed_id), ("person", pid), role=job)
        try:
            creds = client.person_credits(pid)
        except Exception:
            continue
        for m in (creds.get("cast") or []) + (creds.get("crew") or []):
            mid = m.get("id")
            if not mid or mid == seed_id:
                continue
            if not is_recommendable(m, min_votes=40, min_overview=0, min_popularity=0.0):
                # person credits often lack overview; require votes at least
                if (m.get("vote_count") or 0) < 40:
                    continue
            graph.add_node(("movie", mid), title=m.get("title"), kind="movie")
            graph.add_edge(("movie", mid), ("person", pid), role=job)
            slot = tallies.setdefault(
                mid,
                {"movie": m, "links": [], "score": 0.0, "roles": {}},
            )
            link = f"{pname} ({job})"
            if link not in slot["links"]:
                slot["links"].append(link)
            weight = {"Director": 3.0, "Director of Photography": 2.2, "Original Music Composer": 2.0}.get(
                job, 1.2
            )
            # Map the full crew job to a short role label for the explanation rows.
            role_label = {
                "Director": "Director",
                "Director of Photography": "DOP",
                "Original Music Composer": "Composer",
                "Screenplay": "Writer",
                "Writer": "Writer",
                "Editor": "Editor",
                "Cast": "Cast",
            }.get(job, job)
            slot["roles"][role_label] = slot["roles"].get(role_label, 0.0) + weight
            slot["score"] += weight

    ranked = sorted(tallies.values(), key=lambda x: x["score"], reverse=True)
    out: list[RecItem] = []
    for item in ranked:
        links = ", ".join(item["links"][:3])
        out.append(
            RecItem(
                item["movie"],
                float(item["score"]),
                "dna",
                f"Shared craft lineage with {detail.get('title')}: {links}.",
                explanation=DnaExplanation(roles=dict(item["roles"])),
            )
        )
        if len(out) >= top_k:
            break
    return out


def group_peace_treaty(
    space: FeatureSpace,
    profiles: list[TasteProfile],
    top_k: int = 5,
) -> list[RecItem]:
    """Minimize maximum regret across watchers."""
    if not profiles or space.matrix is None:
        return []
    sim_stack = []
    profile_indices: list[int] = []
    liked_union: set[int] = set()
    for pi, p in enumerate(profiles):
        if p.vector is None:
            continue
        sim_stack.append(space.matrix @ p.vector)
        profile_indices.append(pi)
        # Block ALL rated films across every watcher — anyone who rated it has seen it.
        liked_union |= set(p.ratings.keys())
    if not sim_stack:
        return []
    sims = np.vstack(sim_stack)
    mean = sims.mean(axis=0)
    std = sims.std(axis=0)
    min_sim = sims.min(axis=0)
    quality = np.array([bayesian_rating(m) / 10.0 for m in space.movies])
    score = 0.50 * mean + 0.30 * min_sim - 0.20 * std + 0.15 * quality

    order = np.argsort(-score)
    out: list[RecItem] = []
    for idx in order:
        movie = space.movies[int(idx)]
        if not _eligible(movie, liked_union):
            continue
        person_scores = ", ".join(
            f"{profiles[i].label} {sims[i, idx]:.2f}" for i in range(len(sim_stack))
        )
        per_watcher = {profiles[i].label: float(sims[i, int(idx)]) for i in range(len(sim_stack))}
        out.append(
            RecItem(
                movie,
                float(score[int(idx)]),
                "group",
                f"Peace treaty pick — strong for everyone, low regret. [{person_scores}]",
                explanation=GroupExplanation(
                    per_watcher=per_watcher,
                    mean=float(mean[int(idx)]),
                    min=float(min_sim[int(idx)]),
                    std=float(std[int(idx)]),
                ),
            )
        )
        if len(out) >= top_k:
            break
    return out


def mood_map(
    space: FeatureSpace,
    profile: TasteProfile | None = None,
    n_clusters: int = 6,
) -> dict[str, Any]:
    """Cluster catalog into spoiler-free mood territories."""
    if space.matrix is None or len(space.movies) < n_clusters:
        return {"clusters": [], "user_placement": None}

    k = min(n_clusters, len(space.movies))
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(space.matrix)

    clusters = []
    for cid in range(k):
        idxs = np.where(labels == cid)[0]
        movies = [space.movies[int(i)] for i in idxs]
        tag_counts: dict[str, int] = {}
        for m in movies:
            for t in mood_tags(m):
                tag_counts[t] = tag_counts.get(t, 0) + 1
        top_tags = sorted(tag_counts, key=tag_counts.get, reverse=True)[:3]
        name = " / ".join(top_tags) if top_tags else f"Cluster {cid + 1}"
        centroid = km.cluster_centers_[cid]
        dists = np.linalg.norm(space.matrix[idxs] - centroid, axis=1)
        order = np.argsort(dists)
        exemplars = []
        for j in order:
            m = movies[int(j)]
            if is_recommendable(m):
                exemplars.append(m)
            if len(exemplars) >= 8:
                break
        clusters.append(
            {
                "id": cid,
                "name": name,
                "size": len(movies),
                "tags": top_tags,
                "exemplars": exemplars,
            }
        )

    user_placement = None
    if profile and profile.vector is not None:
        dists = np.linalg.norm(km.cluster_centers_ - profile.vector, axis=1)
        home = int(np.argmin(dists))
        user_placement = {
            "cluster_id": home,
            "cluster_name": clusters[home]["name"],
            "distances": {clusters[i]["name"]: float(dists[i]) for i in range(k)},
        }

    return {"clusters": clusters, "user_placement": user_placement, "labels": labels}


def recommend_in_mood(
    space: FeatureSpace,
    mood_result: dict[str, Any],
    cluster_id: int,
    profile: TasteProfile | None = None,
    top_k: int = 5,
) -> list[RecItem]:
    labels = mood_result.get("labels")
    if labels is None or space.matrix is None:
        return []
    idxs = [i for i, lab in enumerate(labels) if int(lab) == cluster_id]
    liked = blocked_ids(profile, session_not_interested()) if profile else session_not_interested()
    scored = []
    for i in idxs:
        movie = space.movies[i]
        if not _eligible(movie, liked):
            continue
        if profile and profile.vector is not None:
            bd = score_candidate(space, profile, i)
            scored.append(
                RecItem(
                    movie,
                    bd.total,
                    "mood",
                    f"Inside the '{mood_result['clusters'][cluster_id]['name']}' mood territory. "
                    f"{bd.format_line()}.",
                    breakdown=bd,
                    contributions=bd.format_line(),
                    explanation=bd,
                )
            )
        else:
            score = bayesian_rating(movie) / 10.0
            scored.append(
                RecItem(
                    movie,
                    score,
                    "mood",
                    f"Inside the '{mood_result['clusters'][cluster_id]['name']}' mood territory.",
                    explanation=None,
                )
            )
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]
