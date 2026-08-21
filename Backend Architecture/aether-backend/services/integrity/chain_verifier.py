"""LEDGER M3 -- scheduled Bronze truth-chain verifier + security-alert wiring.

Reliability Phase-2, Program 1 ("Truth-chain ledger"), M3
(``docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md``).

M2 gave every ``bronze_sdk_events`` row a per-tenant SHA-256 hash chain
(``prev_hash`` / ``integrity_hash``), written inside ``ingest_many``
(``services/ingestion/bronze_bulk.py``). This module is the *reader* half:

  * :func:`verify_tenant_chain` loads one tenant's chained Bronze rows in the
    exact append order M2 wrote them and re-walks them with the shared
    ``shared/integrity/hash_chain.verify_chain`` primitive -- the same primitive
    ``AuditLedger`` uses -- returning a structured
    :class:`ChainVerifierResult` (verified?, rows scanned, first break location,
    all broken record ids).
  * :func:`run_verification_pass` sweeps every tenant that has a chain, records
    each tenant's latest status for the dashboard, and on a FAILURE emits a
    ``P1`` alert through the EXISTING operator/security alert path
    (``services/agent/ops_alerts.record_alert`` -- compression + notification
    routing), never a new channel.
  * :func:`get_verification_dashboard` aggregates the recorded statuses into the
    "tenants currently verified" / "verification failures" view the
    ``/v1/security/ledger/chain-verification`` endpoint serves.
  * :func:`build_chain_verifier_coro` is the periodic worker coroutine, wired
    into the supervised worker registry in ``services/runtime/specs.py`` exactly
    like the other ``build_*_coro`` loops (gated OFF by default via
    ``LEDGER_CHAIN_VERIFIER_ENABLED``).

Chain shape is owned by M2. To re-derive a row's hash byte-for-byte, this module
must reproduce M2's canonical fields / partition key / append order exactly --
so it imports them straight from ``bronze_bulk`` when that (M2) module exposes
them, and otherwise falls back to a faithful local mirror (kept identical to
``bronze_bulk._canonical_fields`` / ``_chain_partition`` / ``_chain_sort_key``).
The verifier never mutates Bronze; it only reads.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from shared.common.common import utc_now
from shared.integrity import hash_chain
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.integrity.chain_verifier")

_BRONZE_TABLE = "bronze_sdk_events"
# Durable store of the last verification status per tenant (dashboard source).
_STATUS_STORE = "ledger_chain_verification"

# Env gating / cadence (repo convention: os.getenv flags, cf. retention_worker
# and ops_alerts). Default OFF -- this is an opt-in safety-net worker.
_ENABLED_ENV = "LEDGER_CHAIN_VERIFIER_ENABLED"
_INTERVAL_ENV = "LEDGER_CHAIN_VERIFIER_INTERVAL_SECONDS"
_DEFAULT_INTERVAL_SECONDS = 6 * 3600
_MIN_INTERVAL_SECONDS = 60

# A broken tamper-evidence chain is a serious integrity signal but not an outage.
_ALERT_SEVERITY = "P1"
_ALERT_KIND = "ledger_chain_integrity"

# Reserved row key: the authoritative typed Bronze columns, carried alongside the
# duplicated ``data`` envelope so the verifier can cross-check them (N6). Never a
# canonical (hashed) field, so it never affects hash re-derivation.
_TYPED_SIDECAR = "__typed_columns__"

# Typed columns whose text values must be byte-identical to the ``data`` envelope.
# These are the real Bronze surfaces the chain protects (the envelope is a
# duplicate the hash is derived from); a typed column edited without the envelope
# (or vice versa) is tamper even when the envelope-derived hash still checks.
_TYPED_TEXT_COLUMNS = (
    "tenant_id",
    "event_id",
    "schema_version",
    "event_type",
    "payload_hash",
    "integrity_hash",
    "prev_hash",
)

# Synthetic break markers (not real record ids) for the non-hash failure modes.
_VANISHED_MARKER = "chain_vanished"       # every chained row for a tenant deleted
_ERROR_MARKER = "verifier_error"          # verification raised for this tenant
_REGRESSION_MARKER = "chain_regressed"    # append-only chain lost rows since last run


# ── Canonical chain shape (mirrors services/ingestion/bronze_bulk.py, M2) ─────
# verify_chain re-hashes each row and compares to its stored integrity_hash, so
# these MUST match M2 exactly or an intact chain would be reported broken. When
# the M2 ingestion module exposes its helpers (the integrated tree), they are the
# single source of truth and are used directly -- zero drift. In a pre-M2 tree the
# from-import raises ImportError and the local mirror (identical to M2) is used.
try:  # pragma: no cover - branch depends on whether M2 has landed in this tree
    from services.ingestion.bronze_bulk import (  # type: ignore
        _canonical_fields as _bronze_canonical_fields,
        _chain_partition as _bronze_chain_partition,
        _chain_sort_key as _bronze_chain_sort_key,
    )
    _CHAIN_HELPERS_SOURCE = "bronze_bulk"
except (ImportError, AttributeError):  # pre-M2 worktree -- faithful local mirror

    def _bronze_canonical_fields(row: dict) -> dict:
        """The stable, tamper-evident identity of one Bronze event to hash.

        Mirrors ``bronze_bulk._canonical_fields``: only fields immutable for a
        given event participate (identity key + occurrence time + type + a stable
        payload digest). Volatile ingest metadata (received_at/batch_id/id/
        created_at) is excluded; ``prev_hash`` is folded in by the primitive.
        """
        return {
            "event_id": row.get("event_id"),
            "tenant_id": row.get("tenant_id"),
            "schema_version": row.get("schema_version"),
            "event_type": row.get("event_type"),
            "event_timestamp": row.get("event_timestamp"),
            "payload_hash": row.get("payload_hash"),
        }

    def _bronze_chain_partition(row: dict) -> str:
        """Independent-chain key for a Bronze row (per tenant)."""
        return row.get("tenant_id") or ""

    def _bronze_chain_sort_key(row: dict) -> tuple[str, str, str]:
        """Deterministic append order within a tenant's chain.

        ``created_at`` segregates/orders batches; the ``(event_id,
        schema_version)`` tail of the unique key totally orders one batch's rows.
        """
        return (
            row.get("created_at") or "",
            row.get("event_id") or "",
            row.get("schema_version") or "",
        )

    _CHAIN_HELPERS_SOURCE = "local_mirror"


# ── Structured result ─────────────────────────────────────────────────────────

@dataclass
class ChainVerifierResult:
    """Outcome of verifying one tenant's Bronze hash chain."""

    tenant_id: str
    verified: bool
    rows_scanned: int
    chains_verified: int
    broken_record_ids: list[str] = field(default_factory=list)
    break_location: Optional[str] = None
    checked_at: str = ""
    # N7 cross-run state: the current chain tail hash and the monotonic
    # high-watermark of rows ever seen. Bronze is append-only, so a later run
    # that shows fewer rows, or whose chain no longer contains the recorded tail,
    # has lost rows — tamper the survivors alone cannot reveal.
    tail_hash: Optional[str] = None
    max_rows_scanned: int = 0

    def to_status(self) -> dict[str, Any]:
        """Flat, JSON-safe status row (also the durable dashboard record)."""
        return {
            "id": self.tenant_id or "",  # store primary key
            "tenant_id": self.tenant_id,
            "verified": self.verified,
            "rows_scanned": self.rows_scanned,
            "chains_verified": self.chains_verified,
            "broken_record_ids": list(self.broken_record_ids),
            "break_location": self.break_location,
            "checked_at": self.checked_at,
            "tail_hash": self.tail_hash,
            "max_rows_scanned": self.max_rows_scanned,
        }


