"""Shared Streamlit session helpers for main app + behind-the-scenes page."""

from __future__ import annotations

import hashlib
from typing import Any

import streamlit as st

from .catalog import build_catalog
from .features import FeatureSpace, TasteProfile
from .ingest import load_persisted_catalog
from .tmdb import TMDBClient, TMDBError
from .ui import inject_theme


def bootstrap_page(title: str) -> None:
    inject_theme()
    st.markdown(f"### {title}")


def get_client() -> TMDBClient:
    client = st.session_state.get("tmdb")
    if client is None:
        client = TMDBClient()
        st.session_state.tmdb = client
    # Older sessions may still honor Cursor's broken HTTPS_PROXY.
    client.repair_session()
    return client


def _offline_catalog(seed_movies: list[dict] | None = None):
    """Fit features from persisted catalog.json when live TMDB is down."""
    from .clean import clean_catalog, normalize_movie

    persisted = load_persisted_catalog()
    if not persisted:
        raise TMDBError(
            "No saved catalog and TMDB is unreachable. "
            "Run scripts/ingest_catalog.py once with a working network."
        )
    cleaned, _ = clean_catalog(persisted, persist=False)
    seen = {m["id"]: m for m in cleaned if m.get("id") is not None}
    for seed in seed_movies or []:
        norm = normalize_movie(seed)
        if norm and norm.get("id") is not None:
            seen[norm["id"]] = norm
    catalog = list(seen.values())
    space = FeatureSpace().fit(catalog)
    return catalog, space


@st.cache_resource(show_spinner="Loading film library + feature space…")
def load_catalog(seed_ids: tuple[int, ...]):
    c = TMDBClient()
    c.repair_session()
    seeds: list[dict[str, Any]] = []
    persisted = {int(m["id"]): m for m in load_persisted_catalog() if m.get("id") is not None}
    for mid in seed_ids:
        if mid in persisted:
            seeds.append(persisted[mid])
            continue
        try:
            seeds.append(c.movie(mid))
        except TMDBError:
            continue
    try:
        catalog, space = build_catalog(
            c,
            seed_movies=seeds or None,
            pages=2,
            enrich_top=80,
            min_catalog=3500,
        )
        return catalog, space
    except TMDBError:
        return _offline_catalog(seeds)


def taste_lists_from_session() -> tuple[list[dict], list[dict], dict[int, float], list[dict]]:
    likes = list(st.session_state.get("taste_picks", []))
    dislikes = list(st.session_state.get("dislike_picks", []))
    ratings = dict(st.session_state.get("taste_ratings", {}))
    rated = list(st.session_state.get("rated_picks", []))
    # Union of everything we know about
    by_id: dict[int, dict] = {}
    for m in rated + likes + dislikes:
        if m.get("id") is not None:
            by_id[int(m["id"])] = m
    return likes, dislikes, ratings, list(by_id.values())


def build_session_profile(space: FeatureSpace) -> TasteProfile | None:
    likes, dislikes, ratings, rated = taste_lists_from_session()
    if not likes and not rated and not ratings:
        return None
    return space.build_taste(
        likes or [m for m in rated if ratings.get(m["id"], 0) >= 3.5],
        label="You",
        disliked=dislikes or [m for m in rated if ratings.get(m["id"], 5) <= 2.0],
        ratings=ratings,
        rated=rated,
    )


def ensure_space(extra_seeds: list[dict] | None = None):
    likes, dislikes, _, rated = taste_lists_from_session()
    seeds = list(extra_seeds or []) + likes + dislikes + rated
    seed_ids = tuple(sorted({int(m["id"]) for m in seeds if m.get("id") is not None}))
    try:
        return load_catalog(seed_ids)
    except TMDBError:
        return _offline_catalog(seeds)


def mood_cache_key(space) -> str:
    """Backend name + cheap hash of the matrix bytes.

    Use as the suffix of an ``st.session_state`` key so the cached Mood Map
    auto-rebuilds when the underlying feature space changes (e.g. after a
    catalog rebuild or seed addition) instead of silently serving a stale
    layout. Falls back to ``"empty"`` when the matrix is missing or the
    bytes call raises — that still differentiates "no mood yet" from
    "mood is current".
    """
    backend = getattr(space, "backend", "unknown")
    try:
        matrix = getattr(space, "matrix", None)
        if matrix is None:
            h = "empty"
        else:
            h = hashlib.sha1(matrix.data.tobytes()).hexdigest()[:16]
    except Exception:
        h = "empty"
    return f"{backend}:{h}"
