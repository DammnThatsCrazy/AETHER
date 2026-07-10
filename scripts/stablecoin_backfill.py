#!/usr/bin/env python3
"""Run a tenant-scoped Stablecoin Intelligence backfill from a JSON rows file.

This command is intentionally connector-neutral. Production connectors can emit
rows in the same schema and invoke the same runner; local/staging operators can
use --dry-run and --verify-only before writing Bronze/Silver/observation state.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Backend Architecture" / "aether-backend"))

from services.stablecoins.ingestion import ProviderObservation  # noqa: E402
from services.stablecoins.models import FinalityState, StablecoinEventType  # noqa: E402
from services.stablecoins.providers import StablecoinProviderIngestionRunner  # noqa: E402


def _load_rows(path: str, *, tenant_id: str, provider: str, execution_id: str, manifest_id: str) -> list[ProviderObservation]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text())
    rows = payload if isinstance(payload, list) else payload.get("rows", [])
    observations: list[ProviderObservation] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {idx} must be an object")
        observations.append(ProviderObservation(
            tenant_id=row.get("tenant_id", tenant_id),
            provider=row.get("provider", provider),
            source_record_id=str(row.get("source_record_id", row.get("id", idx))),
            source_execution_id=row.get("source_execution_id", execution_id),
            source_manifest_id=row.get("source_manifest_id", manifest_id),
            observed_at=row["observed_at"],
            chain_id=str(row["chain_id"]),
            network=row["network"],
            contract_or_mint=row["contract_or_mint"],
            transaction_hash=row["transaction_hash"],
            amount_atomic=int(row["amount_atomic"]),
            from_address=row.get("from_address", ""),
            to_address=row.get("to_address", ""),
            log_or_instruction_index=row.get("log_or_instruction_index"),
            event_type=StablecoinEventType(row.get("event_type", StablecoinEventType.UNKNOWN_STABLECOIN_MOVEMENT.value)),
            finality_status=FinalityState(row.get("finality_status", FinalityState.OBSERVED.value)),
            raw_payload=row,
        ))
    return observations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stablecoin Intelligence backfill runner")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--asset-id", default="")
    parser.add_argument("--deployment-id", default="")
    parser.add_argument("--chain-id", default="")
    parser.add_argument("--source", required=True)
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--resume-from", default="")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--rollback-tag", default="")
    parser.add_argument("--source-execution-id", required=True)
    parser.add_argument("--source-manifest-id", required=True)
    parser.add_argument("--input-json", default="", help="JSON file containing provider rows")
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    rows = _load_rows(args.input_json, tenant_id=args.tenant_id, provider=args.source, execution_id=args.source_execution_id, manifest_id=args.source_manifest_id)
    if args.chain_id:
        rows = [row for row in rows if row.chain_id == args.chain_id]
    if args.limit:
        rows = rows[: args.limit]
    report = await StablecoinProviderIngestionRunner().run_execution(
        tenant_id=args.tenant_id,
        provider=args.source,
        source_execution_id=args.source_execution_id,
        source_manifest_id=args.source_manifest_id,
        observations=rows,
        dry_run=args.dry_run or args.verify_only,
        rollback_tag=args.rollback_tag,
    )
    return report.__dict__


def main() -> int:
    args = _parser().parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["rows_rejected"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