def _record_id(row: dict) -> str:
    """Human-readable break location: the event identity within the tenant chain."""
    return f"{row.get('event_id') or '?'}:{row.get('schema_version') or '?'}"


# ── Loading a tenant's chain (in-memory + Postgres) ───────────────────────────

async def _load_tenant_chain_rows(tenant_id: str) -> list[dict]:
    """Load one tenant's CHAINED Bronze rows (those with an integrity_hash).

    Reads the exact serialized form M2 hashed. In-memory (AETHER_ENV=local) the
    stored dicts ARE what the writer chained. On Postgres the ``data`` JSONB
    envelope is read for hash re-derivation -- its string fields are byte-identical
    to what was hashed at write time, whereas the typed ``timestamptz`` columns
    would re-serialize differently (asyncpg -> datetime) and break re-derivation.
    The AUTHORITATIVE typed columns (``event_type``, ``payload_hash``,
    ``integrity_hash``, ...) are loaded alongside and attached as a sidecar so the
    verifier can catch a typed column edited without the duplicated envelope, or
    vice versa (N6) -- those typed columns are the real Bronze surfaces the chain
    protects. Pre-cutover rows (NULL integrity_hash) are not chain anchors and are
    skipped, matching M2's own tail/anchor selection.
    """
    from repositories.repos import get_pool

    pool = await get_pool()
    if pool is None:
        from repositories.repos import _IN_MEMORY_STORES

        store = _IN_MEMORY_STORES.get(_BRONZE_TABLE, {})
        return [
            row
            for row in store.values()
            if (row.get("tenant_id") or "") == (tenant_id or "")
            and row.get("integrity_hash")
        ]

    records = await pool.fetch(
        "SELECT data, tenant_id, event_id, schema_version, event_type, "
        "payload_hash, event_timestamp, prev_hash, integrity_hash, created_at "
        "FROM bronze_sdk_events "
        "WHERE tenant_id = $1 AND integrity_hash IS NOT NULL",
        tenant_id,
    )
    return [_augment_pg_row(rec) for rec in records]


