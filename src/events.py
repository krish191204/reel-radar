"""Product-loop event log (impressions, skips, watches)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
EVENTS_PATH = DATA_DIR / "events.jsonl"


def log_event(
    event_type: str,
    *,
    movie_id: int | None = None,
    title: str | None = None,
    mode: str | None = None,
    user: str | None = None,
    meta: dict[str, Any] | None = None,
    path: Path = EVENTS_PATH,
) -> None:
    """Append one JSONL event. Failures are swallowed — logging must never break UX."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": int(time.time()),
            "type": event_type,
            "movie_id": movie_id,
            "title": title,
            "mode": mode,
            "user": user,
            "meta": meta or {},
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_not_interested(path: Path = EVENTS_PATH) -> set[int]:
    ids: set[int] = set()
    if not path.exists():
        return ids
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "not_interested" and row.get("movie_id") is not None:
                ids.add(int(row["movie_id"]))
    except OSError:
        pass
    return ids


def session_not_interested() -> set[int]:
    """Union of persisted skips + current Streamlit session skips."""
    ids = load_not_interested()
    try:
        import streamlit as st

        for mid in st.session_state.get("not_interested_ids", []) or []:
            ids.add(int(mid))
    except Exception:
        pass
    return ids


def mark_not_interested(movie: dict[str, Any], *, mode: str | None = None, user: str | None = None) -> None:
    mid = movie.get("id")
    if mid is None:
        return
    mid = int(mid)
    try:
        import streamlit as st

        bucket = st.session_state.setdefault("not_interested_ids", [])
        if mid not in bucket:
            bucket.append(mid)
        # Also push into dislike booth so taste centroid updates next rebuild
        dislikes = st.session_state.setdefault("dislike_picks", [])
        if mid not in {d.get("id") for d in dislikes}:
            dislikes.append(movie)
        ratings = st.session_state.setdefault("taste_ratings", {})
        ratings.setdefault(mid, 1.0)
    except Exception:
        pass
    log_event(
        "not_interested",
        movie_id=mid,
        title=movie.get("title"),
        mode=mode,
        user=user,
    )
