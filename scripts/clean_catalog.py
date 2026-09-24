#!/usr/bin/env python3
"""Clean + normalize data/catalog.json; print a short quality report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.clean import clean_catalog  # noqa: E402


def main() -> None:
    cleaned, report = clean_catalog()
    print(json.dumps(report, indent=2))
    print(f"\nClean catalog: {len(cleaned)} movies")


if __name__ == "__main__":
    main()