def _augment_pg_row(rec: Any) -> dict:
    """Build a verifiable row from a Postgres record.

    The ``data`` envelope (what M2 hashed) drives hash re-derivation; the
    authoritative typed columns ride along under ``_TYPED_SIDECAR`` for the N6
    cross-check. A corrupt envelope (NULL / scalar / array -- e.g. a ``data``
    column overwritten into a non-object) is reconstructed from the typed columns
    only enough to keep the row walking in the right partition/append order, so it
    is flagged broken (its missing envelope content fails both the hash and the
    typed cross-check) instead of raising or silently vanishing.
    """
    data = rec["data"]
    if isinstance(data, (str, bytes, bytearray)):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            data = None
    typed = {
        "tenant_id": rec["tenant_id"],
        "event_id": rec["event_id"],
        "schema_version": rec["schema_version"],
        "event_type": rec["event_type"],
        "payload_hash": rec["payload_hash"],
        "event_timestamp": rec["event_timestamp"],
        "prev_hash": rec["prev_hash"],
        "integrity_hash": rec["integrity_hash"],
    }
    if isinstance(data, dict):
        row = dict(data)
    else:
        row = {
            "tenant_id": rec["tenant_id"],
            "event_id": rec["event_id"],
            "schema_version": rec["schema_version"],
            "created_at": _iso(rec["created_at"]),
            "prev_hash": rec["prev_hash"],
            "integrity_hash": rec["integrity_hash"],
        }
    row[_TYPED_SIDECAR] = typed
    return row


def _iso(value: Any) -> Any:
    """``created_at`` as a sort-key-comparable string (datetime -> isoformat)."""
    return value.isoformat() if isinstance(value, datetime) else value


def _coerce_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _same_instant(typed_ts: Any, envelope_ts: Any) -> bool:
    """Instant-equality for ``event_timestamp`` across the typed (datetime) column
    and the envelope (ISO string).

    Tolerant by design: normal timestamptz<->ISO re-serialization must never read
    as tamper, so only a confidently-parseable, present-on-both-sides mismatch
    counts as divergence.
    """
    if typed_ts is None and envelope_ts is None:
        return True
    if typed_ts is None or envelope_ts is None:
        return False  # one side present, one absent -> divergence
    a, b = _coerce_dt(typed_ts), _coerce_dt(envelope_ts)
    if a is None or b is None:
        return True  # unparseable somewhere -> defer to text-column checks + hash
    if (a.tzinfo is None) != (b.tzinfo is None):
        return True  # naive vs aware -> don't manufacture a mismatch
    return a == b


