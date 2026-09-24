"""Anti-Bubble page."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.recommenders import anti_bubble
from src.streamlit_shell import init_page, load_workspace, require_taste
from src.ui import empty_state, panel_header, render_explained_tickets, top_nav

init_page("Anti-Bubble")
top_nav("anti")
catalog, space, profile, *_ = load_workspace()
panel_header("Anti-Bubble", "One comfort pick, one stretch, one delicious risk.")

if not require_taste(profile):
    st.stop()

if st.button("Pop the bubble", type="primary"):
    with st.spinner("Popping the bubble…"):
        try:
            st.session_state["bubble_recs"] = anti_bubble(space, profile)
        except Exception as e:
            st.error(f"Couldn't pop the bubble: {e.__class__.__name__}")
            st.session_state["bubble_recs"] = []

recs = st.session_state.get("bubble_recs", [])
if recs:
    render_explained_tickets(recs, interactive=True, mode="anti_bubble")
else:
    empty_state(
        "Bubble intact",
        "Pop it when you want controlled whiplash.",
        cta_label="Open taste booth",
        cta_page="Home",
    )
