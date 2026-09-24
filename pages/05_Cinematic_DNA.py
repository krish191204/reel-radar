"""Cinematic DNA page."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.recommenders import cinematic_dna
from src.streamlit_shell import get_client, init_page, load_workspace, search_and_pick
from src.tmdb import TMDBError
from src.ui import empty_state, panel_header, render_explained_tickets, top_nav

init_page("Cinematic DNA")
top_nav("dna")
catalog, space, profile, ratings, likes, dislikes, rated = load_workspace()
panel_header("Cinematic DNA", "Follow directors, DPs, composers, editors, and cast.")

st.caption("Pick a seed film, or we'll use your first taste seed.")
dna_seeds = search_and_pick("Seed film for DNA", "dna", max_results=5)
seed = dna_seeds[0] if dna_seeds else (likes[0] if likes else None)

if seed:
    st.caption(f"Tracing lineage from {seed.get('title')}")

if seed and st.button("Trace the lineage", type="primary"):
    with st.spinner("Walking the credit graph…"):
        try:
            st.session_state["dna_recs"] = cinematic_dna(get_client(), seed)
        except TMDBError as e:
            st.error(f"Couldn't trace lineage for {seed.get('title', 'this seed')}: {e}")
            st.session_state["dna_recs"] = []
        except Exception as e:
            st.error(f"DNA walk failed: {e.__class__.__name__}")
            st.session_state["dna_recs"] = []

recs = st.session_state.get("dna_recs", [])
if recs:
    render_explained_tickets(recs, interactive=True, mode="cinematic_dna")
elif not seed:
    empty_state(
        "Need a seed",
        "Add a film above or import loves on Home.",
        cta_label="Open taste booth",
        cta_page="Home",
    )
else:
    empty_state(
        "Ready to trace",
        "Hit the button to walk the credit graph.",
        cta_label="Open taste booth",
        cta_page="Home",
    )
