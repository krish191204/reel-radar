"""Behind the Scenes — private taste / model introspection."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.features import GENRE_NAMES, format_taste_summary, year_of
from src.quality import bayesian_rating, is_recommendable
from src.streamlit_shell import init_page, load_workspace
from src.ui import GLOSSARY, empty_state, panel_header, seed_chips, top_nav, vertical_bars_html

init_page("Behind the Scenes", icon=":mag:")
top_nav("bts")
catalog, space, profile, ratings, likes, dislikes, rated = load_workspace()
panel_header(
    "Behind the Scenes",
    "Your Letterboxd ratings → taste geometry → what the model thinks you love and avoid.",
)

# ── Taste Fingerprint ──────────────────────────────────────────────────────
# Shown when the profile is substantial enough to talk about. Below 3 liked
# films the model is still spinning up, so we hand the user back to the
# taste booth instead of showing noisy bars.
if (
    profile is not None
    and profile.vector is not None
    and len(profile.liked_movies) >= 3
):
    panel_header("Your taste fingerprint", "What the model sees in your ratings.")

    # Top genres — custom HTML bars (no st.bar_chart)
    if profile.genre_affinity:
        genre_rows = sorted(
            [
                (GENRE_NAMES.get(gid, str(gid)), share)
                for gid, share in profile.genre_affinity.items()
            ],
            key=lambda t: t[1],
            reverse=True,
        )[:8]
        # Normalize so the largest entry is full-width
        max_share = max((v for _, v in genre_rows), default=0.0) or 1.0
        normalized = [(name, v / max_share) for name, v in genre_rows]
        st.markdown(
            vertical_bars_html(normalized, label="Top genres"),
            unsafe_allow_html=True,
        )

    # Decades — same treatment
    if profile.decade_affinity:
        dec_rows = sorted(profile.decade_affinity.items(), key=lambda t: t[0])
        max_dec = max((v for _, v in dec_rows), default=0.0) or 1.0
        normalized = [(f"{d}s", v / max_dec) for d, v in dec_rows]
        st.markdown(
            vertical_bars_html(normalized, label="Decades you watch"),
            unsafe_allow_html=True,
        )

    bullets = format_taste_summary(profile)
    if bullets:
        st.markdown(
            '<div class="rr-section-label">At a glance</div>', unsafe_allow_html=True
        )
        for b in bullets:
            st.markdown(f"- {b}")

    with st.expander("How we score picks", expanded=False):
        st.caption(
            "The same vocabulary appears in every ticket's "
            "Why-this-pick breakdown."
        )
        for label, desc in GLOSSARY.items():
            st.markdown(f"**{label}** — {desc}")
else:
    empty_state(
        "Your taste is still forming",
        "Add a few more films and we'll show you the shape of it.",
        cta_label="Add to booth",
        cta_page="Home",
    )

# ── Existing rating-distribution / model-guts panel ───────────────────────
if not ratings and not likes:
    st.info("Import ratings on any page's taste booth, then return here.")
    st.stop()

st.markdown("#### Rating distribution")
rating_vals = list(ratings.values()) if ratings else []
if rating_vals:
    hist = (
        pd.Series(rating_vals)
        .value_counts()
        .reindex([0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0], fill_value=0)
        .sort_index()
    )
    st.bar_chart(hist)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rated films", len(rating_vals))
    c2.metric("Average stars", f"{sum(rating_vals)/len(rating_vals):.2f}")
    c3.metric("Loves (≥3.5)", sum(1 for r in rating_vals if r >= 3.5))
    c4.metric("Avoids (≤2.0)", sum(1 for r in rating_vals if r <= 2.0))

st.markdown("#### How your stars move the model")
st.caption(
    "Ratings are centered at 3★. Higher stars pull the taste centroid toward that film; "
    "lower stars build an anti-centroid the ranker pushes away from."
)
rows = []
by_id = {int(m["id"]): m for m in rated}
for mid, r in sorted(ratings.items(), key=lambda kv: (-kv[1], kv[0])):
    m = by_id.get(mid)
    if not m:
        continue
    signed = r - 3.0
    rows.append(
        {
            "title": m.get("title"),
            "year": year_of(m),
            "stars": r,
            "signed_pull": round(signed, 2),
            "role": "love" if signed >= 0.5 else ("avoid" if signed <= -1 else "mild"),
            "weight": round(max(0.15, abs(signed) ** 1.4), 3),
        }
    )
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

if profile:
    st.markdown("#### Genre affinity (rating-weighted)")
    genre_rows = [
        {"genre": GENRE_NAMES.get(gid, str(gid)), "affinity": aff}
        for gid, aff in profile.genre_affinity.items()
    ]
    # Skip sort when there's only one row — sort_values on a 1-row
    # DataFrame is a no-op but st.bar_chart's internal handling can
    # still raise KeyError, so we short-circuit.
    if len(genre_rows) > 1:
        genre_df = (
            pd.DataFrame(genre_rows)
            .sort_values("affinity", ascending=False)
            .head(12)
        )
    else:
        genre_df = pd.DataFrame(genre_rows)
    if not genre_df.empty:
        st.bar_chart(genre_df.set_index("genre"))

    st.markdown("#### Decade affinity")
    decade_rows = [
        {"decade": f"{dec}s", "affinity": aff}
        for dec, aff in profile.decade_affinity.items()
    ]
    if len(decade_rows) > 1:
        decade_df = (
            pd.DataFrame(decade_rows)
            .sort_values("decade")
        )
    else:
        decade_df = pd.DataFrame(decade_rows)
    if not decade_df.empty:
        st.bar_chart(decade_df.set_index("decade"))

st.markdown("#### Closest films to your taste centroid")
if profile and profile.vector is not None and space.matrix is not None:
    sims = space.cosine_to_taste(profile)
    # Block ALL rated films — if you rated it, you've seen it.
    blocked = set(profile.ratings.keys())
    ranked = sorted(
        (
            (float(sims[i]), space.movies[i])
            for i in range(len(space.movies))
            if space.movies[i]["id"] not in blocked and is_recommendable(space.movies[i])
        ),
        key=lambda t: t[0],
        reverse=True,
    )[:12]
    near_rows = [
        {
            "rank": i + 1,
            "title": m.get("title"),
            "year": year_of(m),
            "score": round(score, 3),
            "bayes": round(bayesian_rating(m), 2),
            "votes": m.get("vote_count"),
        }
        for i, (score, m) in enumerate(ranked)
    ]
    st.dataframe(pd.DataFrame(near_rows), use_container_width=True, hide_index=True)

    if profile.dislike_vector is not None:
        st.markdown("#### Closest films to your avoid centroid")
        avoid_sims = space.matrix @ profile.dislike_vector
        # Note: don't block rated films here — the "closest to your avoid centroid" is
        # intentionally a peek at what the model thinks you hate, even if you've rated it.
        avoid_ranked = sorted(
            (
                (float(avoid_sims[i]), space.movies[i])
                for i in range(len(space.movies))
                if is_recommendable(space.movies[i])
            ),
            key=lambda t: t[0],
            reverse=True,
        )[:10]
        st.dataframe(
            pd.DataFrame(
                [
                    {"title": m.get("title"), "year": year_of(m), "avoid_sim": round(s, 3)}
                    for s, m in avoid_ranked
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

st.markdown("#### System guts")
g1, g2, g3 = st.columns(3)
g1.metric("Catalog size", len(catalog))
g2.metric("Feature backend", space.backend)
g3.metric(
    "Matrix shape",
    "×".join(str(x) for x in space.matrix.shape) if space.matrix is not None else "—",
)
if profile:
    st.caption(
        f"Taste vector: {profile.vector is not None} · "
        f"Dislike vector: {profile.dislike_vector is not None}"
    )
    if profile.liked_movies:
        st.markdown("**Loves in the model**")
        seed_chips(profile.liked_movies[:16])
    if profile.disliked_movies:
        st.markdown("**Avoids in the model**")
        seed_chips(profile.disliked_movies[:16])
