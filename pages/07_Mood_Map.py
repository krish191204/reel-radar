"""Mood Map page."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app_state import mood_cache_key
from src.features import year_of
from src.recommenders import mood_map, recommend_in_mood
from src.streamlit_shell import init_page, load_workspace, poster
from src.ui import empty_state, panel_header, render_explained_tickets, seed_chips, top_nav

init_page("Mood Map")
top_nav("mood")
catalog, space, profile, *_ = load_workspace()
panel_header("Mood Map", "Cluster the catalog into spoiler-free mood territories.")

# Auto-build on first visit; rebuild when the feature space changes or the
# user moves the n_clusters slider.
n = st.slider("Mood territories", 4, 8, 6)
key = mood_cache_key(space)
stored_key = st.session_state.get("mood_key")
mood = st.session_state.get("mood")
needs_build = mood is None or stored_key != f"{key}:{n}"

if needs_build:
    with st.spinner("Clustering territories…"):
        try:
            st.session_state["mood"] = mood_map(space, profile, n_clusters=n)
            st.session_state["mood_key"] = f"{key}:{n}"
            mood = st.session_state["mood"]
        except Exception as e:
            st.error(f"Couldn't build mood map: {e.__class__.__name__}")
            st.session_state["mood"] = None
            mood = None

if not mood:
    empty_state(
        "Mood map still useful without taste",
        "We'll cluster the whole catalog into 4–8 territories. Add taste to see which one is yours.",
        cta_label="Open taste booth",
        cta_page="Home",
    )
    st.stop()

if mood.get("user_placement"):
    up = mood["user_placement"]
    st.success(f"Home territory: {up['cluster_name']}")

for cluster in mood["clusters"]:
    with st.expander(f"{cluster['name']} · {cluster['size']} films"):
        seed_chips([{"title": t, "release_date": ""} for t in cluster["tags"]])
        cols = st.columns(4)
        for i, m in enumerate(cluster["exemplars"][:4]):
            with cols[i]:
                poster(m, width=120)
                y = year_of(m)
                st.caption(m.get("title", "") + (f" ({y})" if y else ""))
        if st.button("Recommend in this mood", key=f"mood_rec_{cluster['id']}"):
            try:
                st.session_state["mood_recs"] = recommend_in_mood(
                    space, mood, cluster["id"], profile
                )
            except Exception as e:
                st.error(f"Couldn't recommend in mood: {e.__class__.__name__}")
                st.session_state["mood_recs"] = []

if st.session_state.get("mood_recs"):
    st.markdown("#### Picks from selected territory")
    render_explained_tickets(
        st.session_state["mood_recs"], interactive=True, mode="mood"
    )