def _typed_envelope_divergence(row: dict) -> bool:
    """True when a Postgres row's authoritative typed columns diverge from its
    duplicated ``data`` envelope (N6). Always False for in-memory rows, which have
    no sidecar because the stored dict is their only surface."""
    typed = row.get(_TYPED_SIDECAR)
    if not typed:
        return False
    for col in _TYPED_TEXT_COLUMNS:
        if typed.get(col) != row.get(col):
            return True
    return not _same_instant(typed.get("event_timestamp"), row.get("event_timestamp"))


def _backlink_breaks(ordered_rows: list[dict]) -> set[str]:
    """Record ids whose stored ``prev_hash`` backlink does not match the running
    predecessor hash (N15).

    ``verify_chain`` re-derives each row's hash from its own running predecessor
    but reads only ``integrity_hash``; it never checks the stored ``prev_hash``
    backlink. The writer stores ``prev_hash`` = the previous row's
    ``integrity_hash`` (None/"" at the head), so a rewritten backlink -- which
    leaves the exposed chain columns no longer forming the linkage they claim --
    must be caught here. Advancing on the stored ``integrity_hash`` mirrors the
    writer's linkage, so a lone tampered backlink is reported once, not cascaded.
    """
    prev_by_partition: dict[str, Optional[str]] = {}
    broken: set[str] = set()
    for row in ordered_rows:
        key = _bronze_chain_partition(row)
        running = prev_by_partition.get(key)  # None at the head (no predecessor)
        stored_prev = row.get("prev_hash")
        if (stored_prev or "") != (running or ""):
            broken.add(_record_id(row))
        prev_by_partition[key] = row.get("integrity_hash")
    return broken


async def list_tenants_with_chain() -> list[str]:
    """Distinct tenant ids that have at least one chained (integrity_hash) row."""
    from repositories.repos import get_pool

    pool = await get_pool()
    if pool is None:
        from repositories.repos import _IN_MEMORY_STORES

        store = _IN_MEMORY_STORES.get(_BRONZE_TABLE, {})
        return sorted(
            {
                (row.get("tenant_id") or "")
                for row in store.values()
                if row.get("integrity_hash")
            }
        )

    records = await pool.fetch(
        "SELECT DISTINCT tenant_id FROM bronze_sdk_events "
        "WHERE integrity_hash IS NOT NULL"
    )
    return sorted({(rec["tenant_id"] or "") for rec in records})


# ── The verifier ──────────────────────────────────────────────────────────────

async def verify_tenant_chain(tenant_id: str) -> ChainVerifierResult:
    """Load and verify one tenant's Bronze truth-chain (read-only; no writes).

    Delegates the walk/compare/advance mechanics to the shared primitive; this
    supplies only the Bronze-specific partition / append-order / canonical-field
    / stored-hash accessors (all mirrored from M2), then layers three checks the
    envelope-only hash walk cannot make on its own:

      * N6 -- the authoritative typed columns must match the duplicated envelope;
      * N15 -- each stored ``prev_hash`` backlink must match the running hash;
      * N7 -- the append-only chain must not have LOST rows versus the last
        recorded state (tail truncation / recorded-tail deletion). This one reads
        the prior recorded status (a read, not a write) to compare.
    """
    rows = await _load_tenant_chain_rows(tenant_id)
    result = hash_chain.verify_chain(
        rows,
        partition_key=_bronze_chain_partition,
        sort_key=_bronze_chain_sort_key,
        canonical_field_variants=lambda row: [_bronze_canonical_fields(row)],
        stored_hash=lambda row: row.get("integrity_hash"),
        record_id=_record_id,
    )
    ordered = sorted(rows, key=_bronze_chain_sort_key)
    hash_broken = set(result["broken_record_ids"])
    backlink_broken = _backlink_breaks(ordered)  # N15
    broken: list[str] = []
    for row in ordered:
        rid = _record_id(row)
        if rid in hash_broken or rid in backlink_broken or _typed_envelope_divergence(row):
            broken.append(rid)

    rows_scanned = result["records_checked"]
    tail_hash = ordered[-1].get("integrity_hash") if ordered else None

    # N7: append-only regression vs the previously recorded state.
    prior = await _prior_status(tenant_id)
    prior_max = _prior_max_rows(prior)
    regression = _regression_reason(prior, rows, rows_scanned)
    if regression and regression not in broken:
        broken.insert(0, regression)  # the headline break for the dashboard/alert

    return ChainVerifierResult(
        tenant_id=tenant_id,
        verified=not broken,
        rows_scanned=rows_scanned,
        chains_verified=result["chains_verified"],
        broken_record_ids=broken,
        break_location=broken[0] if broken else None,
        checked_at=utc_now().isoformat(),
        tail_hash=tail_hash,
        max_rows_scanned=max(rows_scanned, prior_max),
    )


