"""Watchlist — films saved for later, with a 'what to watch next' ranker."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src.auth import AuthError, TASTE_KEYS, save_taste
from src.events import log_event
from src.recommenders import RecItem
from src.streamlit_shell import (
    current_user,
    init_page,
    load_workspace,
)
from src.ui import (
    empty_state,
    panel_header,
    render_explained_tickets,
    seed_chips,
    top_nav,
)


def _persist_watchlist(username: str, picks: list[dict]) -> None:
    """Write just the watchlist_picks key back to the user's record."""
    payload = {
        key: st.session_state.get(key, [] if key != "taste_ratings" else {})
        for key in TASTE_KEYS
    }
    payload["watchlist_picks"] = picks
    try:
        save_taste(username, payload)
    except AuthError as e:
        st.warning(f"Could not save watchlist: {e}")


def _year(movie: dict) -> str:
    rd = movie.get("release_date") or ""
    return rd[:4] if len(rd) >= 4 else "?"


def _build_next_picks(
    watchlist: list[dict], profile, space, ratings
) -> list[dict]:
    """Rank the catalog using the watchlist as a 0.3-weight positive seed
    mixed with the user's main profile. Returns up to 3 fresh picks, all
    in the watchlist + ratings blocked out.
    """
    blocked = {int(m["id"]) for m in watchlist} | set(ratings.keys())
    if not watchlist:
        return []

    if profile is None or profile.vector is None:
        # No taste yet — fall back to quality ranking across the watchlist.
        from src.quality import bayesian_rating

        eligible = [
            m for m in watchlist if (m.get("vote_count") or 0) >= 30
        ]
        eligible.sort(key=lambda m: bayesian_rating(m), reverse=True)
        return eligible[:3]

    # Build a watchlist-only profile and blend with the main one.
    wl_ratings = {
        int(m["id"]): 4.5 for m in watchlist if m.get("id") is not None
    }
    wl_profile = space.build_taste(
        watchlist, label="Saved", ratings=wl_ratings
    )
    if wl_profile.vector is None:
        return []
    wl_sims = space.cosine_to_taste(wl_profile, dislike_penalty=0)
    main_sims = space.cosine_to_taste(profile, dislike_penalty=0)
    sims = 0.7 * main_sims + 0.3 * wl_sims

    order = np.argsort(-sims)
    picks: list[dict] = []
    for idx in order:
        idx_i = int(idx)
        if idx_i >= len(space.movies):
            continue
        m = space.movies[idx_i]
        mid = int(m.get("id", 0))
        if mid in blocked or not m.get("id"):
            continue
        picks.append(m)
        if len(picks) >= 3:
            break
    return picks


init_page("Watchlist", icon=":bookmark:")
top_nav("watch")
catalog, space, profile, ratings, likes, dislikes, rated = load_workspace()

user = current_user()
watchlist = list(st.session_state.get("watchlist_picks", []))

panel_header("Watchlist", f"{len(watchlist)} saved for later")

if not watchlist:
    empty_state(
        "Nothing saved yet",
        "Tap Save on any ticket to keep it for later. We'll line up what to watch next.",
        cta_label="Browse modes",
        cta_page="Tonight_Decoder",
    )
else:
    # Chips with per-chip remove.
    cols_html = "".join(
        f'<span class="rr-chip accent">{m.get("title", "Untitled")} '
        f'({_year(m)})</span>'
        for m in watchlist
    )
    st.markdown(
        f'<div class="rr-chip-row">{cols_html}</div>', unsafe_allow_html=True
    )
    for i, m in enumerate(watchlist):
        c1, c2 = st.columns([5, 1])
        with c1:
            st.write(f"**{m.get('title', 'Untitled')}** ({_year(m)})")
        with c2:
            if st.button("Remove", key=f"wl_rm_{m.get('id', i)}"):
                new_watchlist = [
                    w for w in watchlist if w.get("id") != m.get("id")
                ]
                st.session_state["watchlist_picks"] = new_watchlist
                if user:
                    _persist_watchlist(user, new_watchlist)
                log_event(
                    "watchlist_remove",
                    movie_id=m.get("id"),
                    title=m.get("title"),
                    user=user,
                )
                st.toast(f"Removed: {m.get('title')}")
                st.rerun()

# What to watch next — only when there's something saved.
next_picks = _build_next_picks(watchlist, profile, space, ratings) if watchlist else []
if watchlist and next_picks:
    panel_header("What to watch next", "From your watchlist + your taste.")
    recs = [
        RecItem(
            movie=m,
            score=float(0),
            role="saved-pick",
            reason="From your watchlist, ranked by taste match.",
        )
        for m in next_picks
    ]
    render_explained_tickets(recs, interactive=False, mode="watchlist")
elif watchlist:
    # Watchlist present but the ranker returned nothing (cold start edge case).
    panel_header("What to watch next", "Add a few loves on Home to seed the ranker.")
    seed_chips([{"title": m.get("title", "Untitled"), "release_date": ""} for m in watchlist[:5]])
