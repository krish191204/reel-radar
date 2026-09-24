"""Group Peace Treaty page."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app_state import ensure_space
from src.recommenders import group_peace_treaty
from src.streamlit_shell import init_page, load_workspace, require_taste, search_and_pick
from src.tmdb import TMDBError
from src.ui import empty_state, panel_header, render_explained_tickets, top_nav

init_page("Group Peace Treaty")
top_nav("group")
catalog, space, profile, ratings, likes, dislikes, rated = load_workspace()
panel_header("Group Peace Treaty", "Minimize maximum regret across everyone on the couch.")

if not require_taste(profile):
    st.stop()

st.caption("Watcher A uses your sidebar taste. Add the rest of the couch below.")
b_picks = search_and_pick("Watcher B films", "group_b")
c_picks = search_and_pick("Watcher C films (optional)", "group_c")

if b_picks and st.button("Negotiate peace", type="primary"):
    all_group = likes + dislikes + rated + b_picks + c_picks
    try:
        with st.spinner("Negotiating with the couch…"):
            _, space2 = ensure_space(all_group)
            profiles = [
                space2.build_taste(
                    likes,
                    label="A",
                    disliked=dislikes,
                    ratings=ratings,
                    rated=rated,
                ),
                space2.build_taste(b_picks, label="B"),
            ]
            if c_picks:
                profiles.append(space2.build_taste(c_picks, label="C"))
            st.session_state["group_recs"] = group_peace_treaty(space2, profiles)
    except TMDBError as e:
        st.error(f"Couldn't build the peace treaty: {e}")
    except Exception as e:
        st.error(f"Peace negotiation crashed: {e.__class__.__name__}")

recs = st.session_state.get("group_recs", [])
if recs:
    render_explained_tickets(recs, interactive=True, mode="group_peace_treaty")
else:
    empty_state(
        "Couch empty",
        "Add Watcher B's loves, then negotiate.",
        cta_label="Open taste booth",
        cta_page="Home",
    )
