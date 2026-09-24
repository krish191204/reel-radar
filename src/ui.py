"""UI helpers for Reel Radar's editorial-cinema Streamlit shell.

Rebuild 2026-08-04: editorial cream/ink/vermilion palette, top nav,
custom bars replace st.bar_chart, popover breakdowns.
"""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from .features import year_of
from .ranking import GLOSSARY
from .tmdb import TMDBClient

CSS_PATH = Path(__file__).resolve().parents[1] / "assets" / "theme.css"


# 8 modes + 1 home entry. Order matches SITE_PAGES in streamlit_shell.py.
# `key` is the active-page key (for top_nav), `page` is the Streamlit page path
# (used to derive the URL slug), `label` is the short nav text.
NAV_ITEMS: list[tuple[str, str, str]] = [
    ("home",     "",                                  "Home"),
    ("tonight",  "pages/01_Tonight_Decoder.py",       "Tonight"),
    ("anti",     "pages/02_Anti_Bubble.py",            "Stretch"),
    ("twin",     "pages/03_Taste_Twin.py",              "Twin"),
    ("vibe",     "pages/04_Vibe_Match.py",              "Vibe"),
    ("dna",      "pages/05_Cinematic_DNA.py",           "DNA"),
    ("group",    "pages/06_Group_Peace_Treaty.py",      "Group"),
    ("mood",     "pages/07_Mood_Map.py",                "Mood"),
    ("watch",    "pages/09_Watchlist.py",               "Watchlist"),
    ("bts",      "pages/08_Behind_the_Scenes.py",        "Guts"),
]


def _slug_for(page_path: str) -> str:
    """Derive the Streamlit URL slug from a pages/*.py path.
    e.g. 'pages/01_Tonight_Decoder.py' -> 'Tonight_Decoder'.
    """
    import re
    if not page_path:
        return ""
    name = page_path.replace("pages/", "").replace(".py", "")
    return re.sub(r"^\d+_", "", name)


# Lucide-style inline SVG icons keyed by mode name.
ICONS: dict[str, str] = {
    "Tonight":      '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    "Stretch":      '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/>',
    "Twin":         '<circle cx="9" cy="12" r="5"/><circle cx="15" cy="12" r="5"/>',
    "Vibe":         '<path d="M3 12c2.5-3 4.5-3 7 0s4.5 3 7 0 4.5-3 7 0"/>',
    "DNA":          '<path d="M4 4c4 4 4 12 0 16M20 4c-4 4-4 12 0 16"/>',
    "Group":        '<circle cx="8" cy="8" r="3"/><circle cx="16" cy="8" r="3"/><path d="M3 19c.6-3 2.6-5 4-5s3.4 2 4 5"/>',
    "Mood":         '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M6 8v4M18 8v4"/>',
    "Watchlist":    '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    "Guts":         '<path d="M3 7h18v12H3z"/><path d="M10 9l5 3-5 3z" fill="currentColor"/>',
}


# Full mode names for the `format_taste_summary` empty-state copy and the
# per-page panel subtitles. Mirrors SITE_PAGES in streamlit_shell.py.
MODE_LABELS: dict[str, str] = {
    "home":     "Home",
    "tonight":  "Tonight Decoder",
    "anti":     "Anti-Bubble",
    "twin":     "Taste Twin",
    "vibe":     "Vibe Match",
    "dna":      "Cinematic DNA",
    "group":    "Group Peace Treaty",
    "mood":     "Mood Map",
    "watch":    "Watchlist",
    "bts":      "Behind the Scenes",
}


# Short blurbs for the mode tiles on Home.
MODE_BLURBS: dict[str, str] = {
    "tonight":  "Time, energy, mood → three picks.",
    "anti":     "Comfort, stretch, and a risk.",
    "twin":     "Your taste mapped to another decade.",
    "vibe":     "Describe a feeling, get matches.",
    "dna":      "Shared directors, DPs, composers.",
    "group":    "Consensus across the couch.",
    "mood":     "Clustered territories. Find yours.",
    "watch":    "Saved films, ranked for tonight.",
    "bts":      "Taste geometry. How picks are made.",
}


