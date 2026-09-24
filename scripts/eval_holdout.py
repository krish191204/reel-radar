#!/usr/bin/env python3
"""Temporal holdout evaluation + optional ranker weight tuning.

Examples:
  python scripts/eval_holdout.py
  python scripts/eval_holdout.py --csv data/examples/letterboxd_sample.csv --tune --k 10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.catalog import build_catalog  # noqa: E402
from src.eval import evaluate_profile, leave_one_out_hitrate, temporal_split  # noqa: E402
from src.ranking import save_weights  # noqa: E402
from src.taste_io import import_taste_csv  # noqa: E402
from src.tmdb import TMDBClient, TMDBError  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Reel Radar holdout evaluation")
    ap.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "data" / "examples" / "letterboxd_sample.csv",
        help="Letterboxd-style ratings CSV",
    )
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--tune", action="store_true", help="Grid-tune margin weights and persist")
    ap.add_argument("--offline", action="store_true", help="Prefer persisted catalog only")
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 2

    client = TMDBClient()
    print(f"Importing taste from {args.csv}…")
    try:
        imported = import_taste_csv(client, args.csv.read_bytes(), max_rows=500)
    except TMDBError as e:
        print(f"TMDB import failed: {e}", file=sys.stderr)
        return 1

    print(
        f"Rated {imported.stats.get('rated', 0)} · "
        f"likes {imported.stats.get('likes', 0)} · "
        f"dislikes {imported.stats.get('dislikes', 0)} · "
        f"unresolved {len(imported.unresolved)}"
    )
    if len(imported.rated) < 5:
        print("Need at least ~5 resolved ratings.", file=sys.stderr)
        return 1

    print("Building feature space…")
    catalog, space = build_catalog(
        client,
        seed_movies=imported.rated,
        pages=1,
        enrich_top=20,
        min_catalog=1500,
    )
    print(f"Catalog {len(catalog)} · backend {space.backend}")

    train, test = temporal_split(
        imported.rated,
        imported.ratings,
        holdout_frac=args.holdout,
        min_train=4,
        min_test=2,
    )
    print(f"Split train={len(train)} test={len(test)}")

    results = []
    if train and test:
        results = evaluate_profile(
            space,
            train,
            test,
            imported.ratings,
            k=args.k,
            tune=args.tune,
        )
    else:
        print("Holdout split too small — running leave-one-out only.")

    loo = leave_one_out_hitrate(space, imported.rated, imported.ratings, k=args.k)

    print()
    print(f"{'ablation':<28} {'HR@'+str(args.k):>8} {'nDCG@'+str(args.k):>8} {'popBias':>8} {'n':>4}")
    print("-" * 60)
    for r in results:
        print(
            f"{r.name:<28} {r.hit_rate_at_k:8.3f} {r.ndcg_at_k:8.3f} "
            f"{r.popularity_bias:8.2f} {r.n:4d}"
        )
    print(
        f"{loo.name:<28} {loo.hit_rate_at_k:8.3f} {loo.ndcg_at_k:8.3f} "
        f"{loo.popularity_bias:8.2f} {loo.n:4d}"
    )

    tuned = next((r for r in results if r.name == "margin_tuned"), None)
    if args.tune and tuned and tuned.details.get("weights"):
        save_weights(tuned.details["weights"])
        print()
        print("Saved tuned weights → data/ranker_weights.json")
        print(json.dumps(tuned.details["weights"], indent=2))
        if tuned.details.get("tune"):
            print("Tune metrics:", tuned.details["tune"])

    out_path = ROOT / "data" / "eval_report.json"
    payload = {
        "k": args.k,
        "backend": space.backend,
        "catalog": len(catalog),
        "train": len(train),
        "test": len(test),
        "results": [
            {
                "name": r.name,
                "hit_rate_at_k": r.hit_rate_at_k,
                "ndcg_at_k": r.ndcg_at_k,
                "popularity_bias": r.popularity_bias,
                "n": r.n,
                "details": {
                    kk: vv
                    for kk, vv in r.details.items()
                    if kk in {"weights", "tune"}
                },
            }
            for r in results
        ],
        "loo": {
            "hit_rate_at_k": loo.hit_rate_at_k,
            "ndcg_at_k": loo.ndcg_at_k,
            "n": loo.n,
        },
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
