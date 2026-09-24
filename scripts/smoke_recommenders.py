"""Smoke test: every recommendation mode returns a list and never leaks
ProxyError / httpx / requests stack traces.

This script does NOT require Streamlit. It loads the persisted catalog.json
via the same offline path the app uses, builds a taste profile from
data/examples/letterboxd_sample.csv, and exercises each recommendation mode.

Exit codes:
  0 = all modes passed
  1 = any mode failed
"""

from __future__ import annotations

import csv
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE_CSV = ROOT / "data" / "examples" / "letterboxd_sample.csv"
BAD_PROXY = "http://127.0.0.1:1"
PROXY_VARS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)
PROXY_SENTINELS = (
    "ProxyError", "Tunnel", "HTTPSConnectionPool", "HTTPConnectionPool",
    "ProxyConnectError", "ProxyConnectionError", "ConnectError",
    "RemoteDisconnected", "NewConnectionError", "Connection refused",
)


class SmokeFailure(RuntimeError):
    pass


@contextmanager
def proxy_env(value: str | None):
    """Snapshot + replace every proxy env var, then restore on exit."""
    saved = {k: os.environ.get(k) for k in PROXY_VARS}
    try:
        if value is None:
            for k in PROXY_VARS:
                os.environ.pop(k, None)
        else:
            for k in PROXY_VARS:
                os.environ[k] = value
        yield
    finally:
        for k in PROXY_VARS:
            if k in saved and saved[k] is not None:
                os.environ[k] = saved[k]
            else:
                os.environ.pop(k, None)


def _is_proxy_error(exc: BaseException) -> bool:
    msg = f"{type(exc).__name__}: {exc}"
    return any(s in msg for s in PROXY_SENTINELS)


def _safe(name: str, fn):
    """Run fn(), translate any exception into a SmokeFailure that mentions
    proxy leakage if appropriate."""
    try:
        return fn()
    except SmokeFailure:
        raise
    except Exception as e:  # noqa: BLE001
        if _is_proxy_error(e):
            raise SmokeFailure(f"{name}: proxy error leaked: {type(e).__name__}: {e}") from e
        raise SmokeFailure(f"{name}: {type(e).__name__}: {e}") from e


def _build_profile(space, csv_path: Path):
    """Build a non-empty taste profile from CSV rows.

    Resolve each row by (title, year) against the catalog; if none resolve,
    synthesize likes=[catalog[0]], dislikes=[catalog[100]] so we always
    have a profile."""
    from src.features import TasteProfile

    by_title_year: dict[tuple[str, str], dict[str, Any]] = {}
    for m in space.movies:
        title = (m.get("title") or m.get("original_title") or "").strip()
        year = (m.get("release_date") or "")[:4]
        if title:
            by_title_year.setdefault((title.lower(), year), m)

    likes: list[dict[str, Any]] = []
    dislikes: list[dict[str, Any]] = []
    ratings: dict[int, float] = {}

    if csv_path.exists():
        with csv_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                title = (row.get("Name") or row.get("Title") or "").strip()
                year = (row.get("Year") or "").strip()
                rating_str = (row.get("Rating") or "").strip()
                if not title:
                    continue
                m = by_title_year.get((title.lower(), year))
                if not m:
                    continue
                try:
                    r = float(rating_str)
                except (TypeError, ValueError):
                    continue
                mid = int(m["id"])
                ratings[mid] = r
                if r >= 3.5:
                    likes.append(m)
                elif r <= 2.0:
                    dislikes.append(m)

    if not likes and not ratings:
        seed = space.movies[0]
        avoid = space.movies[min(100, len(space.movies) - 1)]
        likes = [seed]
        dislikes = [avoid]
        ratings = {int(seed["id"]): 5.0, int(avoid["id"]): 1.0}
        print(
            f"  [csv] fallback -> like='{seed.get('title')}' "
            f"dislike='{avoid.get('title')}'"
        )

    return space.build_taste(
        likes,
        label="You",
        disliked=dislikes,
        ratings=ratings,
    )


def _stub_seed() -> dict[str, Any]:
    """A seed dict shaped like TMDB /movie/{id}?append_to_response=credits.

    `credits` is pre-populated so the function does not need to call
    client.movie(). Each person_id is resolvable via _stub_person_credits."""
    return {
        "id": 999999,
        "title": "The Test Film",
        "overview": "A breathtaking test that walks credits without TMDB.",
        "genre_ids": [18, 12],
        "popularity": 80.0,
        "vote_average": 8.0,
        "vote_count": 5000,
        "runtime": 120,
        "release_date": "2018-05-01",
        "credits": {
            "crew": [
                {"id": 1, "job": "Director", "name": "Alice"},
                {"id": 2, "job": "Original Music Composer", "name": "Bob"},
                {"id": 5, "job": "Director of Photography", "name": "Eve"},
            ],
            "cast": [
                {"id": 3, "name": "Carol"},
                {"id": 4, "name": "Dave"},
            ],
        },
    }


