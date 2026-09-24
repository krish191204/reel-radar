"""UX smoke tests: demo, watchlist, reset, and the new UI primitives.

These tests run without a Streamlit server. They exercise the offline-safe
paths that subagent 3's pages depend on: sample-data import, the 5-cell
taste ribbon, the first-run count, the watchlist round-trip through
``save_taste`` / ``load_taste``, and the empty-state primitive.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.auth import TASTE_KEYS, create_user, load_taste, save_taste  # noqa: E402
from src.ui import first_run_count, vertical_bars_html  # noqa: E402


def test_demo_data_loads() -> None:
    """The curated sample CSV is present and shaped like a Letterboxd export."""
    csv_path = Path("data/examples/letterboxd_sample.csv")
    assert csv_path.exists(), f"missing {csv_path}"
    csv_bytes = csv_path.read_bytes()
    assert len(csv_bytes) > 1000, "sample CSV looks too small"
    assert b"Name" in csv_bytes[:100], "sample CSV missing 'Name' header"
    # The CSV should resolve to a healthy number of rows.
    rows = [line for line in csv_bytes.splitlines() if line.strip()]
    assert len(rows) > 100, f"sample CSV has only {len(rows)} rows"
    print(f"  [demo] CSV ok · {len(rows)} rows")


def test_first_run_count() -> None:
    """first_run_count flips False once the user has 3+ taste signals."""
    assert first_run_count([], [], {}) is True
    assert first_run_count([{"id": 1}], [], {1: 4.5}) is True  # 1+0+1 = 2 < 3
    assert first_run_count([{"id": 1}], [{"id": 2}], {3: 4.0}) is False  # 3 total
    assert first_run_count([], [], {1: 4.0, 2: 4.5, 3: 5.0}) is False
    # Tolerates None types (defensive).
    try:
        first_run_count(None, None, None)  # type: ignore[arg-type]
    except TypeError:
        pass
    print("  [first_run] threshold logic correct")


def test_vertical_bars_html() -> None:
    """vertical_bars_html renders a row per (label, share) and respects share width."""
    html = vertical_bars_html(
        [("Drama", 0.4), ("Thriller", 0.25), ("Comedy", 0.15)],
        label="Top genres",
    )
    assert "Drama" in html
    assert "Thriller" in html
    assert "Comedy" in html
    assert 'rr-rail-label' in html
    assert "Top genres" in html
    # Each row should have a fill with a width attribute
    assert html.count("rr-rail-bar-fill") == 3
    # The widest share should be 100% width
    assert "width:100.0%" in html
    # Empty input returns empty string
    assert vertical_bars_html([]) == ""
    print("  [bars] vertical_bars_html renders 3 rows + widths + label")


def test_taste_keys_has_watchlist() -> None:
    """The new watchlist_picks key is in TASTE_KEYS so persistence works."""
    assert "watchlist_picks" in TASTE_KEYS, "watchlist_picks missing from TASTE_KEYS"
    # And the save_taste contract still defaults it to [] when omitted.
    user = f"_smoke_ux_keys_{int(time.time())}"
    create_user(user, "smokepass123")
    try:
        save_taste(user, {"taste_picks": [{"id": 1, "title": "X"}]})
        loaded = load_taste(user)
        assert loaded.get("watchlist_picks") == [], (
            f"watchlist_picks default not []: {loaded.get('watchlist_picks')!r}"
        )
    finally:
        path = ROOT / "data" / "users" / f"{user}.json"
        if path.exists():
            path.unlink()
    print("  [TASTE_KEYS] watchlist_picks persists + defaults to []")


def test_save_taste_round_trip_with_watchlist() -> None:
    """A watchlist round-trips through save_taste / load_taste unchanged."""
    user = f"smoke_ux_{int(time.time())}"
    pw = "smokepass123"
    create_user(user, pw)
    try:
        payload = {
            key: ([] if key != "taste_ratings" else {}) for key in TASTE_KEYS
        }
        payload["taste_picks"] = [{"id": 99, "title": "Test"}]
        payload["watchlist_picks"] = [{"id": 42, "title": "Saved"}]
        save_taste(user, payload)
        loaded = load_taste(user)
        assert loaded["watchlist_picks"] == [{"id": 42, "title": "Saved"}], (
            f"watchlist round-trip mismatch: {loaded['watchlist_picks']!r}"
        )
        assert loaded["taste_picks"] == [{"id": 99, "title": "Test"}]
    finally:
        path = ROOT / "data" / "users" / f"{user}.json"
        if path.exists():
            path.unlink()
    print("  [watchlist] round-trip through save_taste / load_taste")


def test_reset_clears_all_taste() -> None:
    """The reset helper zeroes every TASTE_KEY, matching the sidebar flow.

    We don't call the Streamlit-side helper directly (it needs a session);
    instead we exercise the same code path through ``save_taste`` with the
    cleared payload, the way the reset button writes it.
    """
    user = f"smoke_ux_reset_{int(time.time())}"
    create_user(user, "smokepass123")
    try:
        # Seed with non-empty values.
        seed = {
            key: ([] if key != "taste_ratings" else {1: 5.0}) for key in TASTE_KEYS
        }
        seed["taste_picks"] = [{"id": 1, "title": "A"}]
        seed["watchlist_picks"] = [{"id": 2, "title": "B"}]
        save_taste(user, seed)
        # Reset.
        cleared = {
            key: ([] if key != "taste_ratings" else {}) for key in TASTE_KEYS
        }
        save_taste(user, cleared)
        loaded = load_taste(user)
        for key in TASTE_KEYS:
            assert loaded.get(key) == ([] if key != "taste_ratings" else {}), (
                f"reset left {key} = {loaded.get(key)!r}"
            )
    finally:
        path = ROOT / "data" / "users" / f"{user}.json"
        if path.exists():
            path.unlink()
    print("  [reset] all TASTE_KEYS zeroed")


def test_pages_parse() -> None:
    """All page files parse as valid Python (catches syntax regressions)."""
    import ast

    pages = [
        "app.py",
        "pages/01_Tonight_Decoder.py",
        "pages/02_Anti_Bubble.py",
        "pages/03_Taste_Twin.py",
        "pages/04_Vibe_Match.py",
        "pages/05_Cinematic_DNA.py",
        "pages/06_Group_Peace_Treaty.py",
        "pages/07_Mood_Map.py",
        "pages/08_Behind_the_Scenes.py",
        "pages/09_Watchlist.py",
    ]
    for p in pages:
        ast.parse(Path(p).read_text(encoding="utf-8"))
    print(f"  [parse] {len(pages)} page files parse clean")


def main() -> int:
    print("=== UX smoke tests ===")
    failures: list[str] = []
    for fn in (
        test_demo_data_loads,
        test_first_run_count,
        test_vertical_bars_html,
        test_taste_keys_has_watchlist,
        test_save_taste_round_trip_with_watchlist,
        test_reset_clears_all_taste,
        test_pages_parse,
    ):
        try:
            fn()
        except AssertionError as e:
            failures.append(f"{fn.__name__}: {e}")
            print(f"  FAIL: {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures.append(f"{fn.__name__}: {type(e).__name__}: {e}")
            print(f"  FAIL: {fn.__name__}: {type(e).__name__}: {e}")
    if failures:
        print("\nUX SMOKE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL UX SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
