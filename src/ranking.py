"""Margin ranking, score breakdowns, and tunable re-ranker weights."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .features import FeatureSpace, TasteProfile, year_of
from .quality import bayesian_rating

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
WEIGHTS_PATH = DATA_DIR / "ranker_weights.json"

# Default linear weights — tuned offline by eval_holdout when possible.
DEFAULT_WEIGHTS = {
    "taste": 0.72,
    "avoid": 0.55,
    "quality": 0.22,
    "energy": 0.18,
    "runtime_fit": 0.08,
    "year_fit": 0.05,
    "popularity_penalty": 0.04,
}


class Explanation(Protocol):
    """Anything that can be displayed as a breakdown. Single as_rows() method."""
    def as_rows(self) -> list[tuple[str, float]]:
        """Return non-zero (label, value) pairs for UI rendering."""
        ...


GLOSSARY: dict[str, str] = {
    "taste":       "fits your taste",
    "avoid":       "drifts from your avoids",
    "quality":     "critics like it",
    "energy":      "energy match",
    "runtime":     "fits your watch window",
    "year":        "matches your decade",
    "pop↓":        "less crowded pick",
    "vibe match":  "matches your words",
    "Director":    "shares a director with",
    "DOP":         "shares a cinematographer with",
    "Composer":    "shares a composer with",
    "Writer":      "shares a writer with",
    "Cast":        "shares a cast member with",
}


@dataclass
class ScoreBreakdown:
    taste: float = 0.0
    avoid: float = 0.0
    quality: float = 0.0
    energy: float = 0.0
    runtime_fit: float = 0.0
    year_fit: float = 0.0
    popularity_penalty: float = 0.0
    total: float = 0.0

    def as_parts(self) -> list[tuple[str, float]]:
        """Signed contribution parts for UI (skip near-zeros)."""
        parts = [
            ("taste", self.taste),
            ("avoid", -self.avoid),
            ("quality", self.quality),
            ("energy", self.energy),
            ("runtime", self.runtime_fit),
            ("year", self.year_fit),
            ("pop↓", -self.popularity_penalty),
        ]
        return [(k, v) for k, v in parts if abs(v) >= 0.005]

    def as_rows(self) -> list[tuple[str, float]]:
        """Protocol-conformant alias for as_parts() (the Explanation protocol)."""
        return self.as_parts()

    def format_line(self) -> str:
        bits = []
        for name, val in self.as_parts():
            sign = "+" if val >= 0 else ""
            bits.append(f"{sign}{val:.2f} {name}")
        return " · ".join(bits) if bits else "—"


def load_weights(path: Path = WEIGHTS_PATH) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in weights:
                        weights[k] = float(v)
        except (OSError, ValueError, TypeError):
            pass
    return weights


def save_weights(weights: dict[str, float], path: Path = WEIGHTS_PATH) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULT_WEIGHTS)
    merged.update({k: float(v) for k, v in weights.items() if k in DEFAULT_WEIGHTS})
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")


def _runtime_fit(movie: dict[str, Any], max_minutes: int | None, avg_runtime: float | None) -> float:
    rt = movie.get("runtime")
    if not rt:
        return 0.0
    rt = float(rt)
    score = 0.0
    if max_minutes:
        # Prefer fitting under the cap with a little headroom, not tiny shorts
        if rt <= max_minutes:
            score += 0.6 * (rt / max_minutes)
            if max_minutes - 25 <= rt <= max_minutes:
                score += 0.4
        else:
            score -= min(1.0, (rt - max_minutes) / 40.0)
    if avg_runtime:
        gap = abs(rt - avg_runtime) / max(avg_runtime, 1.0)
        score += max(0.0, 0.35 * (1.0 - gap))
    return float(np.clip(score, -1.0, 1.0))


def _year_fit(movie: dict[str, Any], profile: TasteProfile) -> float:
    y = year_of(movie)
    if not y or not profile.decade_affinity:
        return 0.0
    dec = (y // 10) * 10
    return float(profile.decade_affinity.get(dec, 0.0))


def _popularity_penalty(movie: dict[str, Any]) -> float:
    """Mild penalty so ultra-popular titles don't always dominate."""
    try:
        pop = float(movie.get("popularity") or 0.0)
    except (TypeError, ValueError):
        pop = 0.0
    # Soft hinge above ~80 popularity
    return float(np.clip((pop - 80.0) / 200.0, 0.0, 1.0))


