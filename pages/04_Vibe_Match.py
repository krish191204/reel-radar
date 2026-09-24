"""Vibe Match page."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.recommenders import vibe_match
from src.streamlit_shell import init_page, load_workspace
from src.ui import empty_state, panel_header, render_explained_tickets, top_nav

init_page("Vibe Match")
top_nav("vibe")
catalog, space, profile, *_ = load_workspace()
panel_header("Vibe Match", "Describe a vibe, scene, weather, or feeling.")

vibe = st.text_area(
    "Your vibe",
    placeholder="rainy city, lonely but hopeful, neon reflections, soft synth…",
    height=120,
)
st.caption("Type a vibe — e.g. 'rainy city, lonely, neon' — to see matches.")

vibe_stripped = vibe.strip()
if st.button(
    "Match the vibe",
    type="primary",
    disabled=not bool(vibe_stripped),
) and vibe_stripped:
    with st.spinner("Matching the vibe…"):
        try:
            blocked = set()
            if profile:
                blocked = set(profile.liked_ids) | set(profile.disliked_ids)
            st.session_state["vibe_recs"] = vibe_match(space, vibe_stripped, blocked)
        except Exception as e:
            st.error(f"Couldn't match the vibe: {e.__class__.__name__}")
            st.session_state["vibe_recs"] = []

recs = st.session_state.get("vibe_recs", [])
if recs:
    render_explained_tickets(recs, interactive=True, mode="vibe_match")
else:
    empty_state(
        "Waiting for weather",
        "Type a vibe and match it.",
        cta_label="Open taste booth",
        cta_page="Home",
    )
