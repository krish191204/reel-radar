"""Normalize + clean the persisted TMDB catalog into a lean, recommendable set."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .ingest import CATALOG_PATH, DATA_DIR, save_catalog
from .quality import (
    MIN_OVERVIEW_LEN,
    MIN_POPULARITY,
    MIN_VOTE_COUNT,
    TV_MOVIE_GENRE,
    bayesian_rating,
    is_recommendable,
    vote_count,
)

REPORT_PATH = DATA_DIR / "clean_report.json"

# Lean schema kept on disk for recommenders / feature space
CATALOG_FIELDS = (
    "id",
    "title",
    "original_title",
    "overview",
    "tagline",
    "release_date",
    "runtime",
    "genre_ids",
    "vote_average",
    "vote_count",
    "popularity",
    "poster_path",
    "backdrop_path",
    "original_language",
    "adult",
    "video",
    "status",
)


def _genre_ids(movie: dict[str, Any]) -> list[int]:
    if movie.get("genre_ids"):
        return [int(g) for g in movie["genre_ids"] if g is not None]
    genres = movie.get("genres") or []
    out = []
    for g in genres:
        if isinstance(g, dict) and g.get("id") is not None:
            out.append(int(g["id"]))
    return out


def normalize_movie(movie: dict[str, Any]) -> dict[str, Any] | None:
    """Collapse stubs + enriched blobs into one lean record."""
    mid = movie.get("id")
    if mid is None:
        return None
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return None

    overview = (movie.get("overview") or "").strip()
    title = (movie.get("title") or movie.get("original_title") or "").strip()
    if not title:
        return None

    rec: dict[str, Any] = {
        "id": mid,
        "title": title,
        "original_title": (movie.get("original_title") or title).strip(),
        "overview": overview,
        "tagline": (movie.get("tagline") or "").strip() or None,
        "release_date": movie.get("release_date") or "",
        "runtime": movie.get("runtime"),
        "genre_ids": _genre_ids(movie),
        "vote_average": float(movie.get("vote_average") or 0.0),
        "vote_count": vote_count(movie),
        "popularity": float(movie.get("popularity") or 0.0),
        "poster_path": movie.get("poster_path"),
        "backdrop_path": movie.get("backdrop_path"),
        "original_language": movie.get("original_language") or None,
        "adult": bool(movie.get("adult")),
        "video": bool(movie.get("video")),
        "status": movie.get("status"),
    }
    # Drop null tagline/runtime noise for compactness
    if not rec["tagline"]:
        rec.pop("tagline", None)
    if rec["runtime"] in (None, 0):
        rec.pop("runtime", None)
    return rec


def clean_reasons(movie: dict[str, Any]) -> list[str]:
    """Why a normalized movie would be dropped."""
    reasons: list[str] = []
    if movie.get("adult"):
        reasons.append("adult")
    if movie.get("video"):
        reasons.append("video_flag")
    status = movie.get("status")
    if status and status not in {"Released", None}:
        reasons.append(f"status:{status}")
    if not (movie.get("release_date") or ""):
        reasons.append("no_release_date")
    else:
        year = movie["release_date"][:4]
        if year.isdigit() and int(year) > 2026:
            reasons.append("future_release")
    if vote_count(movie) < MIN_VOTE_COUNT:
        reasons.append("low_votes")
    if len((movie.get("overview") or "").strip()) < MIN_OVERVIEW_LEN:
        reasons.append("short_overview")
    if float(movie.get("popularity") or 0.0) < MIN_POPULARITY:
        reasons.append("low_popularity")
    if not movie.get("genre_ids"):
        reasons.append("no_genres")
    if TV_MOVIE_GENRE in (movie.get("genre_ids") or []):
        reasons.append("tv_movie")
    if not movie.get("poster_path"):
        reasons.append("no_poster")
    if not is_recommendable(movie):
        # catch-all if gate tightened beyond listed reasons
        if not reasons:
            reasons.append("not_recommendable")
    return reasons


def clean_catalog(
    movies: list[dict[str, Any]] | None = None,
    *,
    path: Path = CATALOG_PATH,
    persist: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Normalize schema, drop junk, dedupe, persist lean catalog + report.
    """
    from .ingest import load_persisted_catalog

    raw = movies if movies is not None else load_persisted_catalog(path)
    dropped = Counter()
    examples: dict[str, list[str]] = {}
    by_id: dict[int, dict[str, Any]] = {}

    for raw_movie in raw:
        norm = normalize_movie(raw_movie)
        if norm is None:
            dropped["invalid_record"] += 1
            continue
        reasons = clean_reasons(norm)
        # Allow missing status (list endpoints don't include it)
        reasons = [r for r in reasons if not r.startswith("status:")]
        # poster optional? keep requiring poster for UI quality
        if reasons:
            for r in reasons:
                dropped[r] += 1
                examples.setdefault(r, [])
                if len(examples[r]) < 5:
                    examples[r].append(f"{norm.get('title')} ({norm.get('id')})")
            continue
        prev = by_id.get(norm["id"])
        if prev is None or vote_count(norm) >= vote_count(prev):
            by_id[norm["id"]] = norm

    cleaned = sorted(
        by_id.values(),
        key=lambda m: (bayesian_rating(m), m.get("popularity") or 0.0),
        reverse=True,
    )

    report = {
        "cleaned_at": int(time.time()),
        "input_count": len(raw),
        "output_count": len(cleaned),
        "dropped": dict(dropped),
        "examples": examples,
        "thresholds": {
            "min_vote_count": MIN_VOTE_COUNT,
            "min_overview_len": MIN_OVERVIEW_LEN,
            "min_popularity": MIN_POPULARITY,
        },
        "languages": dict(Counter(m.get("original_language") or "?" for m in cleaned).most_common(12)),
        "avg_vote_count": round(
            sum(vote_count(m) for m in cleaned) / max(len(cleaned), 1), 1
        ),
        "bayesian_rating_p50": None,
    }
    if cleaned:
        ratings = sorted(bayesian_rating(m) for m in cleaned)
        report["bayesian_rating_p50"] = round(ratings[len(ratings) // 2], 3)

    if persist:
        save_catalog(cleaned, path)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return cleaned, report