def score_candidate(
    space: FeatureSpace,
    profile: TasteProfile,
    index: int,
    *,
    energy_boost: float = 1.0,
    max_minutes: int | None = None,
    weights: dict[str, float] | None = None,
    dislike_lambda: float | None = None,
) -> ScoreBreakdown:
    """Margin score: w_t·taste − λ·avoid + quality priors + context fits."""
    w = weights or load_weights()
    movie = space.movies[index]
    taste = 0.0
    avoid = 0.0
    if space.matrix is not None and profile.vector is not None:
        taste = float(space.matrix[index] @ profile.vector)
    if space.matrix is not None and profile.dislike_vector is not None:
        avoid = float(space.matrix[index] @ profile.dislike_vector)
    lam = dislike_lambda if dislike_lambda is not None else w["avoid"]
    quality = bayesian_rating(movie) / 10.0
    # Map energy boost (~0.2–1.4) into a centered contribution
    energy = float(energy_boost - 1.0)
    runtime = _runtime_fit(movie, max_minutes, profile.avg_runtime)
    year = _year_fit(movie, profile)
    pop_pen = _popularity_penalty(movie)

    total = (
        w["taste"] * taste
        - lam * avoid
        + w["quality"] * quality
        + w["energy"] * energy
        + w["runtime_fit"] * runtime
        + w["year_fit"] * year
        - w["popularity_penalty"] * pop_pen
    )
    return ScoreBreakdown(
        taste=w["taste"] * taste,
        avoid=lam * avoid,
        quality=w["quality"] * quality,
        energy=w["energy"] * energy,
        runtime_fit=w["runtime_fit"] * runtime,
        year_fit=w["year_fit"] * year,
        popularity_penalty=w["popularity_penalty"] * pop_pen,
        total=float(total),
    )


def candidate_feature_row(
    space: FeatureSpace,
    profile: TasteProfile,
    index: int,
    *,
    energy_boost: float = 1.0,
    max_minutes: int | None = None,
) -> np.ndarray:
    """Raw features used by the linear re-ranker / eval ablations."""
    movie = space.movies[index]
    taste = (
        float(space.matrix[index] @ profile.vector)
        if space.matrix is not None and profile.vector is not None
        else 0.0
    )
    avoid = (
        float(space.matrix[index] @ profile.dislike_vector)
        if space.matrix is not None and profile.dislike_vector is not None
        else 0.0
    )
    return np.array(
        [
            taste,
            avoid,
            bayesian_rating(movie) / 10.0,
            float(energy_boost - 1.0),
            _runtime_fit(movie, max_minutes, profile.avg_runtime),
            _year_fit(movie, profile),
            _popularity_penalty(movie),
        ],
        dtype=np.float32,
    )


FEATURE_NAMES = [
    "taste",
    "avoid",
    "quality",
    "energy",
    "runtime_fit",
    "year_fit",
    "popularity_penalty",
]


def score_from_features(feats: np.ndarray, weights: dict[str, float]) -> float:
    w = weights
    return float(
        w["taste"] * feats[0]
        - w["avoid"] * feats[1]
        + w["quality"] * feats[2]
        + w["energy"] * feats[3]
        + w["runtime_fit"] * feats[4]
        + w["year_fit"] * feats[5]
        - w["popularity_penalty"] * feats[6]
    )


def grid_tune_weights(
    feature_rows: list[np.ndarray],
    labels: list[int],
    *,
    k: int = 10,
) -> tuple[dict[str, float], float]:
    """
    Tiny grid search maximizing HitRate@k on binary relevance labels.
    `feature_rows[i]` aligns with one held-out positive + sampled negatives
    already flattened is NOT assumed — instead we expect grouped lists via
    tune_grouped.
    """
    raise NotImplementedError("Use tune_weights_grouped")


def tune_weights_grouped(
    groups: list[tuple[list[np.ndarray], int]],
    *,
    k: int = 10,
) -> tuple[dict[str, float], dict[str, float]]:
    """
    groups: list of (candidate_feature_rows, index_of_relevant_item)
    Returns best weights and metrics dict.
    """
    if not groups:
        return dict(DEFAULT_WEIGHTS), {"hit_rate": 0.0, "ndcg": 0.0, "n": 0}

    taste_grid = [0.55, 0.70, 0.85]
    avoid_grid = [0.35, 0.55, 0.75]
    quality_grid = [0.10, 0.22, 0.35]

    best_w = dict(DEFAULT_WEIGHTS)
    best_score = -1.0
    best_metrics = {"hit_rate": 0.0, "ndcg": 0.0, "n": float(len(groups))}

    for tw in taste_grid:
        for aw in avoid_grid:
            for qw in quality_grid:
                w = dict(DEFAULT_WEIGHTS)
                w["taste"] = tw
                w["avoid"] = aw
                w["quality"] = qw
                hits = 0
                ndcgs = []
                for feats, rel_idx in groups:
                    scores = [score_from_features(f, w) for f in feats]
                    order = list(np.argsort(-np.asarray(scores)))
                    rank = order.index(rel_idx) if rel_idx in order else len(order)
                    if rank < k:
                        hits += 1
                        ndcgs.append(1.0 / np.log2(rank + 2))
                    else:
                        ndcgs.append(0.0)
                hr = hits / len(groups)
                ndcg = float(np.mean(ndcgs)) if ndcgs else 0.0
                # Prefer hit-rate, break ties with ndcg
                key = hr + 0.15 * ndcg
                if key > best_score:
                    best_score = key
                    best_w = w
                    best_metrics = {
                        "hit_rate": hr,
                        "ndcg": ndcg,
                        "n": float(len(groups)),
                    }

    return best_w, best_metrics


def blocked_ids(profile: TasteProfile, extra: set[int] | None = None) -> set[int]:
    """Rated + disliked + session not-interested."""
    blocked = set(profile.ratings.keys()) | set(profile.disliked_ids) | set(profile.liked_ids)
    if extra:
        blocked |= set(extra)
    return blocked
