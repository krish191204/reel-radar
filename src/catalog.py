"""Shared catalog builder for recommendation modes."""

from __future__ import annotations

from typing import Any

from .clean import normalize_movie
from .features import FeatureSpace, year_of
from .ingest import (
    DEFAULT_TARGET,
    ingest_catalog,
    load_persisted_catalog,
    save_catalog,
)
from .quality import filter_catalog
from .tmdb import TMDBClient


def enrich(client: TMDBClient, stub: dict[str, Any]) -> dict[str, Any]:
    """Fetch full movie details when we need runtime/credits/keywords."""
    if stub.get("_enriched") and stub.get("runtime") is not None:
        return stub
    full = client.movie(stub["id"])
    full["_enriched"] = True
    return full


def build_catalog(
    client: TMDBClient,
    seed_movies: list[dict[str, Any]] | None = None,
    pages: int = 3,
    enrich_top: int = 40,
    *,
    min_catalog: int = DEFAULT_TARGET,
    force_ingest: bool = False,
) -> tuple[list[dict[str, Any]], FeatureSpace]:
    """
    Load a large persisted TMDB catalog (ingesting if needed), merge seeds,
    normalize/clean, lightly enrich a popularity subset for runtime, fit features.
    """
    from .clean import clean_catalog

    persisted = load_persisted_catalog()
    # Only bulk-ingest when the library is missing or clearly too small.
    # (Cleaning shrinks raw pulls, so don't thrash ingest on every boot.)
    min_before_ingest = max(800, min_catalog // 2)
    if force_ingest or len(persisted) < min_before_ingest:
        persisted = ingest_catalog(
            client,
            target=min_catalog,
            force=force_ingest,
        )

    # Always normalize + quality-filter before fitting
    cleaned, _report = clean_catalog(persisted, persist=True)
    seen: dict[int, dict[str, Any]] = {m["id"]: m for m in cleaned}

    def add_many(items: list[dict[str, Any]]) -> None:
        for m in items:
            norm = normalize_movie(m)
            if not norm:
                continue
            mid = norm["id"]
            if mid not in seen:
                # only accept quality titles into the live room
                if filter_catalog([norm]):
                    seen[mid] = norm

    for page in range(1, max(1, pages) + 1):
        try:
            add_many(client.popular(page=page))
            add_many(client.top_rated(page=page))
        except Exception:
            break
    try:
        add_many(client.trending("week"))
    except Exception:
        pass

    if seed_movies:
        for seed in seed_movies:
            norm = normalize_movie(seed)
            if norm:
                seen[norm["id"]] = norm
        for seed in seed_movies[:8]:
            try:
                detail = enrich(client, seed)
                norm = normalize_movie(detail)
                if norm:
                    # keep runtime on the lean record when we have it
                    if detail.get("runtime"):
                        norm["runtime"] = detail["runtime"]
                    seen[norm["id"]] = norm
                add_many(detail.get("recommendations", {}).get("results", []))
                add_many(detail.get("similar", {}).get("results", []))
            except Exception:
                continue

    catalog = list(seen.values())

    # Pull runtime onto a popularity subset without bloating catalog with credits
    for i, m in enumerate(sorted(catalog, key=lambda x: x.get("popularity") or 0, reverse=True)):
        if i >= enrich_top:
            break
        if m.get("runtime"):
            continue
        try:
            detail = enrich(client, m)
            if detail.get("runtime"):
                m["runtime"] = detail["runtime"]
                seen[m["id"]] = m
        except Exception:
            continue

    catalog = list(seen.values())
    save_catalog(catalog)
    space = FeatureSpace().fit(catalog)
    return catalog, space


def exclude_seen(movies: list[dict[str, Any]], liked_ids: set[int]) -> list[dict[str, Any]]:
    return [m for m in movies if m.get("id") not in liked_ids]


def runtime_ok(movie: dict[str, Any], max_minutes: int | None) -> bool:
    if not max_minutes:
        return True
    rt = movie.get("runtime")
    if not rt:
        # Unknown runtime: allow if release exists and max is generous
        return max_minutes >= 100
    return int(rt) <= max_minutes


def year_in_decade(movie: dict[str, Any], decade: int) -> bool:
    y = year_of(movie)
    return y is not None and decade <= y <= decade + 9
