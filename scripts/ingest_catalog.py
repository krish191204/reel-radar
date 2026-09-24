#!/usr/bin/env python3
"""Ingest ~2500 TMDB movies into data/catalog.json."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest import DEFAULT_TARGET, ingest_catalog  # noqa: E402
from src.tmdb import TMDBClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest TMDB movies for Reel Radar")
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET)
    parser.add_argument("--force", action="store_true", help="Ignore existing catalog")
    args = parser.parse_args()

    client = TMDBClient()

    def progress(message: str, current: int, total: int) -> None:
        pct = min(100, int(100 * current / max(total, 1)))
        print(f"[{pct:3d}% | {current}/{total}] {message}", flush=True)

    movies = ingest_catalog(
        client,
        target=args.target,
        force=args.force,
        progress=progress,
    )
    print(f"Done. Catalog size: {len(movies)}")


if __name__ == "__main__":
    main()
