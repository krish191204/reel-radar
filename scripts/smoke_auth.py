"""Smoke test: create → authenticate → save/load taste → re-authenticate → wipe.

Exits 0 on success, 1 on any failure. Cleans up its own test user.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.auth import (  # noqa: E402
    AuthError,
    USERS_DIR,
    authenticate,
    create_user,
    hash_password,
    list_users,
    load_taste,
    save_taste,
    verify_password,
)


TEST_USER = "smoke_test_user"


def _cleanup() -> None:
    user_path = USERS_DIR / f"{TEST_USER}.json"
    if user_path.exists():
        user_path.unlink()


def main() -> int:
    failures: list[str] = []

    try:
        # Clean slate
        _cleanup()

        # 1. hash + verify round-trip
        h = hash_password("hunter2!")
        if not verify_password("hunter2!", h):
            failures.append("verify_password failed for correct password")
        if verify_password("wrong", h):
            failures.append("verify_password accepted wrong password")
        print(f"  [hash] ok ({h[:32]}…)")

        # 2. create user
        record = create_user(TEST_USER, "hunter2!")
        if record["username"] != TEST_USER:
            failures.append("create_user returned wrong username")
        print(f"  [create] user created · {USERS_DIR / f'{TEST_USER}.json'}")

        # 3. duplicate username
        try:
            create_user(TEST_USER, "hunter2!")
            failures.append("create_user allowed duplicate username")
        except AuthError:
            print("  [create] duplicate rejected")

        # 4. wrong password
        try:
            authenticate(TEST_USER, "wrong")
            failures.append("authenticate accepted wrong password")
        except AuthError:
            print("  [auth] wrong password rejected")

        # 5. correct password
        record2 = authenticate(TEST_USER, "hunter2!")
        if record2["username"] != TEST_USER:
            failures.append("authenticate returned wrong record")
        print(f"  [auth] correct password ok · created_at={record2['created_at']}")

        # 6. username validation
        try:
            create_user("ab", "hunter2!")
            failures.append("create_user accepted too-short username")
        except AuthError:
            print("  [validate] short username rejected")
        try:
            create_user("evil/path", "hunter2!")
            failures.append("create_user accepted path-traversal username")
        except AuthError:
            print("  [validate] path-traversal username rejected")

        # 7. save + load taste
        taste = {
            "taste_picks":   [{"id": 1, "title": "The Matrix"}],
            "dislike_picks": [{"id": 2, "title": "Cats"}],
            "rated_picks":   [{"id": 1, "title": "The Matrix"}, {"id": 2, "title": "Cats"}],
            "taste_ratings": {1: 5.0, 2: 0.5},
            "import_stats":  {"rated": 2, "likes": 1, "dislikes": 1, "avg_rating": 2.75},
        }
        save_taste(TEST_USER, taste)
        loaded = load_taste(TEST_USER)
        for k, v in taste.items():
            if loaded.get(k) != v:
                failures.append(f"round-trip mismatch on {k!r}")
        print(f"  [taste] round-trip ok · {len(loaded['taste_ratings'])} ratings persisted")

        # 8. partial save (only one key) — defaults fill the rest
        save_taste(TEST_USER, {"taste_picks": [{"id": 99, "title": "X"}]})
        loaded = load_taste(TEST_USER)
        if loaded["taste_picks"] != [{"id": 99, "title": "X"}]:
            failures.append("partial save did not update taste_picks")
        if loaded["taste_ratings"] != {}:
            failures.append("partial save did not reset omitted keys to default")
        print("  [taste] partial save respects defaults")

        # 9. list_users
        users = list_users()
        if TEST_USER not in users:
            failures.append(f"list_users missing {TEST_USER}")
        print(f"  [list] {len(users)} user(s)")

        # 10. password hash format
        if not record["password"].startswith("pbkdf2_sha256$200000$"):
            failures.append("password hash format unexpected")
        print(f"  [hash] format {record['password'].split('$')[1]} iters")

    finally:
        _cleanup()

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL AUTH SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())