def _html(fragment: str) -> None:
    compact = " ".join(fragment.split())
    st.markdown(compact, unsafe_allow_html=True)


# ── Theme + nav ────────────────────────────────────────────────────

def inject_theme() -> None:
    """Inject the theme stylesheet, the skip link, and the main landmark."""
    css = CSS_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    _html(
        '<a class="rr-skip-link" href="#main-content">Skip to content</a>'
        '<main id="main-content" class="rr-main" tabindex="-1">'
    )


def top_nav(active_key: str) -> None:
    """
    Render the editorial top nav. Brand mark on the left, modes on the right.
    Active page gets a vermilion underline.

    Uses ``st.page_link`` so navigation is in-app (no full page reload). Raw
    ``<a href>`` would trigger a reload and wipe the websocket-scoped
    ``st.session_state.user``, forcing a re-login on every click.

    Icons are emitted as a small glyph above each label via ``st.markdown`` —
    ``st.page_link``'s ``icon`` parameter only accepts emoji / material names,
    and our brand icons are raw SVG paths.
    """
    # Brand mark on the left. A marker scopes the adjacent page-link for CSS;
    # the link itself stays in-app so clicking the wordmark preserves session state.
    left, *_ = st.columns([1, 6], gap="small")
    with left:
        st.markdown('<span class="rr-topnav-brand-marker"></span>', unsafe_allow_html=True)
        st.page_link(
            "app.py",
            label="Reel Radar",
            icon=None,
            use_container_width=False,
        )

    # Mode items on the right
    mode_items = [(k, p, l) for (k, p, l) in NAV_ITEMS if k != "home"]
    cols = st.columns(len(mode_items), gap="small")
    for (key, page, label), col in zip(mode_items, cols):
        is_active = " active" if key == active_key else ""
        icon_path = ICONS.get(label, "")
        icon_html = (
            f'<svg class="rr-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{icon_path}</svg>'
            if icon_path else ""
        )
        with col:
            # Icon above the page_link. The page_link label is the nav text.
            st.markdown(
                f'<div class="rr-topnav-icon">{icon_html}</div>',
                unsafe_allow_html=True,
            )
            st.page_link(
                page,
                label=label,
                icon=None,  # st.page_link rejects SVG paths
                use_container_width=False,
            )


# ── Empty state ───────────────────────────────────────────────────

def empty_state(
    title: str,
    body: str,
    *,
    cta_label: str | None = None,
    cta_page: str | None = None,
    cta_tone: str = "vermilion",
) -> None:
    """Empty-state card with optional CTA. Tone maps to one of three accent colors."""
    cta_html = ""
    if cta_label and cta_page:
        href = "/" + cta_page.replace(" ", "_")
        tone = html.escape(cta_tone if cta_tone in ("vermilion", "copper", "cool") else "vermilion")
        cta_html = (
            f'<a class="rr-empty-cta {tone}" href="{html.escape(href)}">'
            f'{html.escape(cta_label)} →</a>'
        )
    _html(
        f"""
        <div class="rr-empty">
          <strong>{html.escape(title)}</strong>
          <div class="rr-empty-body">{html.escape(body)}</div>
          {cta_html}
        </div>
        """
    )


# ── Page panel header ─────────────────────────────────────────────

def panel_header(title: str, subtitle: str) -> None:
    _html(
        f"""
        <div class="rr-panel">
          <div class="rr-panel-title" role="heading" aria-level="2">{html.escape(title)}</div>
          <p class="rr-panel-sub">{html.escape(subtitle)}</p>
        </div>
        """
    )


# ── Custom bar helpers (replace st.bar_chart) ─────────────────────

