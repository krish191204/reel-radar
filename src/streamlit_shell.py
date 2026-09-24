"""Shared Streamlit shell for the Reel Radar multipage site."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app_state import (  # noqa: E402
    build_session_profile,
    ensure_space,
    get_client,
    load_catalog,
    taste_lists_from_session,
)
from src.auth import (  # noqa: E402
    TASTE_KEYS,
    AuthError,
    authenticate,
    create_user,
    load_taste as load_user_taste,
    save_taste as save_user_taste,
)
from src.catalog import enrich  # noqa: E402
from src.features import year_of  # noqa: E402
from src.taste_io import import_taste_csv  # noqa: E402
from src.tmdb import TMDBClient, TMDBError  # noqa: E402
from src.ui import empty_state, inject_theme, seed_chips, top_nav, user_badge_html  # noqa: E402

SITE_PAGES = [
    ("Home", "Taste booth — import Letterboxd, seed loves & avoids."),
    ("Tonight Decoder", "Time, energy, hard nos → three picks."),
    ("Anti-Bubble", "Comfort, stretch, and a delicious risk."),
    ("Taste Twin", "Map your taste onto another decade."),
    ("Vibe Match", "Describe a feeling; get matching films."),
    ("Cinematic DNA", "Follow directors, DPs, composers, cast."),
    ("Group Peace Treaty", "Minimize regret across the couch."),
    ("Mood Map", "Spoiler-free mood territories."),
    ("Watchlist", "Films saved for later, with a 'what to watch next' ranker."),
    ("Behind the Scenes", "Your ratings → model guts."),
]


# ─── Auth helpers ───────────────────────────────────────────────────────────


def current_user() -> str | None:
    return st.session_state.get("user")


def _persist_session_taste() -> None:
    """Write every TASTE_KEY from session_state to the user's record."""
    user = current_user()
    if not user:
        return
    payload = {key: st.session_state.get(key, [] if key != "taste_ratings" else {}) for key in TASTE_KEYS}
    try:
        save_user_taste(user, payload)
    except AuthError as e:
        st.warning(f"Could not save taste: {e}")


def _hydrate_session_from_user(user: str) -> None:
    """Pull the persisted taste dict back into session_state on login."""
    try:
        taste = load_user_taste(user)
    except AuthError:
        return
    for key in TASTE_KEYS:
        default = [] if key != "taste_ratings" else {}
        st.session_state[key] = taste.get(key, default)
    # Per-page pickers (dna, group_b, group_c) start empty on each login.
    for prefix in ("dna", "group_b", "group_c"):
        st.session_state[f"{prefix}_picks"] = []


def load_sample_data() -> None:
    """Load data/examples/letterboxd_sample.csv and merge into session taste.

    Same code path as the manual CSV upload. Resolves each title through TMDB
    via ``import_taste_csv``. Failures surface a Streamlit error and leave the
    existing taste untouched so the user can try again.
    """
    csv_path = ROOT / "data" / "examples" / "letterboxd_sample.csv"
    if not csv_path.exists():
        st.error(f"Sample CSV missing: {csv_path}")
        return
    try:
        csv_bytes = csv_path.read_bytes()
        imported = import_taste_csv(get_client(), csv_bytes, progress_cb=None)
    except Exception as e:  # noqa: BLE001
        st.error(f"Could not load sample data: {e.__class__.__name__}: {e}")
        return

    st.session_state["taste_picks"] = merge_picks(
        st.session_state.get("taste_picks", []), imported.likes
    )
    st.session_state["dislike_picks"] = merge_picks(
        st.session_state.get("dislike_picks", []), imported.dislikes
    )
    st.session_state["rated_picks"] = merge_picks(
        st.session_state.get("rated_picks", []), imported.rated
    )
    ratings = st.session_state.setdefault("taste_ratings", {})
    ratings.update(imported.ratings)
    st.session_state["import_stats"] = imported.stats
    # Preserve any existing watchlist (sample data has none).
    st.session_state.setdefault("watchlist_picks", [])
    _persist_session_taste()
    st.toast(
        f"Loaded {imported.stats.get('rated', 0)} sample ratings — try Tonight Decoder."
    )


