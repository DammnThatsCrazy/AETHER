#!/usr/bin/env python3
"""Emit a bounded, non-mutating rights reconciliation report."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.rights_authority.reconciliation import build_reconciliation_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id")
    parser.add_argument("--limit-per-table", type=int, default=10_000)
    parser.add_argument("--json", dest="json_path")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when rights-less rows are found",
    )
    args = parser.parse_args()
    if args.limit_per_table < 1 or args.limit_per_table > 100_000:
        parser.error("--limit-per-table must be between 1 and 100000")
    report = asyncio.run(build_reconciliation_report(
        tenant_id=args.tenant_id,
        limit_per_table=args.limit_per_table,
    ))
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.json_path:
        Path(args.json_path).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if args.strict and report["totals"]["rightsless"] else 0


if __name__ == "__main__":
    sys.exit(main())