async def _prior_status(tenant_id: str) -> Optional[dict]:
    """The last recorded verification status for a tenant, or None. Never raises."""
    try:
        return await get_store(_STATUS_STORE).get(tenant_id or "")
    except Exception:  # noqa: BLE001 - a missing/unreachable prior must not abort verify
        return None


def _prior_max_rows(prior: Optional[dict]) -> int:
    """The recorded append-only high-watermark (falls back to a pre-N7 record's
    plain ``rows_scanned`` so upgrades detect regressions immediately)."""
    if not prior:
        return 0
    try:
        return int(prior.get("max_rows_scanned") or prior.get("rows_scanned") or 0)
    except (TypeError, ValueError):
        return 0


def _regression_reason(
    prior: Optional[dict], rows: list[dict], rows_scanned: int
) -> Optional[str]:
    """A break marker when the chain regressed vs prior recorded state (N7).

    Bronze is append-only: a tenant's chained row set only ever grows. If the
    recorded row count shrank, or the previously recorded tail row is no longer
    present in the chain, rows were deleted or rewritten -- a truncation the
    internally-consistent survivors cannot reveal.
    """
    if not prior:
        return None
    prior_max = _prior_max_rows(prior)
    if rows_scanned < prior_max:
        return f"{_REGRESSION_MARKER}:rows_shrank:{rows_scanned}<{prior_max}"
    prior_tail = prior.get("tail_hash")
    if prior_tail:
        present = {r.get("integrity_hash") for r in rows}
        if prior_tail not in present:
            return f"{_REGRESSION_MARKER}:tail_missing:{str(prior_tail)[:12]}"
    return None


# ── Alert wiring (reuse the existing ops/security alert path) ──────────────────

async def _emit_chain_failure_alert(result: ChainVerifierResult) -> Optional[dict]:
    """Emit a chain-integrity failure through the EXISTING operator alert path.

    Reuses ``services/agent/ops_alerts.record_alert`` (the platform's alert
    compression + notification-routing seam) -- not a new channel. Same
    ``dedupe_key`` per tenant so a persistently-broken chain pages once, not once
    per sweep. Fail-open: the recorded status + metric are the durable signal, so
    a down alert path must never abort the sweep.
    """
    message = (
        f"Bronze truth-chain verification FAILED for tenant {result.tenant_id}: "
        f"{len(result.broken_record_ids)} broken record(s); "
        f"first break at {result.break_location}; "
        f"{result.rows_scanned} row(s) scanned"
    )
    try:
        from services.agent.ops_alerts import record_alert

        return await record_alert(
            tenant_id=result.tenant_id or "",
            severity=_ALERT_SEVERITY,
            kind=_ALERT_KIND,
            message=message,
            dedupe_key=f"ledger_chain_integrity:{result.tenant_id or 'global'}",
        )
    except Exception as exc:  # noqa: BLE001 - fail-open by design
        logger.error(
            "ledger chain-integrity alert emit failed (fail-open) tenant=%s error=%s",
            result.tenant_id,
            exc,
        )
        metrics.increment("ledger_chain_verifier_alert_error")
        return None


# ── Status persistence + per-tenant orchestration ─────────────────────────────