def _stub_person_credits(catalog_pool: list[dict[str, Any]]):
    """Return a callable that mimics client.person_credits(pid) using
    real catalog entries (so is_recommendable passes)."""
    pool = [m for m in catalog_pool if m.get("id") not in (999999,)][:8]
    if len(pool) < 4:
        # Catalog with too few titles; pad with safe stubs
        while len(pool) < 4:
            pool.append(
                {
                    "id": 800000 + len(pool),
                    "title": f"Stub Film {len(pool)}",
                    "overview": "A" * 60,
                    "genre_ids": [18],
                    "popularity": 5.0,
                    "vote_average": 7.0,
                    "vote_count": 100,
                    "runtime": 100,
                    "release_date": "2015-01-01",
                }
            )

    def fake(pid: int) -> dict[str, Any]:
        # Deterministic spread: alternate cast vs crew per pid.
        if pid % 2 == 0:
            return {"cast": pool[:3], "crew": []}
        return {"cast": [], "crew": pool[1:4]}

    return fake


def _scenario_normal():
    print("\n=== Scenario 1: offline catalog + normal proxy ===")
    failures: list[str] = []
    samples: dict[str, Any] = {}

    with proxy_env(None):
        # Reset embedding state so fit() can take either path cleanly
        from src import embeddings
        embeddings._mark_unavailable("smoke test reset")

        from src.app_state import _offline_catalog
        from src.features import FeatureSpace, TasteProfile
        from src.recommenders import (
            tonight_decoder, anti_bubble, taste_twin, vibe_match,
            group_peace_treaty, mood_map, recommend_in_mood, cinematic_dna,
        )
        from src.tmdb import TMDBClient, TMDBError

        try:
            catalog, space = _offline_catalog()
        except Exception as e:
            print(f"  FAIL: _offline_catalog: {type(e).__name__}: {e}")
            return ["_offline_catalog"], {}
        if not catalog:
            print("  FAIL: empty catalog")
            return ["empty_catalog"], {}
        print(f"  [catalog] {len(catalog)} movies · backend={space.backend}")

        profile = _build_profile(space, SAMPLE_CSV)
        if profile.vector is None:
            print("  FAIL: profile.vector is None")
            return ["profile_vector_none"], {}
        print(
            f"  [profile] liked={len(profile.liked_movies)} "
            f"disliked={len(profile.disliked_movies)}"
        )

        # tonight_decoder
        try:
            picks = tonight_decoder(
                space, profile, catalog,
                max_minutes=180, energy="cozy", hard_no_genres=[27],
            )
            assert isinstance(picks, list)
            samples["tonight_decoder"] = [
                (r.movie.get("title"), round(r.score, 3), r.role) for r in picks
            ]
            print(f"  [tonight_decoder] OK · {len(picks)} picks")
        except SmokeFailure as e:
            failures.append(str(e))
            print(f"  FAIL: tonight_decoder: {e}")
        except Exception as e:  # noqa: BLE001
            failures.append(f"tonight_decoder: {type(e).__name__}: {e}")
            print(f"  FAIL: tonight_decoder: {type(e).__name__}: {e}")

        # anti_bubble
        try:
            picks = anti_bubble(space, profile)
            assert isinstance(picks, list)
            samples["anti_bubble"] = [
                (r.movie.get("title"), round(r.score, 3), r.role) for r in picks
            ]
            print(f"  [anti_bubble] OK · {len(picks)} picks")
        except Exception as e:  # noqa: BLE001
            failures.append(f"anti_bubble: {type(e).__name__}: {e}")
            print(f"  FAIL: anti_bubble: {type(e).__name__}: {e}")

        # taste_twin
        try:
            picks = taste_twin(space, profile, target_decade=1990, top_k=5)
            assert isinstance(picks, list)
            samples["taste_twin"] = [
                (r.movie.get("title"), round(r.score, 3)) for r in picks
            ]
            print(f"  [taste_twin] OK · {len(picks)} picks")
        except Exception as e:  # noqa: BLE001
            failures.append(f"taste_twin: {type(e).__name__}: {e}")
            print(f"  FAIL: taste_twin: {type(e).__name__}: {e}")

        # vibe_match
        try:
            picks = vibe_match(
                space,
                "a quiet rainy night with a slow-burn mystery",
                liked_ids=set(profile.liked_ids) | set(profile.disliked_ids),
                top_k=6,
            )
            assert isinstance(picks, list)
            samples["vibe_match"] = [
                (r.movie.get("title"), round(r.score, 3)) for r in picks
            ]
            print(f"  [vibe_match] OK · {len(picks)} picks")
        except Exception as e:  # noqa: BLE001
            failures.append(f"vibe_match: {type(e).__name__}: {e}")
            print(f"  FAIL: vibe_match: {type(e).__name__}: {e}")

        # group_peace_treaty
        try:
            p2 = _build_profile(space, SAMPLE_CSV)
            p2.label = "Friend"
            picks = group_peace_treaty(space, [profile, p2], top_k=5)
            assert isinstance(picks, list)
            samples["group_peace_treaty"] = [
                (r.movie.get("title"), round(r.score, 3)) for r in picks
            ]
            print(f"  [group_peace_treaty] OK · {len(picks)} picks")
        except Exception as e:  # noqa: BLE001
            failures.append(f"group_peace_treaty: {type(e).__name__}: {e}")
            print(f"  FAIL: group_peace_treaty: {type(e).__name__}: {e}")

        # mood_map
        try:
            mm = mood_map(space, profile=profile, n_clusters=6)
            assert isinstance(mm, dict)
            clusters = mm.get("clusters", [])
            assert isinstance(clusters, list)
            samples["mood_map"] = [
                (c.get("name"), len(c.get("exemplars", []))) for c in clusters
            ]
            print(f"  [mood_map] OK · {len(clusters)} clusters")
        except Exception as e:  # noqa: BLE001
            failures.append(f"mood_map: {type(e).__name__}: {e}")
            print(f"  FAIL: mood_map: {type(e).__name__}: {e}")

        # cinematic_dna with stubbed seed (credits pre-populated)
        try:
            seed = _stub_seed()
            client = TMDBClient(api_key="fake")
            client.person_credits = _stub_person_credits(catalog)
            picks = cinematic_dna(client, seed, top_k=5)
            assert isinstance(picks, list)
            samples["cinematic_dna_stub"] = [
                (r.movie.get("title"), round(r.score, 3)) for r in picks
            ]
            print(f"  [cinematic_dna stub] OK · {len(picks)} picks")
        except Exception as e:  # noqa: BLE001
            failures.append(f"cinematic_dna_stub: {type(e).__name__}: {e}")
            print(f"  FAIL: cinematic_dna_stub: {type(e).__name__}: {e}")

        # cinematic_dna with TMDBClient(fake key) and no credits -> TMDBError expected
        try:
            client = TMDBClient(api_key="fake")
            seed_no_credits = {"id": 1, "title": "Test"}
            try:
                picks = cinematic_dna(client, seed_no_credits)
                # No error: that means TMDB responded 200 for movie/1 with fake key,
                # which shouldn't happen. Either way, accept gracefully.
                print(
                    f"  [cinematic_dna fake-key] unexpected no-error: "
                    f"{len(picks)} picks"
                )
            except TMDBError as e:
                msg = _safe_redact(str(e))
                if any(s in msg for s in PROXY_SENTINELS):
                    failures.append(f"cinematic_dna fake-key: proxy leaked: {msg}")
                    print(f"  FAIL: cinematic_dna fake-key: proxy leaked")
                else:
                    print(
                        f"  [cinematic_dna fake-key] TMDBError raised as expected: "
                        f"{msg[:80]}"
                    )
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                if _is_proxy_error(e):
                    failures.append(f"cinematic_dna fake-key: proxy leaked: {msg}")
                    print(f"  FAIL: cinematic_dna fake-key: proxy leaked")
                else:
                    failures.append(f"cinematic_dna fake-key: {msg}")
                    print(f"  FAIL: cinematic_dna fake-key: {msg}")
        except Exception as e:  # noqa: BLE001
            failures.append(f"cinematic_dna fake-key: {type(e).__name__}: {e}")

    return failures, samples