# Back-compat alias for older pages / Hot-reload mid-flight imports.
_try_sample_data = load_sample_data


def render_login_gate() -> None:
    """Show sign-in / sign-up card. Called by every page before content."""
    if current_user():
        return

    # Auth recovery — track failed attempts so we can throttle after 3.
    if "login_attempts" not in st.session_state:
        st.session_state["login_attempts"] = 0
        st.session_state["first_fail_ts"] = 0.0

    st.markdown(
        '<div class="rr-section-label">Sign in to save your taste</div>',
        unsafe_allow_html=True,
    )

    tab_in, tab_up = st.tabs(["Sign in", "Create account"])

    with tab_in:
        with st.form("login_form", clear_on_submit=False):
            u = st.text_input("Username", key="login_username")
            p = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            # If the user has already burned through attempts, refuse until
            # the cool-down window has elapsed.
            if st.session_state["login_attempts"] >= 3:
                wait = max(0, 5 - (time.time() - st.session_state["first_fail_ts"]))
                if wait > 0:
                    st.error(
                        f"Too many failed attempts. Wait {int(wait)}s and try again."
                    )
                    return
                # Window elapsed — reset so the user gets a fresh slate.
                st.session_state["login_attempts"] = 0
            try:
                record = authenticate(u, p)
            except AuthError as e:
                st.session_state["login_attempts"] += 1
                if st.session_state["login_attempts"] == 1:
                    st.session_state["first_fail_ts"] = time.time()
                if st.session_state["login_attempts"] >= 3:
                    wait = max(0, 5 - (time.time() - st.session_state["first_fail_ts"]))
                    if wait > 0:
                        st.error(
                            f"Too many failed attempts. Wait {int(wait)}s and try again."
                        )
                    else:
                        st.error(str(e))
                else:
                    st.error(str(e))
            else:
                st.session_state.user = record["username"]
                st.session_state["login_attempts"] = 0
                _hydrate_session_from_user(record["username"])
                st.success(f"Welcome back, {record['username']}.")
                st.rerun()

    with tab_up:
        with st.form("signup_form", clear_on_submit=False):
            u = st.text_input("Choose a username", key="signup_username")
            p = st.text_input("Choose a password", type="password", key="signup_password")
            p2 = st.text_input("Confirm password", type="password", key="signup_password2")
            submitted = st.form_submit_button("Create account", type="primary")
        if submitted:
            if p != p2:
                st.error("Passwords do not match.")
            else:
                try:
                    record = create_user(u, p)
                except AuthError as e:
                    st.error(str(e))
                else:
                    st.session_state.user = record["username"]
                    _hydrate_session_from_user(record["username"])
                    st.success(f"Account created — welcome, {record['username']}.")
                    st.rerun()

    st.caption(
        "Your taste (loves, avoids, ratings) is stored locally in `data/users/`. "
        "Passwords are hashed with PBKDF2-HMAC-SHA256 (200k iterations)."
    )
    st.stop()


def render_user_badge() -> None:
    """Sidebar chip showing the logged-in user + logout."""
    user = current_user()
    if not user:
        return
    st.markdown(user_badge_html(user), unsafe_allow_html=True)
    if st.button("Sign out", key="global_logout"):
        _persist_session_taste()  # final save
        st.session_state.user = None
        for key in TASTE_KEYS:
            st.session_state.pop(key, None)
        st.rerun()


# ─── Page init / workspace ──────────────────────────────────────────────────