def vertical_bars_html(rows: list[tuple[str, float]], label: str = "") -> str:
    """
    Render a list of (label, 0-1 share) as a vertical bar list in editorial
    style. Used by the Behind the Scenes fingerprint and the Home right rail.
    """
    if not rows:
        return ""
    max_v = max((v for _, v in rows), default=0.0) or 1.0
    head = f'<div class="rr-rail-label">{html.escape(label)}</div>' if label else ""
    bars: list[str] = []
    for name, v in rows:
        pct = max(0.0, min(1.0, v / max_v))
        width_pct = pct * 100
        bars.append(
            f'<div class="rr-rail-bar-row">'
            f'<div class="rr-rail-bar-label">{html.escape(str(name))}</div>'
            f'<div class="rr-rail-bar-track"><div class="rr-rail-bar-fill" '
            f'style="width:{width_pct:.1f}%"></div></div>'
            f'<div class="rr-rail-bar-pct">{int(round(v * 100))}%</div>'
            f'</div>'
        )
    return head + f'<div class="rr-rail-bars">{"".join(bars)}</div>'


# ── Per-ticket breakdown (popover body) ──────────────────────────

def _breakdown_html(rec) -> str:
    """Render a RecItem's explanation as horizontal bars in the popover body."""
    if getattr(rec, "explanation", None) is None:
        return '<div class="rr-popover-breakdown"><em>No breakdown available.</em></div>'
    rows = rec.explanation.as_rows()
    if not rows:
        return '<div class="rr-popover-breakdown"><em>No breakdown available.</em></div>'
    max_abs = max((abs(v) for _, v in rows), default=0.0) or 1.0
    out: list[str] = ['<div class="rr-popover-breakdown">']
    for label, val in rows:
        # Lookup the user-facing description via GLOSSARY
        desc = GLOSSARY.get(label, label.replace("_", " "))
        # Clamp the bar width to a percentage of half the track
        half_pct = min(50.0, abs(val) / max_abs * 50.0)
        if val >= 0:
            bar = f'<div class="rr-popover-bar-fill pos" style="width:{half_pct:.1f}%"></div>'
        else:
            bar = f'<div class="rr-popover-bar-fill neg" style="width:{half_pct:.1f}%"></div>'
        sign = "+" if val >= 0 else ""
        out.append(
            f'<div class="rr-popover-row">'
            f'<div class="rr-popover-label">{html.escape(desc)}</div>'
            f'<div class="rr-popover-bar-track">{bar}</div>'
            f'<div class="rr-popover-value">{sign}{val:.2f}</div>'
            f'</div>'
        )
    out.append('</div>')
    return "".join(out)


# ── Ticket card ──────────────────────────────────────────────────

def ticket_card(rec) -> str:
    """Minimal ticket card: poster, title+year, optional hairline meta. No role pill, no reason text."""
    m = rec.movie
    title = html.escape(m.get("title") or "Untitled")
    y = year_of(m)
    year_bit = f" <span class='rr-ticket-meta'>· {y}</span>" if y else ""
    meta_bits: list[str] = []
    if m.get("vote_average"):
        meta_bits.append(f"{float(m['vote_average']):.1f}")
    if m.get("runtime"):
        meta_bits.append(f"{int(m['runtime'])}m")
    meta_html = (
        f"<div class='rr-ticket-meta'>{' · '.join(html.escape(b) for b in meta_bits)}</div>"
        if meta_bits else ""
    )

    poster = TMDBClient.poster_url(m.get("poster_path"), size="w185")
    if poster:
        poster_html = (
            f'<img class="rr-ticket-poster" src="{html.escape(poster)}" '
            f'alt="Poster for {title}" loading="lazy" />'
        )
    else:
        poster_html = '<div class="rr-ticket-poster missing" aria-hidden="true">no art</div>'

    return (
        f'<article class="rr-ticket">'
        f'{poster_html}'
        f'<div class="rr-ticket-body">'
        f'<h3 class="rr-ticket-title">{title}{year_bit}</h3>'
        f'{meta_html}'
        f'</div>'
        f'</article>'
    )


