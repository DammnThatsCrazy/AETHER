#!/usr/bin/env python3
"""Rekey existing Gold lake records onto the tenant-inclusive record_id.

Background
----------
``GoldRepository.materialize()`` (Backend Architecture/aether-backend/
repositories/lake.py) computes::

    record_id = sha256(f"{tenant_id}:{metric_name}:{entity_id}:{entity_type}")[:24]

Before that was fixed, the formula omitted ``tenant_id`` entirely::

    record_id = sha256(f"{metric_name}:{entity_id}:{entity_type}")[:24]

so two tenants materializing the same ``(metric_name, entity_id, entity_type)``
collided on one row and silently overwrote each other — whichever tenant
wrote last "won", and the earlier tenant's value is gone for good. Existing
Gold rows written under the old formula are still stored under a key that
does not match what ``materialize()`` computes today for their own
``tenant_id``/``metric_name``/``entity_id``/``entity_type``. This script finds
and repairs exactly that mismatch.

What this script does
----------------------
For every Gold domain table (``gold_<domain>``):

1. Scan every row (read-only).
2. For each row, recompute the canonical record_id from the row's OWN
   ``tenant_id``/``metric_name``/``entity_id``/``entity_type`` fields, using
   ``GoldRepository.compute_record_id`` — the exact function ``materialize()``
   hashes inline. This script never reimplements/forks the formula.
3. A row whose current key already equals its canonical id needs nothing
   (counted as ``skipped``).
4. A row whose current key differs is a legacy/mis-keyed row that wants to
   move to the canonical id (counted as ``rekeyed``).
5. If two or more CURRENT rows want the SAME canonical id — a genuine
   collision, e.g. a stale pre-fix row sitting next to a row that was already
   correctly (re)materialized after the fix shipped, for the same
   tenant/metric/entity/type — the row with the latest ``updated_at`` wins and
   is written/kept at the canonical id. Every other competitor is left
   completely untouched at its current (stale) key and logged in full: never
   deleted, never silently dropped (counted as ``collisions`` /
   ``collision_rows_dropped``).

An old tenant-less key that was overwritten by a LATER tenant before this
script ever runs cannot be un-overwritten — that data loss already happened
at write time, silently, long before a backfill exists to look at it. This
script can only relocate whatever row currently exists; see the runbook's
cross-tenant-corruption caveat (docs/runbooks/GOLD-TENANT-BACKFILL.md).

Safety
------
- Dry-run by default. Nothing is written unless ``--apply`` is passed.
- Idempotent: rows already at their canonical id are left alone; a row moved
  by a prior run is gone from its old key, so a second run reports
  ``rekeyed: 0`` for it.
- In local mode (no live database pool) this operates on the shared
  in-memory Gold store via the same BaseRepository primitives lake.py itself
  uses — find_many / find_by_id / insert / delete. Nothing here forks lake.py's
  storage logic.
- Against a real database pool, ``--apply`` additionally requires
  ``--confirm-prod`` as an explicit second confirmation. Take a backup first —
  see docs/runbooks/GOLD-TENANT-BACKFILL.md.

Usage
-----
    # Dry run across every known Gold domain
    python scripts/gold_tenant_backfill.py

    # Dry run, one domain only
    python scripts/gold_tenant_backfill.py --domain market

    # Apply (local / in-memory)
    AETHER_ENV=local python scripts/gold_tenant_backfill.py --apply

    # Apply against a real database (extra confirmation required)
    python scripts/gold_tenant_backfill.py --apply --confirm-prod

    # Machine-readable report
    python scripts/gold_tenant_backfill.py --json

Exit codes: 0 = clean (no unresolved collisions), 1 = refused to run
(--apply against a live pool without --confirm-prod), 2 = ran but left one or
more unresolved collisions in place (see the printed/--json report).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
for _path in (str(BACKEND), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from repositories.lake import GoldRepository  # noqa: E402
from repositories.repos import BaseRepository, get_pool  # noqa: E402
from shared.common.common import utc_now  # noqa: E402
from shared.logger.logger import get_logger  # noqa: E402

logger = get_logger("aether.scripts.gold_tenant_backfill")

DEFAULT_PAGE_SIZE = 500


class ConfirmationRequired(RuntimeError):
    """Raised when --apply targets a live database pool without --confirm-prod."""


# ═══════════════════════════════════════════════════════════════════════════
# Domain discovery
# ═══════════════════════════════════════════════════════════════════════════

def discover_gold_domains() -> list[str]:
    """Default domain set when --domain is not given.

    Every module-level GoldRepository declared in repositories.lake (market,
    onchain, social, ..., web3_daily_metrics) — the complete set of Gold
    domains the codebase currently knows about. A domain that only exists
    dynamically (no module-level constant, e.g. one created ad hoc by a
    connector or a test) is still reachable by passing --domain explicitly.
    """
    import repositories.lake as lake_module

    seen: set[str] = set()
    domains: list[str] = []
    for value in vars(lake_module).values():
        if isinstance(value, GoldRepository) and value.table_name not in seen:
            seen.add(value.table_name)
            domains.append(value.table_name[len("gold_"):])
    return sorted(domains)


# ═══════════════════════════════════════════════════════════════════════════
# Scan (read-only)
# ═══════════════════════════════════════════════════════════════════════════

async def _scan_all(
    repo: BaseRepository, *, page_size: int, row_limit: Optional[int]
) -> list[dict[str, Any]]:
    """Read every row in `repo`'s table. Read-only — never writes.

    Paged via find_many/offset. Safe against drift because nothing mutates
    the table between pages here: the whole point of the plan/apply split
    below is that ALL reads finish before any write starts.
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    while row_limit is None or len(rows) < row_limit:
        take = page_size if row_limit is None else min(page_size, row_limit - len(rows))
        if take <= 0:
            break
        batch = await repo.find_many(
            filters=None, limit=take, offset=offset, sort_by="created_at", sort_order="asc",
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < take:
            break
        offset += take
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# Plan (pure — decides what WOULD happen; never writes)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RowInfo:
    current_id: str
    tenant_id: str
    metric_name: Any
    entity_id: Any
    entity_type: Any
    updated_at: str
    canonical_id: str
    raw: dict[str, Any]


@dataclass
class CollisionGroup:
    canonical_id: str
    winner: RowInfo
    losers: list[RowInfo]


@dataclass
class TablePlan:
    table_name: str
    scanned: int = 0
    already_correct: list[RowInfo] = field(default_factory=list)
    malformed: int = 0
    simple_moves: list[RowInfo] = field(default_factory=list)
    collisions: list[CollisionGroup] = field(default_factory=list)

    @property
    def rekeyed_count(self) -> int:
        moved = len(self.simple_moves)
        moved += sum(1 for g in self.collisions if g.winner.current_id != g.canonical_id)
        return moved

    @property
    def collision_loser_count(self) -> int:
        return sum(len(g.losers) for g in self.collisions)

    @property
    def skipped_count(self) -> int:
        return len(self.already_correct) + self.malformed


def _row_info(row: dict[str, Any]) -> Optional[RowInfo]:
    current_id = row.get("id") or ""
    metric_name = row.get("metric_name")
    entity_id = row.get("entity_id")
    entity_type = row.get("entity_type")
    if not current_id or metric_name is None or entity_id is None or entity_type is None:
        return None
    tenant_id = row.get("tenant_id") or ""
    canonical_id = GoldRepository.compute_record_id(
        tenant_id=tenant_id, metric_name=metric_name, entity_id=entity_id, entity_type=entity_type,
    )
    return RowInfo(
        current_id=current_id,
        tenant_id=tenant_id,
        metric_name=metric_name,
        entity_id=entity_id,
        entity_type=entity_type,
        updated_at=row.get("updated_at") or "",
        canonical_id=canonical_id,
        raw=row,
    )


def _plan_table(table_name: str, rows: list[dict[str, Any]]) -> TablePlan:
    plan = TablePlan(table_name=table_name, scanned=len(rows))
    by_canonical: dict[str, list[RowInfo]] = {}
    for row in rows:
        info = _row_info(row)
        if info is None:
            plan.malformed += 1
            continue
        by_canonical.setdefault(info.canonical_id, []).append(info)

    for canonical_id, group in by_canonical.items():
        if len(group) == 1:
            info = group[0]
            if info.current_id == canonical_id:
                plan.already_correct.append(info)
            else:
                plan.simple_moves.append(info)
            continue

        # Collision: 2+ CURRENT rows resolve to the same tenant-scoped
        # identity. Documented, conservative policy: the row with the latest
        # updated_at wins and is written/kept at canonical_id; every other
        # competitor is left exactly where it is — never deleted — and fully
        # logged (see _report_for). Ties break on current_id purely for a
        # stable, repeatable outcome, not a claim about which row is "right".
        winner = max(group, key=lambda r: (r.updated_at, r.current_id))
        losers = [r for r in group if r is not winner]
        plan.collisions.append(CollisionGroup(canonical_id=canonical_id, winner=winner, losers=losers))

    return plan


# ═══════════════════════════════════════════════════════════════════════════
# Apply (the only place that writes)
# ═══════════════════════════════════════════════════════════════════════════

async def _move(repo: BaseRepository, info: RowInfo) -> None:
    """Relocate a row's content to its canonical id.

    Defensive re-check: if something now occupies canonical_id that was not
    there when this table was scanned (e.g. live traffic materialized
    correctly at that key while this backfill was running), never
    blind-overwrite it — apply the same latest-updated_at policy at write
    time and leave `info`'s row exactly where it is if it loses.
    """
    existing = await repo.find_by_id(info.canonical_id)
    if existing is not None and existing.get("id") != info.current_id:
        if (existing.get("updated_at") or "") >= info.updated_at:
            logger.warning(
                "gold_tenant_backfill late collision at %s: keeping existing row, "
                "leaving %s untouched", info.canonical_id, info.current_id,
            )
            return
    new_data = dict(info.raw)
    await repo.insert(info.canonical_id, new_data)
    await repo.delete(info.current_id)


async def _apply_table(repo: BaseRepository, plan: TablePlan) -> None:
    for info in plan.simple_moves:
        await _move(repo, info)
    for group in plan.collisions:
        if group.winner.current_id != group.canonical_id:
            await _move(repo, group.winner)
        # Losers are intentionally left untouched at their current key —
        # never deleted. See the module docstring / runbook collision policy.


# ═══════════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════════

def _row_summary(info: RowInfo) -> dict[str, Any]:
    return {
        "id": info.current_id,
        "tenant_id": info.tenant_id,
        "metric_name": info.metric_name,
        "entity_id": info.entity_id,
        "entity_type": info.entity_type,
        "updated_at": info.updated_at,
        "value": info.raw.get("value"),
    }


def _report_for(plan: TablePlan) -> dict[str, Any]:
    moved: list[dict[str, Any]] = []
    for info in plan.simple_moves:
        moved.append({
            "from": info.current_id, "to": info.canonical_id,
            "tenant_id": info.tenant_id, "metric_name": info.metric_name,
            "entity_id": info.entity_id, "entity_type": info.entity_type,
        })
    for g in plan.collisions:
        if g.winner.current_id != g.canonical_id:
            moved.append({
                "from": g.winner.current_id, "to": g.canonical_id,
                "tenant_id": g.winner.tenant_id, "metric_name": g.winner.metric_name,
                "entity_id": g.winner.entity_id, "entity_type": g.winner.entity_type,
                "collision_winner": True,
            })

    collision_detail = [
        {
            "canonical_id": g.canonical_id,
            "winner": _row_summary(g.winner),
            "losers": [_row_summary(l) for l in g.losers],
        }
        for g in plan.collisions
    ]

    return {
        "table": plan.table_name,
        "scanned": plan.scanned,
        "rekeyed": plan.rekeyed_count,
        "collisions": len(plan.collisions),
        "collision_rows_dropped": plan.collision_loser_count,
        "skipped": plan.skipped_count,
        "skipped_already_correct": len(plan.already_correct),
        "skipped_malformed": plan.malformed,
        "moved": moved,
        "collision_detail": collision_detail,
    }


def _sum_totals(domain_reports: list[dict[str, Any]]) -> dict[str, int]:
    keys = ("scanned", "rekeyed", "collisions", "collision_rows_dropped", "skipped")
    return {k: sum(r[k] for r in domain_reports) for k in keys}


# ═══════════════════════════════════════════════════════════════════════════
# Orchestration
# ═══════════════════════════════════════════════════════════════════════════

async def run_backfill(
    domains: Optional[list[str]] = None,
    *,
    apply: bool = False,
    confirm_prod: bool = False,
    batch_size: int = DEFAULT_PAGE_SIZE,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Scan (and, if apply, rekey) every requested Gold domain.

    domains=None scans every domain discover_gold_domains() finds. Always
    dry-run (report only, zero writes) unless apply=True. apply=True against
    a live database pool additionally requires confirm_prod=True.
    """
    pool = await get_pool()
    is_prod = pool is not None
    if apply and is_prod and not confirm_prod:
        raise ConfirmationRequired(
            "Refusing --apply against a live database pool without --confirm-prod. "
            "Take a backup and re-run with both flags — see "
            "docs/runbooks/GOLD-TENANT-BACKFILL.md."
        )

    target_domains = list(domains) if domains else discover_gold_domains()
    domain_reports: list[dict[str, Any]] = []
    for domain in target_domains:
        repo = GoldRepository(domain=domain)
        rows = await _scan_all(repo, page_size=batch_size, row_limit=limit)
        plan = _plan_table(repo.table_name, rows)
        if apply:
            await _apply_table(repo, plan)
        report = _report_for(plan)
        domain_reports.append(report)
        logger.info(
            "gold_tenant_backfill domain=%s scanned=%d rekeyed=%d collisions=%d skipped=%d",
            repo.table_name, report["scanned"], report["rekeyed"],
            report["collisions"], report["skipped"],
        )

    return {
        "mode": "apply" if apply else "dry_run",
        "pool": "postgres" if is_prod else "in_memory",
        "generated_at": utc_now().isoformat(),
        "domains": domain_reports,
        "totals": _sum_totals(domain_reports),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def _print_human(report: dict[str, Any]) -> None:
    totals = report["totals"]
    print(f"Gold tenant backfill -- mode={report['mode']} pool={report['pool']} "
          f"generated_at={report['generated_at']}")
    print(f"  TOTAL scanned={totals['scanned']} rekeyed={totals['rekeyed']} "
          f"collisions={totals['collisions']} (rows left in place={totals['collision_rows_dropped']}) "
          f"skipped={totals['skipped']}")
    for d in report["domains"]:
        if d["scanned"] == 0:
            continue
        print(f"  [{d['table']}] scanned={d['scanned']} rekeyed={d['rekeyed']} "
              f"collisions={d['collisions']} skipped={d['skipped']}")
        for c in d["collision_detail"]:
            loser_desc = ", ".join(
                f"{l['id']} (tenant={l['tenant_id']!r} updated_at={l['updated_at']})"
                for l in c["losers"]
            )
            print(f"    COLLISION at {c['canonical_id']}: kept {c['winner']['id']} "
                  f"(updated_at={c['winner']['updated_at']}); left untouched: {loser_desc}")
    if report["mode"] == "dry_run":
        print("  DRY RUN -- nothing was written. Re-run with --apply to perform the rekey.")
    elif totals["collisions"]:
        print("  ACTION NEEDED -- unresolved collisions were left in place; review and see "
              "docs/runbooks/GOLD-TENANT-BACKFILL.md.")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--domain", action="append", default=None, metavar="NAME",
        help="Restrict to this Gold domain (repeatable). Default: every domain "
             "discover_gold_domains() finds.",
    )
    p.add_argument("--apply", action="store_true", help="Perform the rekey. Default is dry-run.")
    p.add_argument(
        "--confirm-prod", action="store_true",
        help="Required together with --apply when a live database pool is detected.",
    )
    p.add_argument("--batch-size", type=int, default=DEFAULT_PAGE_SIZE, metavar="N",
                    help=f"Read page size (default {DEFAULT_PAGE_SIZE}).")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                    help="Max rows scanned per domain (default: unlimited).")
    p.add_argument("--json", action="store_true", help="Emit the report as JSON on stdout.")
    return p


def main() -> int:
    args = _parser().parse_args()
    try:
        report = asyncio.run(run_backfill(
            domains=args.domain,
            apply=args.apply,
            confirm_prod=args.confirm_prod,
            batch_size=args.batch_size,
            limit=args.limit,
        ))
    except ConfirmationRequired as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        _print_human(report)

    return 2 if report["totals"]["collisions"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