def init_page(title: str, *, icon: str = ":clapper:") -> None:
    st.set_page_config(
        page_title=f"{title} · Reel Radar",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_theme()


def merge_picks(existing: list[dict], incoming: list[dict]) -> list[dict]:
    by_id = {m["id"]: m for m in existing}
    for m in incoming:
        by_id[m["id"]] = m
    return list(by_id.values())


def poster(movie: dict, width: int = 120) -> None:
    url = TMDBClient.poster_url(movie.get("poster_path"))
    if url:
        st.image(url, width=width)
    else:
        st.caption("No poster")


def search_and_pick(label: str, key: str, max_results: int = 6) -> list[dict]:
    q = st.text_input(label, key=f"{key}_q", placeholder="Type a title…")
    picks: list[dict] = st.session_state.setdefault(f"{key}_picks", [])
    client = get_client()
    if q and len(q.strip()) >= 2:
        try:
            results = client.search_movies(q.strip())[:max_results]
        except TMDBError as e:
            st.error(str(e))
            results = []
        for r in results:
            y = year_of(r)
            caption = f"{r.get('title')} ({y})" if y else r.get("title", "")
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{caption}**")
                st.caption(((r.get("overview") or "")[:120] + "…") if r.get("overview") else "")
            with c2:
                if st.button("Add", key=f"{key}_add_{r['id']}"):
                    if r["id"] not in {p["id"] for p in picks}:
                        try:
                            picks.append(enrich(client, r))
                        except TMDBError:
                            picks.append(r)
                        st.session_state[f"{key}_picks"] = picks
                        if key in ("taste", "dislike"):
                            _persist_session_taste()
                        st.rerun()
    if picks:
        st.caption("On your reel")
        seed_chips(picks)
        remove = None
        for p in picks:
            y = year_of(p)
            c1, c2 = st.columns([5, 1])
            with c1:
                st.write(f"{p.get('title')}" + (f" ({y})" if y else ""))
            with c2:
                if st.button("Remove", key=f"{key}_rm_{p['id']}"):
                    remove = p["id"]
        if remove is not None:
            st.session_state[f"{key}_picks"] = [p for p in picks if p["id"] != remove]
            if key in ("taste", "dislike"):
                _persist_session_taste()
            st.rerun()
    return st.session_state.get(f"{key}_picks", [])


@st.cache_data(show_spinner=False, ttl=60 * 30)
def cached_genres():
    try:
        return get_client().genres()
    except TMDBError as e:
        st.warning(str(e))
        return []


def render_taste_sidebar() -> None:
    """Global taste booth — available on every page (after login)."""
    with st.sidebar:
        render_user_badge()
        st.markdown("### Taste booth")
        st.caption("Shared across every page. Import once, recommend everywhere.")

        uploaded = st.file_uploader(
            "Import Letterboxd / ratings CSV",
            type=["csv"],
            key="global_ratings_csv",
            help="Letterboxd export ratings.csv (Name, Year, Rating).",
        )
        if uploaded is not None and st.button("Import CSV", type="primary", key="global_import_csv"):
            try:
                status = st.status(
                    "Resolving titles on TMDB…", expanded=True, state="running"
                )
                progress = st.empty()

                def _progress(processed: int, total: int, last_title: str) -> None:
                    progress.caption(
                        f"{processed}/{total} · {last_title[:40]}"
                    )

                imported = import_taste_csv(
                    get_client(),
                    uploaded.getvalue(),
                    progress_cb=_progress,
                )
                status.update(label="Import complete", state="complete")
            except TMDBError as e:
                st.error(str(e))
            else:
                st.session_state["taste_picks"] = merge_picks(
                    st.session_state.get("taste_picks", []), imported.likes
                )
                st.session_state["dislike_picks"] = merge_picks(
                    st.session_state.get("dislike_picks", []), imported.dislikes
                )
                st.session_state["rated_picks"] = merge_picks(
                    st.session_state.get("rated_picks", []), imported.rated
                )
                ratings = st.session_state.setdefault("taste_ratings", {})
                ratings.update(imported.ratings)
                st.session_state["import_stats"] = imported.stats
                if imported.unresolved:
                    st.warning(
                        f"Unresolved ({len(imported.unresolved)}): "
                        + ", ".join(imported.unresolved[:8])
                    )
                st.success(
                    f"Imported {imported.stats.get('rated', 0)} rated · "
                    f"avg {imported.stats.get('avg_rating', '—')}★"
                )
                _persist_session_taste()
                st.rerun()

        if st.session_state.get("import_stats"):
            s = st.session_state["import_stats"]
            st.caption(
                f"Last import: {s.get('rated', 0)} rated · "
                f"{s.get('likes', 0)} loves / {s.get('dislikes', 0)} avoids"
            )

        if st.button(
            "Try sample data",
            key="global_try_sample",
            help="Load the curated 267-film sample profile.",
        ):
            _try_sample_data()
            st.rerun()

        search_and_pick("Films you love", "taste")
        search_and_pick("Films you hate / skip", "dislike")

        st.divider()
        if st.button("Rebuild catalog", key="global_rebuild_catalog"):
            load_catalog.clear()
            st.rerun()

        # Reset taste — two-click confirm.
        st.divider()
        if not st.session_state.get("reset_confirm"):
            if st.button("Reset taste", key="global_reset_taste"):
                st.session_state["reset_confirm"] = True
                st.rerun()
        else:
            st.warning("This will clear all your taste. Sure?")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Yes, clear", key="global_reset_yes"):
                    for key in ("taste_picks", "dislike_picks", "rated_picks", "watchlist_picks"):
                        st.session_state[key] = []
                    st.session_state["taste_ratings"] = {}
                    st.session_state["import_stats"] = []
                    st.session_state["first_run_dismissed"] = False
                    st.session_state["reset_confirm"] = False
                    _persist_session_taste()
                    st.toast("Taste reset.")
                    st.rerun()
            with c2:
                if st.button("Cancel", key="global_reset_no"):
                    st.session_state["reset_confirm"] = False
                    st.rerun()


def recent_watched_history(limit: int = 5) -> list[dict]:
    """Return the most recent `watched` events for the current user.

    Reads ``data/events.jsonl`` once per session (cached in
    ``st.session_state``) and filters to the logged-in user. The events are
    returned newest-first so the caller can take ``[:limit]``.
    """
    user = current_user()
    if not user:
        return []
    cached = st.session_state.get("_rr_history_cache")
    if cached is not None:
        return cached[:limit]
    events_path = Path("data/events.jsonl")
    rows: list[dict] = []
    if events_path.exists():
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    row.get("type") == "watched"
                    and row.get("user") == user
                    and row.get("title")
                ):
                    rows.append(row)
        except OSError:
            rows = []
    rows.sort(key=lambda r: r.get("ts", 0), reverse=True)
    st.session_state["_rr_history_cache"] = rows
    return rows[:limit]


def load_workspace(extra_seeds: list[dict] | None = None):
    """Return catalog, space, profile, ratings — prefer offline catalog if TMDB is down."""
    render_login_gate()  # every page is gated by login

    try:
        get_client()
    except TMDBError as e:
        from src.ingest import load_persisted_catalog

        if not load_persisted_catalog():
            st.error(str(e))
            st.stop()
        st.warning(str(e))

    render_taste_sidebar()
    likes, dislikes, ratings, rated = taste_lists_from_session()
    seeds = list(extra_seeds or []) + likes + dislikes + rated
    try:
        catalog, space = ensure_space(seeds)
    except TMDBError as e:
        st.error(str(e))
        st.stop()
    profile = build_session_profile(space)
    return catalog, space, profile, ratings, likes, dislikes, rated


def require_taste(profile, *, allow_without: bool = False) -> bool:
    if profile and profile.vector is not None:
        return True
    if allow_without:
        return False
    empty_state(
        "Seed the booth first",
        "Import a Letterboxd ratings.csv or add loved films in the sidebar, then come back.",
    )
    return False