async def record_tenant_status(result: ChainVerifierResult) -> None:
    """Persist a tenant's latest verification status for the dashboard read."""
    await get_store(_STATUS_STORE).set(result.tenant_id or "", result.to_status())


async def verify_and_record(tenant_id: str) -> ChainVerifierResult:
    """Verify one tenant, record its status, and alert + metric on failure."""
    result = await verify_tenant_chain(tenant_id)
    await record_tenant_status(result)
    if result.verified:
        metrics.increment("ledger_chain_verifier_verified_total")
    else:
        metrics.increment("ledger_chain_verifier_failure_total")
        logger.error(
            "ledger chain BROKEN tenant=%s broken=%d first_break=%s scanned=%d",
            tenant_id,
            len(result.broken_record_ids),
            result.break_location,
            result.rows_scanned,
        )
        await _emit_chain_failure_alert(result)
    return result


async def _record_and_alert_failure(result: ChainVerifierResult) -> None:
    """Persist a failed result and route it through the metric + alert path.

    Used for the non-hash failure modes -- a verifier exception (N13) and a
    vanished chain (N7) -- so they surface exactly like an ordinary broken chain
    instead of leaving a stale-green (or missing) dashboard entry.
    """
    await record_tenant_status(result)
    metrics.increment("ledger_chain_verifier_failure_total")
    await _emit_chain_failure_alert(result)


async def _record_verifier_error(tenant_id: str, exc: Exception) -> None:
    """N13: a tenant whose verification RAISED must not stay green (or statusless).

    Record an explicit failed result -- carrying the prior high-watermark/tail so a
    later successful run still detects any regression across the error -- and alert.
    """
    prior = await _prior_status(tenant_id)
    marker = f"{_ERROR_MARKER}:{type(exc).__name__}"
    result = ChainVerifierResult(
        tenant_id=tenant_id,
        verified=False,
        rows_scanned=int((prior or {}).get("rows_scanned") or 0),
        chains_verified=0,
        broken_record_ids=[marker],
        break_location=marker,
        checked_at=utc_now().isoformat(),
        tail_hash=(prior or {}).get("tail_hash"),
        max_rows_scanned=_prior_max_rows(prior),
    )
    await _record_and_alert_failure(result)


async def _record_vanished_chain(prior: dict) -> None:
    """N7: a tenant whose ENTIRE chain was deleted disappears from
    ``list_tenants_with_chain()``; without this its old (often green) status would
    persist forever. Record it failed and alert."""
    result = ChainVerifierResult(
        tenant_id=prior.get("tenant_id") or "",
        verified=False,
        rows_scanned=0,
        chains_verified=0,
        broken_record_ids=[_VANISHED_MARKER],
        break_location=_VANISHED_MARKER,
        checked_at=utc_now().isoformat(),
        tail_hash=prior.get("tail_hash"),
        max_rows_scanned=_prior_max_rows(prior),  # keep the watermark so it stays failed
    )
    await _record_and_alert_failure(result)


