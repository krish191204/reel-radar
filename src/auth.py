"""Per-user login + taste persistence for Reel Radar.

Stores one JSON file per user under ``data/users/<username>.json``. Passwords are
hashed with PBKDF2-HMAC-SHA256 + per-user salt (stdlib only — no extra deps).

Schema::

    {
        "username": "krish",
        "created_at": 1754000000,
        "password": "pbkdf2_sha256$200000$<salt_hex>$<hash_hex>",
        "taste": {
            "taste_picks":   [movie, ...],
            "dislike_picks": [movie, ...],
            "rated_picks":   [movie, ...],
            "taste_ratings": {tmdb_id: float, ...},
            "import_stats":  {...}
        }
    }

The taste keys mirror ``st.session_state`` exactly so ``load_taste`` can drop
straight back into a fresh session.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
USERS_DIR = DATA_DIR / "users"

# PBKDF2 parameters — 200k iterations is OWASP-recommended for SHA-256 in 2025.
PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERS = 200_000
SALT_BYTES = 16

# Username rules — keep simple, prevent path traversal.
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")


class AuthError(RuntimeError):
    """User-visible auth failure (bad credentials, username taken, etc.)."""


# ─── Password hashing ───────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    salt = secrets.token_hex(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERS
    )
    return f"{PBKDF2_ALGO}${PBKDF2_ITERS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt, hash_hex = stored.split("$", 3)
    except ValueError:
        return False
    if algo != PBKDF2_ALGO:
        return False
    try:
        iters = int(iters_s)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iters
    )
    return hmac.compare_digest(digest.hex(), hash_hex)


# ─── User store ─────────────────────────────────────────────────────────────


def _safe_username(username: str) -> str:
    if not USERNAME_RE.match(username):
        raise AuthError(
            "Username must be 3-32 chars: letters, digits, underscore, hyphen."
        )
    return username


def _user_path(username: str) -> Path:
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    return USERS_DIR / f"{username}.json"


def _read_user(username: str) -> dict[str, Any] | None:
    path = _user_path(username)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_user(record: dict[str, Any]) -> None:
    path = _user_path(record["username"])
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    # Lock down permissions on POSIX — owner read/write only.
    try:
        path.chmod(0o600)
    except (OSError, NotImplementedError):
        pass


# Keys we persist from st.session_state. Keep in sync with streamlit_shell.py.
TASTE_KEYS = ("taste_picks", "dislike_picks", "rated_picks", "taste_ratings", "import_stats", "watchlist_picks")


def create_user(username: str, password: str) -> dict[str, Any]:
    """Create a new user record. Raises AuthError if username is taken."""
    uname = _safe_username(username)
    if len(password) < 6:
        raise AuthError("Password must be at least 6 characters.")
    if _read_user(uname) is not None:
        raise AuthError("Username already taken.")
    record = {
        "username": uname,
        "created_at": int(time.time()),
        "password": hash_password(password),
        "taste": {key: ([] if key != "taste_ratings" else {}) for key in TASTE_KEYS},
    }
    _write_user(record)
    return record


def authenticate(username: str, password: str) -> dict[str, Any]:
    """Return user record on success; raise AuthError on failure."""
    uname = _safe_username(username)
    record = _read_user(uname)
    if record is None or not verify_password(password, record.get("password", "")):
        # Same error either way — don't leak which usernames exist.
        raise AuthError("Invalid username or password.")
    return record


def save_taste(username: str, taste: dict[str, Any]) -> None:
    """Persist a taste dict to the user's record on disk.

    `taste_ratings` has int keys (TMDB ids) which JSON cannot represent, so
    we coerce them to strings on write and back to ints on read.
    """
    record = _read_user(username)
    if record is None:
        raise AuthError(f"Unknown user: {username}")
    out: dict[str, Any] = {}
    for key in TASTE_KEYS:
        default = [] if key != "taste_ratings" else {}
        value = taste.get(key, default)
        if key == "taste_ratings" and isinstance(value, dict):
            value = {str(k): float(v) for k, v in value.items()}
        out[key] = value
    record["taste"] = out
    record["taste_updated_at"] = int(time.time())
    _write_user(record)


def load_taste(username: str) -> dict[str, Any]:
    """Return the persisted taste dict for a user (or empty defaults).

    Coerces `taste_ratings` keys back to int so callers can do
    `ratings[tmdb_id]` lookups directly.
    """
    record = _read_user(username)
    if record is None:
        raise AuthError(f"Unknown user: {username}")
    taste = record.get("taste", {})
    raw_ratings = taste.get("taste_ratings")
    if isinstance(raw_ratings, dict):
        taste["taste_ratings"] = {int(k): float(v) for k, v in raw_ratings.items()}
    return taste


def list_users() -> list[str]:
    """Return all usernames (sorted, for debug pages only)."""
    if not USERS_DIR.exists():
        return []
    return sorted(p.stem for p in USERS_DIR.glob("*.json"))