"""Research experiment over the held-out test carriers (offline, full scale).

    python -m pipeline.run_experiments                     # all test carriers, 50 % payload
    python -m pipeline.run_experiments --images 200 --relative 0.25
    python -m pipeline.run_experiments --payload-mode absolute --absolute-bytes 64

Runs exactly the same measurement code as the Experiments page
(app.services.experiments.run_comparison) and stores the run in the database
(source="pipeline"), so the UI and the landing page show it. A JSON copy is
written to docs/experiments/ for the report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.common import ROOT  # noqa: F401  (sets sys.path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", type=int, default=0, help="0 = all held-out test carriers")
    parser.add_argument("--payload-mode", choices=["relative", "absolute"], default="relative")
    parser.add_argument("--relative", type=float, default=0.5)
    parser.add_argument("--absolute-bytes", type=int, default=64)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    from app.core.streaming import Trace
    from app.db.session import SessionLocal
    from app.services.experiments import run_comparison, test_carriers

    total = len(test_carriers())
    images = total if args.images <= 0 else min(args.images, total)

    def emit(event: dict) -> None:
        print(f"[{event['stage']}] {event['message']}", flush=True)

    with SessionLocal() as db:
        result = run_comparison(
            Trace(emit=emit), db, None, images=images, payload_mode=args.payload_mode, relative=args.relative,
            absolute_bytes=args.absolute_bytes, seed=args.seed, source="pipeline",
        )  # fmt: skip

    out_dir = Path(__file__).resolve().parents[2] / "docs" / "experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"technique_comparison_{args.payload_mode}_{images}.json"
    out.write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    print(f"\nStored run {result['run_id']} and wrote {out}")
    print(result["answer"])


if __name__ == "__main__":
    main()
