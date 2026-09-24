"""Feature engineering + taste profiles for Reel Radar."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from .embeddings import encode_texts
from .quality import bayesian_rating


def feature_backend_name() -> str:
    from .embeddings import embedding_backend

    return embedding_backend()

GENRE_NAMES = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Science Fiction",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
}

GENRE_MOOD_HINTS = {
    28: "adrenaline",
    12: "wonder",
    16: "playful",
    35: "light",
    80: "gritty",
    99: "curious",
    18: "heavy",
    10751: "warm",
    14: "wonder",
    36: "reflective",
    27: "tense",
    10402: "light",
    9648: "curious",
    10749: "warm",
    878: "wonder",
    10770: "cozy",
    53: "tense",
    10752: "heavy",
    37: "gritty",
}


def year_of(movie: dict[str, Any]) -> int | None:
    date = movie.get("release_date") or ""
    if len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def decade_of(movie: dict[str, Any]) -> int | None:
    y = year_of(movie)
    return (y // 10) * 10 if y else None


def genre_ids(movie: dict[str, Any]) -> list[int]:
    if "genre_ids" in movie and movie["genre_ids"] is not None:
        return list(movie["genre_ids"])
    genres = movie.get("genres") or []
    return [g["id"] for g in genres if isinstance(g, dict) and "id" in g]


def movie_text(movie: dict[str, Any]) -> str:
    parts = [
        movie.get("title") or "",
        movie.get("original_title") or "",
        movie.get("overview") or "",
        movie.get("tagline") or "",
    ]
    keywords = movie.get("keywords") or {}
    if isinstance(keywords, dict):
        parts.append(" ".join(k.get("name", "") for k in keywords.get("keywords", [])))
    genres = movie.get("genres") or []
    if genres and isinstance(genres[0], dict):
        parts.append(" ".join(g.get("name", "") for g in genres))
    else:
        parts.append(" ".join(GENRE_NAMES.get(g, "") for g in genre_ids(movie)))
    return " ".join(p for p in parts if p)


def mood_tags(movie: dict[str, Any]) -> list[str]:
    tags = {GENRE_MOOD_HINTS.get(gid) for gid in genre_ids(movie)}
    tags.discard(None)
    overview = (movie.get("overview") or "").lower()
    lexicon = {
        "cozy": ["home", "family", "small town", "gentle", "heartwarming"],
        "tense": ["murder", "chase", "conspiracy", "threat", "survive"],
        "melancholy": ["loss", "grief", "lonely", "regret", "farewell"],
        "playful": ["hilarious", "chaos", "misadventure", "prank"],
        "romantic": ["love", "romance", "affair", "wedding"],
        "mind-bend": ["reality", "memory", "dream", "identity", "simulation"],
    }
    for mood, words in lexicon.items():
        if any(w in overview for w in words):
            tags.add(mood)
    return sorted(tags) or ["undefined"]


@dataclass
class TasteProfile:
    liked_ids: list[int] = field(default_factory=list)
    disliked_ids: list[int] = field(default_factory=list)
    liked_movies: list[dict[str, Any]] = field(default_factory=list)
    disliked_movies: list[dict[str, Any]] = field(default_factory=list)
    ratings: dict[int, float] = field(default_factory=dict)
    vector: np.ndarray | None = None
    dislike_vector: np.ndarray | None = None
    genre_affinity: dict[int, float] = field(default_factory=dict)
    decade_affinity: dict[int, float] = field(default_factory=dict)
    avg_runtime: float | None = None
    label: str = "You"
    feature_backend: str = "tfidf"

    def is_ready(self) -> bool:
        return len(self.liked_movies) >= 1


class FeatureSpace:
    """TF-IDF (+ optional MiniLM embeddings) + numeric metadata space."""

    def __init__(self, use_embeddings: bool = True):
        self.use_embeddings = use_embeddings
        self.vectorizer = TfidfVectorizer(
            max_features=3500,
            ngram_range=(1, 2),
            stop_words="english",
            min_df=1,
        )
        self.movie_ids: list[int] = []
        self.movies: list[dict[str, Any]] = []
        self.matrix: np.ndarray | None = None
        self.id_to_index: dict[int, int] = {}
        self._fitted = False
        self.backend = "tfidf"
        self._dense: np.ndarray | None = None  # embedding block only, for vibe queries

    def fit(self, movies: list[dict[str, Any]]) -> "FeatureSpace":
        by_id: dict[int, dict[str, Any]] = {}
        for m in movies:
            mid = m.get("id")
            if mid is None:
                continue
            prev = by_id.get(mid)
            if prev is None or len(movie_text(m)) > len(movie_text(prev)):
                by_id[mid] = m
        self.movies = list(by_id.values())
        self.movie_ids = [m["id"] for m in self.movies]
        self.id_to_index = {mid: i for i, mid in enumerate(self.movie_ids)}

        if not self.movies:
            # Empty catalog: skip TF-IDF (it would raise "empty vocabulary").
            # Leave an (0, 4) matrix so recommenders iterate zero times safely
            # and `vector_for` can still build a 4-d meta vector.
            self._genre_index = {}
            self.matrix = np.zeros((0, 4), dtype=np.float32)
            self._dense = None
            self.backend = "tfidf+meta"
            self._fitted = True
            return self

        texts = [movie_text(m) for m in self.movies]
        tfidf = self.vectorizer.fit_transform(texts).toarray().astype(np.float32)

        all_genres = sorted({gid for m in self.movies for gid in genre_ids(m)})
        self._genre_index = {g: i for i, g in enumerate(all_genres)}
        numeric = []
        for m in self.movies:
            y = year_of(m) or 2000
            runtime = float(m.get("runtime") or 110)
            pop = float(m.get("popularity") or 0.0)
            quality = bayesian_rating(m) / 10.0
            gvec = np.zeros(len(all_genres), dtype=np.float32)
            for gid in genre_ids(m):
                if gid in self._genre_index:
                    gvec[self._genre_index[gid]] = 1.0
            numeric.append(
                np.concatenate(
                    [
                        np.array(
                            [
                                (y - 1950) / 80.0,
                                runtime / 180.0,
                                min(pop, 200) / 200.0,
                                quality,
                            ],
                            dtype=np.float32,
                        ),
                        gvec,
                    ]
                )
            )
        num_mat = np.vstack(numeric) if numeric else np.zeros((0, 4), dtype=np.float32)

        blocks = [normalize(tfidf), normalize(num_mat)]
        self.backend = "tfidf+meta"

        if self.use_embeddings:
            dense = encode_texts(texts)
            if dense is not None:
                self._dense = dense.astype(np.float32)
                blocks.insert(0, self._dense)
                self.backend = "minilm+tfidf+meta"
            else:
                self._dense = None
        else:
            self._dense = None

        # Weight blocks: embeddings (if any) dominate semantic vibe
        if len(blocks) == 3:
            combined = np.hstack([blocks[0] * 1.35, blocks[1] * 0.85, blocks[2] * 0.9])
        else:
            combined = np.hstack([blocks[0] * 1.0, blocks[1] * 1.0])
        self.matrix = normalize(combined)
        self._fitted = True
        return self

    def _meta_vector(self, movie: dict[str, Any]) -> np.ndarray:
        y = year_of(movie) or 2000
        runtime = float(movie.get("runtime") or 110)
        pop = float(movie.get("popularity") or 0.0)
        quality = bayesian_rating(movie) / 10.0
        gvec = np.zeros(len(self._genre_index), dtype=np.float32)
        for gid in genre_ids(movie):
            if gid in self._genre_index:
                gvec[self._genre_index[gid]] = 1.0
        return np.concatenate(
            [
                np.array(
                    [
                        (y - 1950) / 80.0,
                        runtime / 180.0,
                        min(pop, 200) / 200.0,
                        quality,
                    ],
                    dtype=np.float32,
                ),
                gvec,
            ]
        )

    def vector_for(self, movie: dict[str, Any]) -> np.ndarray | None:
        if not self._fitted or self.matrix is None:
            return None
        # Empty-fit short-circuit: vectorizer has no vocab, nothing to project into.
        if self.matrix.shape[0] == 0:
            return None
        idx = self.id_to_index.get(movie.get("id"))
        if idx is not None:
            return self.matrix[idx]

        text = movie_text(movie)
        tfidf = self.vectorizer.transform([text]).toarray().astype(np.float32)
        meta = self._meta_vector(movie).reshape(1, -1)
        parts = [normalize(tfidf), normalize(meta)]
        weights = [0.85, 0.9]
        if self._dense is not None:
            from .embeddings import encode_query

            dense = encode_query(text)
            if dense is not None:
                parts = [dense.reshape(1, -1), parts[0], parts[1]]
                weights = [1.35, 0.85, 0.9]
        scaled = [parts[i] * weights[i] for i in range(len(parts))]
        return normalize(np.hstack(scaled))[0]

    def build_taste(
        self,
        liked: list[dict[str, Any]],
        label: str = "You",
        *,
        disliked: list[dict[str, Any]] | None = None,
        ratings: dict[int, float] | None = None,
        rated: list[dict[str, Any]] | None = None,
        midpoint: float = 3.0,
    ) -> TasteProfile:
        """
        Build a taste profile from Letterboxd-style ratings.

        Ratings are centered at `midpoint` (default 3.0):
          - 5★ pulls the centroid hard toward that film
          - 0.5★ pulls the anti-centroid hard away
          - ~3★ barely moves the model
        """
        disliked = disliked or []
        rated = rated or []
        ratings = dict(ratings or {})

        by_id: dict[int, dict[str, Any]] = {}
        for m in list(rated) + list(liked) + list(disliked):
            if m.get("id") is None:
                continue
            by_id[int(m["id"])] = m

        # Fill missing ratings from bucket membership
        for m in liked:
            ratings.setdefault(int(m["id"]), 4.5)
        for m in disliked:
            ratings.setdefault(int(m["id"]), 1.0)

        like_ids = [mid for mid, r in ratings.items() if r >= midpoint + 0.5]
        dislike_ids = [mid for mid, r in ratings.items() if r <= midpoint - 1.0]

        profile = TasteProfile(
            liked_ids=like_ids,
            disliked_ids=dislike_ids,
            liked_movies=[by_id[i] for i in like_ids if i in by_id],
            disliked_movies=[by_id[i] for i in dislike_ids if i in by_id],
            ratings=ratings,
            label=label,
            feature_backend=self.backend,
        )

        pos_vecs: list[np.ndarray] = []
        pos_w: list[float] = []
        neg_vecs: list[np.ndarray] = []
        neg_w: list[float] = []

        for mid, movie in by_id.items():
            r = float(ratings.get(mid, midpoint))
            signed = r - midpoint  # -2.5 .. +2.0
            vec = self.vector_for(movie)
            if vec is None:
                continue

            # Genre / decade: signed contribution so low scores push genres down
            strength = abs(signed) + 0.15
            direction = 1.0 if signed >= 0 else -1.0
            for gid in genre_ids(movie):
                profile.genre_affinity[gid] = (
                    profile.genre_affinity.get(gid, 0.0) + direction * strength * max(r, 0.5)
                )
            dec = decade_of(movie)
            if dec:
                profile.decade_affinity[dec] = (
                    profile.decade_affinity.get(dec, 0.0) + direction * strength * max(r, 0.5)
                )

            if signed >= 0:
                # Emphasize 4–5★ more than 3★
                w = max(0.15, signed ** 1.4)
                pos_vecs.append(vec)
                pos_w.append(w)
            else:
                w = max(0.15, abs(signed) ** 1.4)
                neg_vecs.append(vec)
                neg_w.append(w)

        runtimes = [
            by_id[mid].get("runtime")
            for mid, r in ratings.items()
            if mid in by_id and r >= midpoint and by_id[mid].get("runtime")
        ]
        if runtimes:
            profile.avg_runtime = float(np.mean(runtimes))

        if pos_vecs:
            w = np.asarray(pos_w, dtype=np.float32).reshape(-1, 1)
            stacked = np.vstack(pos_vecs)
            profile.vector = normalize((stacked * w).sum(axis=0, keepdims=True) / w.sum())[0]
        if neg_vecs:
            w = np.asarray(neg_w, dtype=np.float32).reshape(-1, 1)
            stacked = np.vstack(neg_vecs)
            profile.dislike_vector = normalize(
                (stacked * w).sum(axis=0, keepdims=True) / w.sum()
            )[0]

        # Softmax-ish normalize affinities after flooring negatives lightly
        profile.genre_affinity = {k: max(0.0, v) for k, v in profile.genre_affinity.items()}
        gsum = sum(profile.genre_affinity.values()) or 1.0
        profile.genre_affinity = {k: v / gsum for k, v in profile.genre_affinity.items()}
        profile.decade_affinity = {k: max(0.0, v) for k, v in profile.decade_affinity.items()}
        dsum = sum(profile.decade_affinity.values()) or 1.0
        profile.decade_affinity = {k: v / dsum for k, v in profile.decade_affinity.items()}
        return profile

    def cosine_to_taste(self, profile: TasteProfile, dislike_penalty: float = 0.55) -> np.ndarray:
        # Graceful empty-state: an unseeded profile or a missing matrix should
        # yield all-zero similarities so recommenders iterate zero times
        # instead of crashing on an assertion (which Python `-O` strips anyway).
        if self.matrix is None or profile.vector is None or not len(self.movies):
            return np.zeros(len(self.movies), dtype=np.float32)
        sims = self.matrix @ profile.vector
        if profile.dislike_vector is not None:
            sims = sims - dislike_penalty * (self.matrix @ profile.dislike_vector)
        return sims


def format_taste_summary(profile: TasteProfile) -> list[str]:
    """
    Return 3 short factual bullets about a taste profile.
    No heuristic prose — keep it factual. Used by the Taste Fingerprint panel.
    Returns an empty list if the profile isn't substantial.
    """
    if profile is None or profile.vector is None or len(profile.liked_movies) < 3:
        return []
    bullets: list[str] = []

    # Top 3 genres with their share
    top_genres = sorted(profile.genre_affinity.items(), key=lambda t: t[1], reverse=True)[:3]
    if top_genres:
        names = [f"{GENRE_NAMES.get(gid, str(gid))} {share*100:.0f}%" for gid, share in top_genres]
        bullets.append("Loves " + ", ".join(names))

    # Weighted-average release year from liked movies
    years: list[int] = []
    weights: list[float] = []
    for m in profile.liked_movies:
        y = year_of(m)
        if y is None:
            continue
        r = float(profile.ratings.get(int(m["id"]), 3.5))
        years.append(y)
        weights.append(r)
    if years:
        avg_year = sum(y * w for y, w in zip(years, weights)) / max(sum(weights), 1e-9)
        # Pick the nearest decade
        decade = int(avg_year // 10 * 10)
        bullets.append(f"Centers around the {decade}s")

    # Average runtime
    if profile.avg_runtime is not None:
        bullets.append(f"Average runtime {int(profile.avg_runtime)} min")

    return bullets