async def run_verification_pass() -> dict[str, Any]:
    """One full sweep: verify every tenant with a chain; record + alert per tenant.

    Returns a summary of the sweep (also what the worker logs each cycle).
    """
    tenants = await list_tenants_with_chain()
    # Snapshot the previously recorded statuses BEFORE this pass records anything,
    # so vanished-chain reconciliation (N7) compares against last pass, not this one.
    prior_statuses = await _all_recorded_statuses()
    verified = 0
    failures: list[str] = []
    errored: list[str] = []
    for tenant_id in tenants:
        try:
            result = await verify_and_record(tenant_id)
        except Exception as exc:  # noqa: BLE001 - one tenant must not abort the sweep
            logger.error(
                "ledger chain verify errored tenant=%s error=%s", tenant_id, exc
            )
            metrics.increment("ledger_chain_verifier_pass_error")
            # N13: persist an explicit failed status + alert instead of skipping.
            try:
                await _record_verifier_error(tenant_id, exc)
            except Exception as rec_exc:  # noqa: BLE001 - recording must not abort the sweep
                logger.error(
                    "ledger chain error-status record failed tenant=%s error=%s",
                    tenant_id,
                    rec_exc,
                )
            errored.append(tenant_id)
            failures.append(tenant_id)
            continue
        if result.verified:
            verified += 1
        else:
            failures.append(tenant_id)

    # N7: a tenant that had a chain last time but is absent now had its whole chain
    # deleted. Flag it failed so a stale (green) dashboard status can't linger.
    current = set(tenants)
    vanished: list[str] = []
    for status in prior_statuses:
        tid = status.get("tenant_id") or ""
        if not tid or tid in current or tid in vanished:
            continue
        if _prior_max_rows(status) <= 0:
            continue  # never had a real chain (e.g. an error-only status) -> nothing lost
        try:
            await _record_vanished_chain(status)
        except Exception as exc:  # noqa: BLE001 - reconciliation must not abort the sweep
            logger.error(
                "ledger chain vanished-status record failed tenant=%s error=%s", tid, exc
            )
        vanished.append(tid)
        failures.append(tid)

    summary = {
        "tenants_checked": len(tenants),
        "verified": verified,
        "verification_failures": len(failures),
        "failed_tenants": failures,
        "errored_tenants": errored,
        "vanished_tenants": vanished,
        "ran_at": utc_now().isoformat(),
    }
    logger.info("ledger chain verification pass complete: %s", summary)
    return summary


async def _all_recorded_statuses() -> list[dict]:
    """Every recorded per-tenant status, or [] if the store is unreachable."""
    try:
        return await get_store(_STATUS_STORE).find()
    except Exception:  # noqa: BLE001 - a down status store must not abort the sweep
        return []


# ── Dashboard read ────────────────────────────────────────────────────────────

async def get_verification_dashboard() -> dict[str, Any]:
    """Aggregate the last-recorded per-tenant statuses into the dashboard view.

    Shape: ``verified`` / ``verification_failures`` counts (the two headline
    numbers the milestone names) plus the verified tenant ids and the detail of
    any failing tenants.
    """
    statuses = await get_store(_STATUS_STORE).find()
    verified = [s for s in statuses if s.get("verified")]
    failing = [s for s in statuses if not s.get("verified")]
    return {
        "verified": len(verified),
        "verification_failures": len(failing),
        "total_tenants": len(statuses),
        "verified_tenants": sorted(s.get("tenant_id") or "" for s in verified),
        "failing_tenants": [
            {
                "tenant_id": s.get("tenant_id"),
                "broken_record_ids": s.get("broken_record_ids", []),
                "break_location": s.get("break_location"),
                "rows_scanned": s.get("rows_scanned", 0),
                "checked_at": s.get("checked_at"),
            }
            for s in failing
        ],
    }


# ── Scheduled worker (services/runtime/specs.py wires this in) ─────────────────

def is_enabled() -> bool:
    """Canonical read of the worker's enable flag (default OFF)."""
    return os.getenv(_ENABLED_ENV, "0").strip().lower() in ("1", "true", "yes", "on")


def _interval_seconds() -> int:
    try:
        return max(_MIN_INTERVAL_SECONDS, int(os.getenv(_INTERVAL_ENV, "")))
    except (TypeError, ValueError):
        return _DEFAULT_INTERVAL_SECONDS


async def chain_verifier_loop(interval_seconds: Optional[int] = None) -> None:
    """Background loop: run a full verification pass on a fixed cadence."""
    interval = interval_seconds if interval_seconds is not None else _interval_seconds()
    logger.info(
        "ledger chain verifier worker started: interval=%ss chain_helpers=%s",
        interval,
        _CHAIN_HELPERS_SOURCE,
    )
    while True:
        try:
            await run_verification_pass()
        except Exception as exc:  # noqa: BLE001 - a bad cycle must not kill the loop
            logger.error("ledger chain verifier loop error: %s", exc)
            metrics.increment("ledger_chain_verifier_loop_error")
        await asyncio.sleep(interval)


async def build_chain_verifier_coro() -> None:
    """Factory entrypoint for the supervised worker registry (fresh coro per start)."""
    await chain_verifier_loop()
