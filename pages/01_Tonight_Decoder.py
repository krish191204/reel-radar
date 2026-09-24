"""Tonight Decoder page."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.events import log_event
from src.recommenders import tonight_decoder
from src.streamlit_shell import cached_genres, current_user, init_page, load_workspace, require_taste
from src.ui import empty_state, panel_header, render_explained_tickets, top_nav

init_page("Tonight Decoder")
top_nav("tonight")
catalog, space, profile, ratings, likes, dislikes, rated = load_workspace()
panel_header(
    "Tonight Decoder",
    "Time, energy, hard nos — margin-ranked picks with score breakdowns.",
)

if not require_taste(profile):
    st.stop()

c1, c2, c3 = st.columns(3)
with c1:
    minutes = st.slider("Minutes you've got", 60, 210, 120, 5)
with c2:
    energy = st.selectbox(
        "Energy",
        ["cozy", "tense", "brain-on", "adrenaline", "melancholy"],
    )
with c3:
    genres = cached_genres()
    name_to_id = {g["name"]: g["id"] for g in genres}
    hard = st.multiselect("Hard-no genres", list(name_to_id.keys()))
    hard_ids = [name_to_id[n] for n in hard]

if st.button("Decode tonight", type="primary"):
    with st.spinner("Decoding tonight…"):
        try:
            recs = tonight_decoder(
                space,
                profile,
                catalog,
                max_minutes=minutes,
                energy=energy,
                hard_no_genres=hard_ids,
            )
            st.session_state["last_recs"] = recs
            log_event(
                "decode",
                mode="tonight",
                user=current_user(),
                meta={
                    "minutes": minutes,
                    "energy": energy,
                    "hard_nos": hard_ids,
                    "n": len(recs),
                    "backend": space.backend,
                },
            )
        except Exception as e:
            st.error(f"Couldn't decode tonight: {e.__class__.__name__}")
            st.session_state["last_recs"] = []

recs = st.session_state.get("last_recs", [])
if recs:
    render_explained_tickets(recs, interactive=True, mode="tonight")
else:
    empty_state(
        "Ready when you are",
        "Set tonight's constraints, then decode.",
        cta_label="Open taste booth",
        cta_page="Home",
    )
