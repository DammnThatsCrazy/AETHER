#!/usr/bin/env python3
"""Evaluate identity decisions against a curated human-review JSONL export.

This offline tool measures false merges, false non-merges and observed
same-identity rates by score band. A score is ordinal match strength, not a
probability. The report cannot calibrate production or tune resolver policy.
Each input row requires decision_id, score, same_identity, runtime_action, and
label_source="human_review".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.backend.services.identity.calibration_evaluation import (  # noqa: E402
    evaluate_calibration,
    load_reviewed_pairs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", type=Path, help="Curated human-reviewed pair labels in JSONL format")
    parser.add_argument("--bins", type=int, default=10, help="Reliability bins (default: 10)")
    parser.add_argument("--minimum-labels", type=int, default=500,
                        help="Minimum total reviewed pairs required (default: 500)")
    parser.add_argument("--minimum-per-band", type=int, default=30,
                        help="Minimum reviewed pairs in every score band (default: 30)")
    parser.add_argument("--minimum-each-class-per-band", type=int, default=10,
                        help="Minimum same/different identity labels in every band (default: 10)")
    parser.add_argument("--maximum-interval-half-width", type=float, default=0.15,
                        help="Maximum 95%% Wilson interval half-width in each band (default: 0.15)")
    parser.add_argument("--minimum-tenants", type=int, default=3,
                        help="Minimum distinct opaque tenant references (default: 3)")
    parser.add_argument("--minimum-source-families", type=int, default=2,
                        help="Minimum distinct source families (default: 2)")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path; stdout by default")
    args = parser.parse_args()
    try:
        report = evaluate_calibration(
            load_reviewed_pairs(args.labels),
            bins=args.bins,
            minimum_labels=args.minimum_labels,
            minimum_per_band=args.minimum_per_band,
            minimum_each_class_per_band=args.minimum_each_class_per_band,
            maximum_interval_half_width=args.maximum_interval_half_width,
            minimum_tenants=args.minimum_tenants,
            minimum_source_families=args.minimum_source_families,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