def _safe_redact(s: str) -> str:
    """Trim an error string for one-line display."""
    return s.replace("\n", " ")[:160]


def _scenario_empty():
    print("\n=== Scenario 2: empty catalog + empty profile safety ===")
    failures: list[str] = []

    with proxy_env(None):
        from src.features import FeatureSpace, TasteProfile
        from src.recommenders import (
            tonight_decoder, anti_bubble, taste_twin, vibe_match,
            group_peace_treaty, mood_map, recommend_in_mood,
        )

        empty_space = FeatureSpace().fit([])
        empty_profile = TasteProfile()

        empty_cases = [
            (
                "tonight_decoder(empty)",
                lambda: tonight_decoder(
                    empty_space, empty_profile, [],
                    max_minutes=120, energy="cozy", hard_no_genres=[],
                ),
                list,
            ),
            (
                "anti_bubble(empty)",
                lambda: anti_bubble(empty_space, empty_profile),
                list,
            ),
            (
                "taste_twin(empty)",
                lambda: taste_twin(empty_space, empty_profile, target_decade=1990),
                list,
            ),
            (
                "vibe_match(empty)",
                lambda: vibe_match(empty_space, "rainy night", liked_ids=set()),
                list,
            ),
            (
                "group_peace_treaty(empty)",
                lambda: group_peace_treaty(empty_space, [empty_profile]),
                list,
            ),
            (
                "mood_map(empty)",
                lambda: mood_map(empty_space, profile=empty_profile),
                dict,
            ),
            (
                "recommend_in_mood(empty)",
                lambda: recommend_in_mood(
                    empty_space,
                    {"clusters": [], "labels": np.zeros(0, dtype=int),
                     "user_placement": None},
                    cluster_id=0, profile=empty_profile,
                ),
                list,
            ),
        ]

        for name, fn, expect_type in empty_cases:
            try:
                result = fn()
                if isinstance(result, expect_type):
                    sz = len(result) if hasattr(result, "__len__") else "?"
                    print(f"  [{name}] OK · {expect_type.__name__}({sz})")
                else:
                    failures.append(name)
                    print(
                        f"  FAIL: {name} -> got {type(result).__name__}, "
                        f"expected {expect_type.__name__}"
                    )
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                if _is_proxy_error(e):
                    failures.append(f"{name}: proxy leaked")
                    print(f"  FAIL: {name}: proxy leaked")
                else:
                    failures.append(f"{name}: {msg}")
                    print(f"  FAIL: {name}: {msg}")

    return failures


