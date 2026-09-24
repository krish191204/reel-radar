"""Reel Radar — Home.

Editorial-cinema rebuild. One tight 2-column composition:
  Left: brand, one real sentence about the user, mode tiles, history
  Right: "What we know about you" panel (real data, not counts)
No more ribbon, no more custom portal grid, no more first-run banner.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.streamlit_shell import (  # noqa: E402
    init_page,
    load_sample_data,
    load_workspace,
    recent_watched_history,
)
from src.ui import (  # noqa: E402
    empty_state,
    first_run_count,
    top_nav,
    vertical_bars_html,
)
from src.features import format_taste_summary  # noqa: E402


def _home_sentence(profile, likes, dislikes, ratings) -> str:
    """
    Generate a single editorial sentence about the user's taste.
    Falls back to a calm onboarding sentence when taste is empty.
    """
    if not first_run_count(likes, dislikes, ratings):
        bullets = format_taste_summary(profile) if profile else []
        if bullets:
            # Render the bullets as a single editorial sentence, not a list.
            return " · ".join(bullets)
    return (
        "Reel Radar reads your Letterboxd history and finds the next film "
        "that's distinctly you, not just generally good."
    )


def _top_genres_rows(profile, limit: int = 3) -> list[tuple[str, float]]:
    if not profile or not getattr(profile, "genre_affinity", None):
        return []
    from src.features import GENRE_NAMES
    items = sorted(profile.genre_affinity.items(), key=lambda t: t[1], reverse=True)[:limit]
    rows = []
    for gid, share in items:
        name = GENRE_NAMES.get(gid, str(gid))
        rows.append((name, float(share)))
    return rows


def _right_rail(profile, likes, dislikes, ratings, catalog_count: int) -> None:
    """Right column: 'What we know about you' panel. Real data, not counts."""
    st.markdown('<div class="rr-rail">', unsafe_allow_html=True)
    st.markdown('<div class="rr-rail-label">What we know about you</div>', unsafe_allow_html=True)

    if first_run_count(likes, dislikes, ratings):
        # Empty state for new users
        st.markdown(
            '<p class="rr-rail-caption">Import your Letterboxd or try the sample data — '
            'then this panel fills in.</p>',
            unsafe_allow_html=True,
        )
    else:
        # Vermilion number: total ratings
        st.markdown(
            f'<p class="rr-rail-figure">{len(ratings)}</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<p class="rr-rail-caption">'
            f'ratings across {len(likes)} loves and {len(dislikes)} avoids.</p>',
            unsafe_allow_html=True,
        )

        # Top genres as editorial bars
        rows = _top_genres_rows(profile, limit=3)
        if rows:
            # Normalize to a 0-1 share (genre_affinity is already normalized but
            # bar widths are relative to the top entry so the largest is full-width).
            total = sum(v for _, v in rows) or 1.0
            display_rows = [(name, v / total) for name, v in rows]
            st.markdown(
                vertical_bars_html(display_rows, label="Top genres"),
                unsafe_allow_html=True,
            )

        # Quiet caption at the bottom
        st.markdown(
            f'<p class="rr-rail-caption">Drawn from {len(ratings)} ratings.</p>',
            unsafe_allow_html=True,
        )

    st.markdown('</div>', unsafe_allow_html=True)


def _mode_tiles() -> None:
    """Eight mode tiles in a 4×2 grid (responsive).

    Uses ``st.page_link`` so the session is preserved across navigation.
    The CSS in ``assets/theme.css`` targets the page-link widget classes
    to give each tile its editorial styling (paper surface, vermilion
    top border on hover/active, etc.).
    """
    from src.ui import MODE_BLURBS, NAV_ITEMS
    items = [(k, p, l) for (k, p, l) in NAV_ITEMS if k != "home"]
    for row_start in (0, 4):
        row = items[row_start:row_start + 4]
        cols = st.columns(4, gap="small")
        for i, (key, page, label) in enumerate(row):
            blurb = MODE_BLURBS.get(key, "")
            num = row_start + i + 1
            with cols[i]:
                st.markdown(
                    f'<div class="rr-tile-num">{num:02d}</div>'
                    f'<div class="rr-tile-blurb">{html_escape(blurb)}</div>',
                    unsafe_allow_html=True,
                )
                st.page_link(
                    page,
                    label=label,
                    icon=None,  # st.page_link rejects raw SVG paths
                    use_container_width=True,
                )


def html_escape(s: str) -> str:
    import html as _html
    return _html.escape(str(s))


# ── Page ───────────────────────────────────────────────────────────

init_page("Home")
catalog, space, profile, ratings, likes, dislikes, rated = load_workspace()

# Editorial top nav (replaces Streamlit's auto sidebar nav)
top_nav("home")

# Home composition: 2 columns
left_col, right_col = st.columns([2, 1], gap="large", vertical_alignment="top")

with left_col:
    st.markdown('<div class="rr-home">', unsafe_allow_html=True)

    # Hero: kicker, brand, one real sentence, single CTA
    st.markdown(
        '<div class="rr-home-hero">'
        '<div class="rr-home-kicker">A movie recommender that reads you</div>'
        '<h1 class="rr-home-brand">Reel Radar</h1>'
        f'<p class="rr-home-sentence">{html_escape(_home_sentence(profile, likes, dislikes, ratings))}</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Single primary CTA — collapsed first-run
    if first_run_count(likes, dislikes, ratings):
        st.markdown(
            '<a class="rr-home-cta" id="rr_home_cta" href="javascript:void(0)">'
            'Load sample data →</a>'
            '<span class="rr-home-cta-sub">'
            'Or import your own Letterboxd ratings.csv in the sidebar.'
            '</span>',
            unsafe_allow_html=True,
        )
        if st.button(
            "Load sample data",
            key="home_load_sample",
            type="primary",
            help="One-click load of the curated 267-film sample profile.",
        ):
            load_sample_data()
            st.rerun()
    else:
        # Taste is loaded — primary CTA is a "What's on tonight?" link.
        # Use st.page_link (not a raw <a href>) so navigation is in-app and
        # the websocket session survives — otherwise the sidebar collapses
        # briefly on every Home → Tonight hop. The wrapper div carries
        # the CTA styling via theme.css (see .rr-home-cta-wrap).
        st.markdown(
            '<div class="rr-home-cta-wrap">',
            unsafe_allow_html=True,
        )
        st.page_link(
            "pages/01_Tonight_Decoder.py",
            label="What's on tonight? →",
            icon=None,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    # Mode tiles (4×2 grid)
    _mode_tiles()

    # Optional history strip (last 5 watched for this user)
    history = recent_watched_history(limit=5)
    if history:
        st.markdown(
            '<div class="rr-section-label">Recently watched</div>',
            unsafe_allow_html=True,
        )
        from src.ui import seed_chips
        history_movies = [{"title": h.get("title", ""), "release_date": ""} for h in history]
        seed_chips(history_movies)

    st.markdown('</div>', unsafe_allow_html=True)

with right_col:
    _right_rail(profile, likes, dislikes, ratings, len(catalog))

# Quiet footer caption (kept small + monospace, matches the editorial tone)
st.caption(
    f"`{space.backend}` · {len(ratings)} rated · {len(catalog)} films in the room"
)
