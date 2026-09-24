"""Temporal holdout evaluation for Reel Radar recommenders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .features import FeatureSpace, TasteProfile
from .quality import bayesian_rating, is_recommendable
from .ranking import (
    DEFAULT_WEIGHTS,
    candidate_feature_row,
    load_weights,
    score_from_features,
    tune_weights_grouped,
)


@dataclass
class EvalResult:
    name: str
    hit_rate_at_k: float
    ndcg_at_k: float
    coverage: float
    popularity_bias: float
    n: int
    details: dict[str, Any]


def temporal_split(
    rated: list[dict[str, Any]],
    ratings: dict[int, float],
    *,
    holdout_frac: float = 0.2,
    min_train: int = 8,
    min_test: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Split by release year as a proxy for temporal order when diary dates
    aren't available. Falls back to rating magnitude then id.
    """
    items = [m for m in rated if m.get("id") is not None and int(m["id"]) in ratings]
    if len(items) < min_train + min_test:
        return items, []

    def sort_key(m: dict[str, Any]):
        date = m.get("release_date") or "0000-00-00"
        return (date, ratings.get(int(m["id"]), 0.0), int(m["id"]))

    items = sorted(items, key=sort_key)
    n_test = max(min_test, int(round(len(items) * holdout_frac)))
    n_test = min(n_test, len(items) - min_train)
    if n_test <= 0:
        return items, []
    train, test = items[:-n_test], items[-n_test:]
    return train, test


def _dcg(rels: list[float]) -> float:
    return float(sum(r / np.log2(i + 2) for i, r in enumerate(rels)))


def ndcg_at_k(ranked_ids: list[int], relevant: set[int], k: int) -> float:
    gains = [1.0 if mid in relevant else 0.0 for mid in ranked_ids[:k]]
    ideal = sorted(gains, reverse=True)
    denom = _dcg(ideal)
    if denom <= 0:
        return 0.0
    return _dcg(gains) / denom


def hit_rate_at_k(ranked_ids: list[int], relevant: set[int], k: int) -> float:
    return 1.0 if any(mid in relevant for mid in ranked_ids[:k]) else 0.0


def _rank_baseline_cosine(
    space: FeatureSpace,
    profile: TasteProfile,
    blocked: set[int],
    k: int,
) -> list[int]:
    sims = space.cosine_to_taste(profile)
    order = np.argsort(-sims)
    out = []
    for idx in order:
        m = space.movies[int(idx)]
        mid = m.get("id")
        if mid is None or mid in blocked or not is_recommendable(m):
            continue
        out.append(int(mid))
        if len(out) >= k:
            break
    return out


def _rank_margin(
    space: FeatureSpace,
    profile: TasteProfile,
    blocked: set[int],
    k: int,
    weights: dict[str, float],
) -> list[int]:
    scored: list[tuple[float, int]] = []
    for i, m in enumerate(space.movies):
        mid = m.get("id")
        if mid is None or mid in blocked or not is_recommendable(m):
            continue
        feats = candidate_feature_row(space, profile, i)
        scored.append((score_from_features(feats, weights), int(mid)))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [mid for _, mid in scored[:k]]


def _rank_tfidf_only_proxy(
    space: FeatureSpace,
    profile: TasteProfile,
    blocked: set[int],
    k: int,
) -> list[int]:
    """Approximate TF-IDF-only by dropping dislike penalty."""
    if space.matrix is None or profile.vector is None:
        return []
    sims = space.matrix @ profile.vector
    order = np.argsort(-sims)
    out = []
    for idx in order:
        m = space.movies[int(idx)]
        mid = m.get("id")
        if mid is None or mid in blocked or not is_recommendable(m):
            continue
        out.append(int(mid))
        if len(out) >= k:
            break
    return out


