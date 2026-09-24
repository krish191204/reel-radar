"""Import taste from Letterboxd / generic ratings CSVs."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Callable

import pandas as pd

from .tmdb import TMDBClient, TMDBError


@dataclass
class ImportedTaste:
    likes: list[dict[str, Any]] = field(default_factory=list)
    dislikes: list[dict[str, Any]] = field(default_factory=list)
    rated: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    ratings: dict[int, float] = field(default_factory=dict)  # tmdb_id -> 0.5..5.0
    stats: dict[str, Any] = field(default_factory=dict)


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    cleaned = []
    for c in df.columns:
        name = str(c).replace("\ufeff", "").strip().lower()
        name = re.sub(r"\s+", " ", name)
        cleaned.append(name)
    df.columns = cleaned
    return df


def _pick_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def parse_ratings_csv(file_obj: BinaryIO | str | bytes) -> pd.DataFrame:
    """
    Accept Letterboxd export (`ratings.csv` / `diary.csv`) or a simple
    title,year,rating CSV.
    """
    if isinstance(file_obj, (bytes, bytearray)):
        raw: BinaryIO | str = io.BytesIO(file_obj)
    else:
        raw = file_obj
    df = pd.read_csv(raw)
    df = _norm_cols(df)
    title_col = _pick_col(df, ["name", "title", "film", "movie", "film title"])
    if not title_col:
        raise ValueError(
            "CSV needs a title column (Letterboxd: Name; or title / film / movie)."
        )
    year_col = _pick_col(df, ["year", "release year", "released"])
    rating_col = _pick_col(df, ["rating", "ratings", "stars", "score", "your rating"])
    out = pd.DataFrame()
    out["title"] = df[title_col].astype(str).str.strip()
    out["year"] = pd.to_numeric(df[year_col], errors="coerce") if year_col else None
    if rating_col:
        out["rating"] = pd.to_numeric(df[rating_col], errors="coerce")
    else:
        out["rating"] = 4.0  # watched / listed without stars → soft like
    out = out[out["title"].str.len() > 0]
    return out.reset_index(drop=True)


def _resolve_row(client: TMDBClient, title: str, year: float | None) -> dict[str, Any] | None:
    try:
        results = client.search_movies(title)
    except TMDBError:
        return None
    if not results:
        return None
    if year and not pd.isna(year):
        y = int(year)
        dated = []
        for r in results:
            rd = r.get("release_date") or ""
            if len(rd) >= 4 and rd[:4].isdigit() and abs(int(rd[:4]) - y) <= 1:
                dated.append(r)
        if dated:
            return dated[0]
    return results[0]


def import_taste_csv(
    client: TMDBClient,
    file_obj: BinaryIO | bytes,
    *,
    like_threshold: float = 3.5,
    dislike_threshold: float = 2.0,
    max_rows: int = 500,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> ImportedTaste:
    """
    Map CSV rows to TMDB movies.
    Letterboxd ratings are typically 0.5–5.0 stars.
    All resolved ratings are kept; likes/dislikes are convenience buckets.

    `max_rows` defaults to 500 (typical Letterboxd export is ~300–800 rows).
    `progress_cb(processed, total, last_title)` fires every row so the UI
    spinner can stay alive during a long import.
    """
    df = parse_ratings_csv(file_obj)
    # Prefer strongest opinions first, but keep a wide slice
    df = df.sort_values("rating", ascending=False, na_position="last").head(max_rows)

    total = int(len(df))
    result = ImportedTaste()
    seen_ids: set[int] = set()
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        title = str(row["title"])
        year = row.get("year")
        rating = float(row["rating"]) if pd.notna(row.get("rating")) else 4.0
        if rating > 5.5:
            rating = rating / 2.0
        rating = max(0.5, min(5.0, rating))

        movie = _resolve_row(client, title, year)
        if not movie or not movie.get("id"):
            result.unresolved.append(title)
            if progress_cb:
                try:
                    progress_cb(i, total, title)
                except Exception:  # noqa: BLE001
                    pass
            continue
        mid = int(movie["id"])
        if mid in seen_ids:
            if progress_cb:
                try:
                    progress_cb(i, total, title)
                except Exception:  # noqa: BLE001
                    pass
            continue
        seen_ids.add(mid)
        result.ratings[mid] = rating
        result.rated.append(movie)

        if rating >= like_threshold:
            result.likes.append(movie)
        elif rating <= dislike_threshold:
            result.dislikes.append(movie)

        if progress_cb:
            try:
                progress_cb(i, total, title)
            except Exception:  # noqa: BLE001
                pass

    result.stats = {
        "rows_read": total,
        "rated": len(result.rated),
        "likes": len(result.likes),
        "dislikes": len(result.dislikes),
        "mid": len(result.rated) - len(result.likes) - len(result.dislikes),
        "unresolved": len(result.unresolved),
        "avg_rating": round(
            sum(result.ratings.values()) / max(len(result.ratings), 1), 2
        ),
        "backend": "letterboxd_or_generic_csv",
    }
    return result
