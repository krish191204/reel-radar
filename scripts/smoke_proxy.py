"""Smoke test: confirm Reel Radar never propagates ProxyError / httpx / requests
tracebacks when HTTPS_PROXY/HTTP_PROXY/ALL_PROXY point at a broken sandbox.

Runs three scenarios end-to-end:
  1. Bad shell proxy + fake TMDB key -> CSV import + ensure_space + tonight_decoder
  2. Bad shell proxy + no TMDB key   -> offline path using data/catalog.json
  3. Proxies cleared + fake TMDB key -> control (should still be safe)

Exits non-zero on any uncaught proxy-flavored exception reaching top-level.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE_CSV = ROOT / "data" / "examples" / "letterboxd_sample.csv"
BAD_PROXY = "http://127.0.0.1:1"  # closed port -> immediate refusal
PROXY_VARS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)
# Anything that smells like a sandboxed proxy failure must not bubble up.
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


def _csv_bytes() -> bytes:
    if SAMPLE_CSV.exists():
        return SAMPLE_CSV.read_bytes()
    return (
        "Name,Year,Rating\nThe Matrix,1999,5.0\nSpirited Away,2001,5.0\n"
    ).encode()


def run_scenario(name: str, env_value: str | None, *, with_key: bool) -> None:
    print(f"\n=== {name} ===")
    if with_key:
        os.environ["TMDB_API_KEY"] = "smoke-test-fake-key"
    else:
        os.environ.pop("TMDB_API_KEY", None)

    with proxy_env(env_value):
        # Import inside the env context so HF Hub / httpx see the proxy vars.
        from src import taste_io
        from src.app_state import ensure_space
        from src.features import TasteProfile
        from src.recommenders import tonight_decoder
        from src.tmdb import TMDBClient, TMDBError

        client = TMDBClient()
        client.repair_session()
        assert client.session.trust_env is False, "trust_env still True"
        # Empty/None values are allowed; we just refuse to inherit env-supplied
        # proxies. requests stores env-derived entries as string URLs.
        for scheme in ("http", "https"):
            value = client.session.proxies.get(scheme)
            assert value in (None, ""), f"proxy {scheme}={value!r} leaked"

        # CSV import — must not raise a proxy-flavored error.
        try:
            imported = taste_io.import_taste_csv(client, _csv_bytes())
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if any(s in msg for s in PROXY_SENTINELS):
                raise SmokeFailure(f"CSV import leaked proxy error: {msg}") from e
            if isinstance(e, TMDBError):
                print(f"  [csv-import] tmdb-offline: {msg[:120]}")
            else:
                raise SmokeFailure(f"unexpected csv import error: {msg}") from e
        else:
            print(
                f"  [csv-import] {len(imported.rated)} rated · "
                f"{len(imported.unresolved)} unresolved"
            )

        # ensure_space must succeed using persisted catalog.json.
        try:
            catalog, space = ensure_space()
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if any(s in msg for s in PROXY_SENTINELS):
                raise SmokeFailure(f"ensure_space leaked proxy error: {msg}") from e
            raise SmokeFailure(f"ensure_space crashed: {msg}") from e
        assert catalog, "ensure_space returned empty catalog"
        print(f"  [ensure_space] catalog={len(catalog)} backend={space.backend}")

        seed = catalog[0]
        profile = TasteProfile(
            liked_ids=[seed["id"]],
            disliked_ids=[],
            liked_movies=[seed],
            ratings={int(seed["id"]): 5.0},
            vector=space.vector_for(seed),
        )
        try:
            picks = tonight_decoder(
                space,
                profile,
                catalog,
                max_minutes=180,
                energy="cozy",
                hard_no_genres=[],
            )
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if any(s in msg for s in PROXY_SENTINELS):
                raise SmokeFailure(f"tonight_decoder leaked proxy error: {msg}") from e
            raise SmokeFailure(f"tonight_decoder crashed: {msg}") from e
        print(f"  [tonight_decoder] {len(picks)} picks")


def main() -> int:
    failures: list[str] = []
    for label, env_value, with_key in (
        ("bad proxy + fake TMDB key", BAD_PROXY, True),
        ("bad proxy + no TMDB key (offline path)", BAD_PROXY, False),
        ("proxies cleared + fake TMDB key", None, True),
    ):
        try:
            run_scenario(label, env_value, with_key=with_key)
        except SmokeFailure as e:
            print(f"  FAIL: {e}")
            failures.append(label)

    if failures:
        print("\nFAILED scenarios:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll smoke scenarios passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())