# ── Chips (used in watchlist, search_and_pick) ───────────────────

def seed_chips(movies: list[dict]) -> None:
    if not movies:
        return
    chips = []
    for m in movies:
        y = year_of(m)
        label = m.get("title") or "Film"
        if y:
            label = f"{label} · {y}"
        chips.append(f'<span class="rr-chip accent">{html.escape(label)}</span>')
    _html(f'<div class="rr-chip-row">{"".join(chips)}</div>')


# ── User badge (sidebar) ─────────────────────────────────────────

def user_badge_html(username: str) -> str:
    return (
        f'<div class="rr-user-badge">'
        f'<span class="rr-user-dot" aria-hidden="true"></span>'
        f'<span class="rr-user-name">{html.escape(username)}</span>'
        f'</div>'
    )


# ── First-run detection ──────────────────────────────────────────

def first_run_count(likes, dislikes, ratings) -> bool:
    """True if the user has fewer than 3 taste signals — first-run territory."""
    try:
        n = len(likes or []) + len(dislikes or []) + len(ratings or {})
    except TypeError:
        return True
    return n < 3


# ── Public dispatcher for interactive ticket grids ───────────────

def render_explained_tickets(
    recs,
    *,
    interactive: bool = True,
    mode: str = "recs",
) -> None:
    """
    Render a grid of minimal ticket cards. Each card is followed by a
    `st.popover` ("Why this pick?") with the breakdown bars, plus three
    small buttons (Skip / Save / Watched).
    """
    from .events import log_event, mark_not_interested

    if not recs:
        empty_state(
            "No picks yet",
            "Run a mode above. If results stay empty, rebuild the catalog or add different seeds.",
        )
        return

    # 1. The grid of cards (pure HTML; no Streamlit widgets here)
    cards = "".join(ticket_card(r) for r in recs)
    _html(f'<div class="rr-ticket-grid">{cards}</div>')

    if not interactive:
        return

    user = st.session_state.get("user")

    # 2. Per-rec popover (breakdown) + button row
    for rec in recs:
        mid = rec.movie.get("id")
        if mid is None:
            continue

        # Log impression (one per render)
        log_event(
            "impression",
            movie_id=int(mid),
            title=rec.movie.get("title"),
            mode=mode,
            user=user,
            meta={"score": rec.score, "role": rec.role},
        )

        # Popover for the breakdown
        try:
            with st.popover("Why this pick?"):
                _html(_breakdown_html(rec))
        except TypeError:
            # Streamlit < 1.39 fallback (no-op)
            pass

        # Three small buttons in a row
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Skip", key=f"ni_{mode}_{mid}", help="Won't recommend again"):
                mark_not_interested(rec.movie, mode=mode, user=user)
                st.toast("Skipped.", icon="✕")
                st.rerun()
        with c2:
            if st.button("Save", key=f"save_{mode}_{mid}", help="Save for later"):
                watchlist = list(st.session_state.get("watchlist_picks", []))
                if not any(m.get("id") == mid for m in watchlist):
                    watchlist.append(rec.movie)
                    st.session_state["watchlist_picks"] = watchlist
                    log_event(
                        "watchlist_add",
                        movie_id=int(mid),
                        title=rec.movie.get("title"),
                        mode=mode,
                        user=user,
                    )
                    try:
                        from .streamlit_shell import _persist_session_taste
                        _persist_session_taste()
                    except Exception:
                        pass
                    st.toast("Saved.", icon="＋")
                    st.rerun()
                else:
                    st.toast("Already saved.", icon="＋")
        with c3:
            if st.button("Watched", key=f"w_{mode}_{mid}", help="Log a watch"):
                log_event(
                    "watched",
                    movie_id=int(mid),
                    title=rec.movie.get("title"),
                    mode=mode,
                    user=user,
                )
                st.toast("Watched.", icon="▶")