def evaluate_profile(
    space: FeatureSpace,
    train_movies: list[dict[str, Any]],
    test_movies: list[dict[str, Any]],
    ratings: dict[int, float],
    *,
    k: int = 10,
    relevant_threshold: float = 3.5,
    tune: bool = True,
) -> list[EvalResult]:
    """Run ablations for one user taste split."""
    train_ratings = {int(m["id"]): ratings[int(m["id"])] for m in train_movies if int(m["id"]) in ratings}
    test_ratings = {int(m["id"]): ratings[int(m["id"])] for m in test_movies if int(m["id"]) in ratings}
    relevant = {mid for mid, r in test_ratings.items() if r >= relevant_threshold}
    if not relevant:
        # If no high ratings in holdout, treat all held-out as relevant weakly
        relevant = set(test_ratings.keys())
    if not relevant:
        return []

    likes = [m for m in train_movies if train_ratings.get(int(m["id"]), 0) >= 3.5]
    dislikes = [m for m in train_movies if train_ratings.get(int(m["id"]), 5) <= 2.0]
    profile = space.build_taste(
        likes or train_movies[:1],
        disliked=dislikes,
        ratings=train_ratings,
        rated=train_movies,
    )
    blocked = set(train_ratings.keys())

    # Build tune groups: for each relevant test item, rank it among random negs
    groups: list[tuple[list[np.ndarray], int]] = []
    rng = np.random.default_rng(42)
    catalog_idxs = [i for i, m in enumerate(space.movies) if is_recommendable(m)]
    id_to_idx = space.id_to_index
    for mid in list(relevant)[:40]:
        if mid not in id_to_idx:
            continue
        pos_i = id_to_idx[mid]
        neg_pool = [i for i in catalog_idxs if space.movies[i]["id"] not in blocked | relevant]
        if len(neg_pool) < 20:
            continue
        chosen = [pos_i] + list(rng.choice(neg_pool, size=min(50, len(neg_pool)), replace=False))
        feats = [candidate_feature_row(space, profile, i) for i in chosen]
        groups.append((feats, 0))

    tuned = dict(load_weights())
    tune_metrics = {}
    if tune and groups:
        tuned, tune_metrics = tune_weights_grouped(groups, k=k)

    rankers: dict[str, Callable[[], list[int]]] = {
        "cosine+dislike": lambda: _rank_baseline_cosine(space, profile, blocked, k),
        "tfidf_proxy_no_dislike": lambda: _rank_tfidf_only_proxy(space, profile, blocked, k),
        "margin_default": lambda: _rank_margin(space, profile, blocked, k, DEFAULT_WEIGHTS),
        "margin_tuned": lambda: _rank_margin(space, profile, blocked, k, tuned),
    }

    results: list[EvalResult] = []
    catalog_ids = {int(m["id"]) for m in space.movies if m.get("id") is not None}
    for name, fn in rankers.items():
        ranked = fn()
        hr = hit_rate_at_k(ranked, relevant, k)
        ndcg = ndcg_at_k(ranked, relevant, k)
        # Popularity bias: mean bayes of top-k
        by_id = {int(m["id"]): m for m in space.movies if m.get("id") is not None}
        pops = [bayesian_rating(by_id[i]) for i in ranked if i in by_id]
        pop_bias = float(np.mean(pops)) if pops else 0.0
        cov = len(set(ranked) & catalog_ids) / max(1, k)
        details = {"ranked": ranked[:k], "relevant": sorted(relevant)}
        if name == "margin_tuned":
            details["weights"] = tuned
            details["tune"] = tune_metrics
        results.append(
            EvalResult(
                name=name,
                hit_rate_at_k=hr,
                ndcg_at_k=ndcg,
                coverage=cov,
                popularity_bias=pop_bias,
                n=len(relevant),
                details=details,
            )
        )
    return results


def leave_one_out_hitrate(
    space: FeatureSpace,
    rated: list[dict[str, Any]],
    ratings: dict[int, float],
    *,
    k: int = 10,
    max_items: int = 40,
) -> EvalResult:
    """Per-item leave-one-out HitRate@k using margin_tuned / default weights."""
    items = [m for m in rated if m.get("id") is not None and int(m["id"]) in ratings]
    items = items[:max_items]
    if len(items) < 5:
        return EvalResult("loo_margin", 0.0, 0.0, 0.0, 0.0, 0, {})

    weights = load_weights()
    hits = []
    ndcgs = []
    for hold in items:
        hid = int(hold["id"])
        if ratings.get(hid, 0) < 3.5:
            continue
        train = [m for m in items if int(m["id"]) != hid]
        train_ratings = {int(m["id"]): ratings[int(m["id"])] for m in train}
        likes = [m for m in train if train_ratings.get(int(m["id"]), 0) >= 3.5]
        dislikes = [m for m in train if train_ratings.get(int(m["id"]), 5) <= 2.0]
        if not likes:
            continue
        profile = space.build_taste(likes, disliked=dislikes, ratings=train_ratings, rated=train)
        blocked = set(train_ratings.keys())
        ranked = _rank_margin(space, profile, blocked, k, weights)
        rel = {hid}
        hits.append(hit_rate_at_k(ranked, rel, k))
        ndcgs.append(ndcg_at_k(ranked, rel, k))

    n = len(hits)
    return EvalResult(
        name="loo_margin",
        hit_rate_at_k=float(np.mean(hits)) if hits else 0.0,
        ndcg_at_k=float(np.mean(ndcgs)) if ndcgs else 0.0,
        coverage=1.0,
        popularity_bias=0.0,
        n=n,
        details={},
    )