def _scenario_minilm_fallback():
    print("\n=== Scenario 3: MiniLM fallback under broken proxy ===")
    failures: list[str] = []

    with proxy_env(BAD_PROXY):
        from src import embeddings
        # Force the embedding backend into "none" without actually trying to
        # hit the network — exercises the tfidf+meta fallback path in fit().
        embeddings._mark_unavailable("smoke test forced unavailable")
        backend = embeddings.embedding_backend()
        print(f"  [embedding backend after reset] {backend}")
        if backend != "none":
            print(f"  WARN: backend is {backend}, not 'none'")

        from src.app_state import _offline_catalog

        try:
            catalog, space = _offline_catalog()
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if _is_proxy_error(e):
                failures.append(f"_offline_catalog under broken proxy: {msg}")
                print(f"  FAIL: _offline_catalog leaked proxy error: {msg}")
            else:
                failures.append(f"_offline_catalog: {msg}")
                print(f"  FAIL: _offline_catalog: {msg}")
            return failures

        print(
            f"  [FeatureSpace.fit] backend={space.backend} · "
            f"matrix={None if space.matrix is None else space.matrix.shape}"
        )
        if "minilm" in space.backend:
            failures.append("MiniLM did not fall back under broken proxy")
            print(f"  FAIL: MiniLM did not fall back under broken proxy")
        else:
            print(f"  OK: MiniLM unavailable, fit() fell back to {space.backend}")

        # And exercise vibe_match under this fallback to make sure the
        # encode_query -> None branch is exercised.
        try:
            from src.recommenders import vibe_match
            picks = vibe_match(space, "rainy mystery", liked_ids=set(), top_k=3)
            assert isinstance(picks, list)
            print(f"  [vibe_match under fallback] OK · {len(picks)} picks")
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if _is_proxy_error(e):
                failures.append(f"vibe_match under fallback: {msg}")
            else:
                failures.append(f"vibe_match under fallback: {msg}")
            print(f"  FAIL: vibe_match under fallback: {msg}")

    return failures


def main() -> int:
    failures: list[str] = []
    samples: dict[str, Any] = {}

    f1, s1 = _scenario_normal()
    failures.extend(f1)
    samples.update(s1)

    f2 = _scenario_empty()
    failures.extend(f2)

    f3 = _scenario_minilm_fallback()
    failures.extend(f3)

    print("\n=== Sample outputs ===")
    if not samples:
        print("  (no samples collected)")
    for mode, rows in samples.items():
        print(f"  [{mode}]")
        for r in rows[:3]:
            print(f"    {r}")

    if failures:
        print("\n=== FAILED ===")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\n=== ALL RECOMMENDERS SMOKE TESTS PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())