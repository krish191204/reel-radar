"""Taste Twin page."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features import FeatureSpace
from src.recommenders import taste_twin
from src.streamlit_shell import get_client, init_page, load_workspace, require_taste
from src.tmdb import TMDBError
from src.ui import empty_state, panel_header, render_explained_tickets, top_nav

init_page("Taste Twin")
top_nav("twin")
catalog, space, profile, ratings, likes, dislikes, rated = load_workspace()
panel_header("Taste Twin", "Your modern taste, remapped onto another decade.")

if not require_taste(profile):
    st.stop()

decade = st.select_slider(
    "Target decade",
    options=list(range(1940, 2020, 10)),
    value=1970,
    format_func=lambda d: f"{d}s",
)

if st.button("Find my twin", type="primary"):
    with st.spinner("Finding your twin from this decade…"):
        client = get_client()
        extras: list[dict] = []
        try:
            extras = client.discover(
                primary_release_date_gte=f"{decade}-01-01",
                primary_release_date_lte=f"{decade + 9}-12-31",
                sort_by="vote_average.desc",
                vote_count_gte=200,
                without_genres="10770",
                page=1,
            )
            extras += client.discover(
                primary_release_date_gte=f"{decade}-01-01",
                primary_release_date_lte=f"{decade + 9}-12-31",
                sort_by="popularity.desc",
                vote_count_gte=100,
                without_genres="10770",
                page=1,
            )
        except TMDBError as e:
            st.warning(f"TMDB twin search failed: {e}")
        try:
            merged = {m["id"]: m for m in catalog}
            for m in extras:
                merged[m["id"]] = m
            twin_space = FeatureSpace().fit(list(merged.values()))
            twin_profile = twin_space.build_taste(
                likes,
                label="You",
                disliked=dislikes,
                ratings=ratings,
                rated=rated,
            )
            st.session_state["twin_recs"] = taste_twin(twin_space, twin_profile, decade)
        except Exception as e:
            st.error(f"Twin pipeline failed: {e.__class__.__name__}")
            st.session_state["twin_recs"] = []

recs = st.session_state.get("twin_recs", [])
if recs:
    render_explained_tickets(recs, interactive=True, mode="taste_twin")
else:
    empty_state(
        "Pick a decade",
        "Then find your twin from that era.",
        cta_label="Open taste booth",
        cta_page="Home",
    )
