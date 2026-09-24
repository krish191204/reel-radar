"""Bulk TMDB catalog ingest + persistence."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .tmdb import TMDBClient, TMDBError
from .quality import filter_catalog, is_recommendable

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"
DEFAULT_TARGET = 10000


ProgressCb = Callable[[str, int, int], None]


def _noop_progress(message: str, current: int, total: int) -> None:
    return None


def _merge(seen: dict[int, dict[str, Any]], items: list[dict[str, Any]]) -> int:
    added = 0
    for m in items:
        mid = m.get("id")
        if not mid:
            continue
        # Soft gate during ingest: keep raw popular pages but drop empty stubs early
        if not (m.get("overview") or "").strip() and (m.get("vote_count") or 0) < 20:
            continue
        if mid not in seen:
            seen[mid] = m
            added += 1
        else:
            prev = seen[mid]
            if len(m.get("overview") or "") > len(prev.get("overview") or ""):
                seen[mid] = {**prev, **m}
    return added


def load_persisted_catalog(path: Path = CATALOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return list(raw.get("movies") or [])
    if isinstance(raw, list):
        return raw
    return []


def save_catalog(movies: list[dict[str, Any]], path: Path = CATALOG_PATH) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "count": len(movies),
        "updated_at": int(time.time()),
        "movies": movies,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def ingest_catalog(
    client: TMDBClient,
    target: int = DEFAULT_TARGET,
    *,
    force: bool = False,
    path: Path = CATALOG_PATH,
    progress: ProgressCb = _noop_progress,
    request_pause: float = 0.05,
) -> list[dict[str, Any]]:
    """
    Pull at least `target` distinct movies from TMDB and persist to disk.

    Uses popular, top-rated, and decade/genre discover sweeps for coverage.
    """
    existing = [] if force else load_persisted_catalog(path)
    seen: dict[int, dict[str, Any]] = {m["id"]: m for m in existing if m.get("id")}
    progress(f"Starting with {len(seen)} persisted titles", len(seen), target)

    def pause() -> None:
        if request_pause > 0:
            time.sleep(request_pause)

    # --- Popular + top rated (high quality spine) ---
    for label, fetcher, pages in (
        ("popular", client.popular, 60),
        ("top_rated", client.top_rated, 60),
    ):
        for page in range(1, pages + 1):
            if len(seen) >= target:
                break
            try:
                batch = fetcher(page=page)
            except TMDBError:
                break
            _merge(seen, batch)
            progress(f"{label} page {page}", len(seen), target)
            pause()
            if not batch:
                break
        if len(seen) >= target:
            break

    # --- Trending ---
    if len(seen) < target:
        try:
            _merge(seen, client.trending("week"))
            pause()
            _merge(seen, client.trending("day"))
            pause()
        except TMDBError:
            pass

    # --- Stratified decade quotas (coverage before popularity fill) ---
    # Ensure Mood Map / Taste Twin aren't stuck on modern-popular islands.
    decades = list(range(1940, 2030, 10))
    per_decade_floor = max(40, min(120, target // max(8, len(decades))))
    sort_modes = ("vote_count.desc", "vote_average.desc", "popularity.desc", "primary_release_date.desc")

    def _decade_count(decade: int) -> int:
        n = 0
        for m in seen.values():
            d = m.get("release_date") or ""
            if len(d) < 4 or not d[:4].isdigit():
                continue
            y = int(d[:4])
            if decade <= y <= decade + 9:
                n += 1
        return n

    for decade in decades:
        if len(seen) >= int(target * 1.15):
            break
        for sort_by in sort_modes:
            if _decade_count(decade) >= per_decade_floor:
                break
            if len(seen) >= int(target * 1.15):
                break
            for page in range(1, 16):
                if _decade_count(decade) >= per_decade_floor:
                    break
                try:
                    batch = client.discover(
                        primary_release_date_gte=f"{decade}-01-01",
                        primary_release_date_lte=f"{decade + 9}-12-31",
                        sort_by=sort_by,
                        vote_count_gte=80,
                        include_adult=False,
                        without_genres="10770",
                        page=page,
                    )
                except TMDBError:
                    break
                added = _merge(seen, batch)
                progress(
                    f"strat decade {decade}s {sort_by} p{page} ({_decade_count(decade)}/{per_decade_floor})",
                    len(seen),
                    target,
                )
                pause()
                if not batch:
                    break
                if added == 0 and page > 4:
                    break

    # --- Stratified genre quotas ---
    try:
        genres = client.genres()
    except TMDBError:
        genres = []
    # Skip TV Movie genre id if present
    genres = [g for g in genres if g.get("id") and g.get("id") != 10770]
    per_genre_floor = max(25, min(80, target // max(12, len(genres) or 12)))

    def _genre_count(gid: int) -> int:
        n = 0
        for m in seen.values():
            gids = m.get("genre_ids")
            if gids is None:
                gids = [g.get("id") for g in (m.get("genres") or []) if isinstance(g, dict)]
            if gids and gid in gids:
                n += 1
        return n

    for g in genres:
        if len(seen) >= int(target * 1.2):
            break
        gid = int(g["id"])
        for sort_by in ("vote_count.desc", "popularity.desc", "vote_average.desc"):
            if _genre_count(gid) >= per_genre_floor:
                break
            for page in range(1, 8):
                if _genre_count(gid) >= per_genre_floor:
                    break
                try:
                    batch = client.discover(
                        with_genres=str(gid),
                        sort_by=sort_by,
                        vote_count_gte=60,
                        include_adult=False,
                        without_genres="10770",
                        page=page,
                    )
                except TMDBError:
                    break
                _merge(seen, batch)
                progress(
                    f"strat genre {g.get('name')} {sort_by} p{page} ({_genre_count(gid)}/{per_genre_floor})",
                    len(seen),
                    target,
                )
                pause()

    # --- Broad popularity discover fill ---
    page = 1
    while len(seen) < target and page <= 120:
        try:
            batch = client.discover(
                sort_by="popularity.desc",
                vote_count_gte=50,
                include_adult=False,
                page=page,
            )
        except TMDBError:
            break
        added = _merge(seen, batch)
        progress(f"discover fill p{page}", len(seen), target)
        pause()
        if not batch:
            break
        if added == 0 and page > 5:
            # Still advance a bit in case of overlap, then stop if stuck
            if page > 30:
                break
        page += 1

    # --- Deep fill (no vote_count filter) to widen the net ---
    # Casts a much wider net so the catalog grows beyond the ~2500 plateau that
    # vote_count_gte filters hit. Each pass covers ~500 unique titles per page.
    for sort_by, page_cap in (
        ("popularity.desc", 80),
        ("vote_count.desc", 60),
        ("primary_release_date.desc", 40),
    ):
        for page in range(1, page_cap + 1):
            try:
                batch = client.discover(
                    sort_by=sort_by,
                    include_adult=False,
                    page=page,
                )
            except TMDBError:
                break
            added = _merge(seen, batch)
            progress(f"deep fill {sort_by} p{page}", len(seen), target)
            pause()
            if not batch:
                break
            if added == 0 and page > 20:
                break
        if len(seen) >= target * 1.2:
            break

    movies = sorted(seen.values(), key=lambda m: m.get("popularity") or 0, reverse=True)
    # Persist only recommendable titles so the library itself stays clean
    movies = filter_catalog(movies)
    # If quality filter shrank us too far, keep a softer set so we still have volume.
    # Soft floor drops min_votes from 80 (strict) → 15 so we keep ~3-4× more titles.
    if len(movies) < max(500, target // 3):
        movies = sorted(
            [m for m in seen.values() if is_recommendable(
                m, min_votes=15, min_overview=15, min_popularity=0.2
            )],
            key=lambda m: m.get("popularity") or 0,
            reverse=True,
        )
    save_catalog(movies, path)
    progress(f"Saved {len(movies)} movies to {path.name}", len(movies), target)
    return movies
