"""Retention sweep for Kyber's short-lived operational tables.

The storage-plane lifecycle (``shared/storage/lifecycle.py``) resolves the
right *window* for ``retention_class: short_lived`` — but it can only reach two
kinds of data: descriptor-indexed externalized objects, and Bronze hot rows.
Kyber's four short-lived tables are neither. They are
``allow_object_externalization: false`` plain JSONB rows written through
:class:`repositories.repos.BaseRepository`, so the correct window was computed
and then nothing acted on it. Expired operator sessions, spent step-up grants
and abandoned single-use ceremony challenges accumulated forever.

This module is the missing executor. It is deliberately narrow:

* **The window comes from the policy registry, never from a constant here.**
  Every table is resolved through ``shared.storage.manager.policy_for`` (which
  fails closed on an unknown resource type) and a table is swept only when its
  policy says ``retention_class: short_lived`` and
  ``delete_behavior: hard_delete``. Re-deriving "7 days" locally would rebuild
  the exact bug this closes, one layer up.

* **Only terminal rows are deleted.** A live session is never swept because it
  is old; it is swept because it *ended* and then aged out. Session rows are
  fetched by terminal status, so a row in a live status is not even loaded, and
  the status is re-checked before the delete. :data:`TERMINAL_SESSION_STATUSES`
  and :data:`LIVE_SESSION_STATUSES` partition ``SessionStatus`` exactly, so a
  status added to the contract without being classified here fails the test
  rather than silently defaulting to "sweepable".

* **Evidence is never touched.** ``kyber_access_scopes``,
  ``kyber_access_decisions``, ``kyber_authentication_events`` and
  ``kyber_device_approval_events`` are ``retention_class: legal`` —
  security evidence must outlive the session that produced it. They are listed
  in :data:`KYBER_EVIDENCE_TABLES` for assertion purposes and the policy guard
  refuses them independently: a sweeper that deletes evidence is far worse than
  one that deletes nothing.

* **Legal holds block.** An active hold covering a resource type skips the
  whole table, matching the lifecycle's fail-closed treatment of holds.

Each run is bounded (:data:`DEFAULT_MAX_PER_TABLE` deletions per table) so a
large backlog drains over several runs instead of stalling the worker, and the
result reports ``more_remaining`` when it did not reach the end.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Coroutine, Optional, get_args

from repositories.repos import BaseRepository
from shared.logger.logger import get_logger, metrics
from shared.storage.manager import StoragePolicy, policy_for
from shared.temporal.clock import SYSTEM_CLOCK, Clock
from shared.temporal.instant import try_parse_instant

from .access.contracts import SessionStatus

logger = get_logger("aether.kyber.retention")

#: Session statuses that mean the session is over. Only these are sweepable.
TERMINAL_SESSION_STATUSES: frozenset[str] = frozenset({"revoked", "expired"})

#: Session statuses that mean the session may still be used. Never sweepable,
#: at any age. Together with the terminal set this covers ``SessionStatus``
#: exactly — see ``tests/security/test_kyber_retention_sweep.py``.
LIVE_SESSION_STATUSES: frozenset[str] = frozenset(
    {"active", "restricted", "risk_limited", "locked"}
)

#: ``retention_class: legal`` Kyber tables. Security evidence: an investigation
#: reads these long after every session that produced them is gone. This
#: sweeper must never delete from them, and the policy guard below enforces it
#: independently of this list.
KYBER_EVIDENCE_TABLES: tuple[str, ...] = (
    "kyber_device_approval_events",
    "kyber_access_scopes",
    "kyber_access_decisions",
    "kyber_authentication_events",
)

#: Retention class this sweeper is allowed to act on. Anything else is skipped.
SWEEPABLE_RETENTION_CLASS = "short_lived"

#: Delete behavior this sweeper is allowed to act on.
SWEEPABLE_DELETE_BEHAVIOR = "hard_delete"

#: Deletions per table per run. A backlog drains across runs.
DEFAULT_MAX_PER_TABLE = 1000

#: Page size for the legal-hold scan (mirrors the lifecycle's paging).
_HOLD_PAGE_SIZE = 500

_DEFAULT_INTERVAL_SECONDS = 3600
_MIN_INTERVAL_SECONDS = 60


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class TableRule:
    """How one short-lived table decides that a row is terminal and aged.

    The rule carries no window of its own — the window is always resolved from
    the storage policy registry at sweep time and then divided by
    :attr:`window_divisor`.
    """

    #: Resource type / table name, as registered in config/storage_policies.yaml.
    resource_type: str
    #: Statuses that make a row terminal. When set, rows are fetched per status
    #: so a live row is never loaded, and the status is re-checked before delete.
    terminal_statuses: tuple[str, ...] = ()
    #: Fields whose mere presence makes a row terminal (consumed / revoked).
    terminal_marker_fields: tuple[str, ...] = ()
    #: Field holding an absolute expiry; a past expiry makes the row terminal.
    expiry_field: Optional[str] = None
    #: Fields, in priority order, that date the row for aging. The first one
    #: that parses wins. A row whose every candidate is missing or unparseable
    #: is left alone — an undatable row must not be deleted on a guess.
    age_fields: tuple[str, ...] = ()
    #: The policy window is divided by this to get the effective floor. Minutes-
    #: lived ceremony rows use a divisor rather than a second configuration
    #: knob, so the floor still moves when the policy window moves.
    window_divisor: int = 1
    #: Row field carrying the primary key when the bookkeeping ``id`` is absent.
    id_field: str = "id"


#: One rule per short-lived Kyber table. ``webhook_quarantine`` is also
#: ``short_lived`` but belongs to the delivery plane, not Kyber, so it is not
#: swept here.
SWEEP_RULES: tuple[TableRule, ...] = (
    # A workforce session is swept because it ENDED and then aged out.
    TableRule(
        resource_type="kyber_workforce_sessions",
        terminal_statuses=("revoked", "expired"),
        age_fields=("revoked_at", "updated_at", "created_at"),
    ),
    # An elevation is terminal once consumed, revoked, or past its absolute
    # expiry — it is never extended, so a past expiry is final.
    TableRule(
        resource_type="kyber_step_up_grants",
        terminal_marker_fields=("consumed_at", "revoked_at"),
        expiry_field="expires_at",
        age_fields=("consumed_at", "revoked_at", "expires_at", "updated_at", "created_at"),
        id_field="grant_id",
    ),
    # Single-use ceremony challenges. Consuming one normally deletes the row
    # outright; what survives is the abandoned ceremony, which ages out on a
    # floor derived from the policy window (one hour per week of window).
    TableRule(
        resource_type="kyber_webauthn_challenges",
        terminal_marker_fields=("consumed_at",),
        expiry_field="expires_at",
        age_fields=("consumed_at", "expires_at", "updated_at", "created_at"),
        window_divisor=168,
        id_field="challenge_id",
    ),
    TableRule(
        resource_type="kyber_device_proof_challenges",
        terminal_marker_fields=("consumed_at",),
        expiry_field="expires_at",
        age_fields=("consumed_at", "expires_at", "updated_at", "created_at"),
        window_divisor=168,
        id_field="challenge_id",
    ),
)

#: Resource types this sweeper will consider. Anything absent is untouched.
SWEPT_RESOURCE_TYPES: tuple[str, ...] = tuple(r.resource_type for r in SWEEP_RULES)

_RULES_BY_TYPE: dict[str, TableRule] = {r.resource_type: r for r in SWEEP_RULES}


class _TableRepository(BaseRepository):
    """Concrete JSONB view over one table, for read + delete only."""

    def __init__(self, table_name: str) -> None:
        super().__init__(table_name)


def _parse(value: Any) -> Optional[datetime]:
    """Parse a stored ISO timestamp, or ``None`` when it is unusable.

    Unparseable never means "old enough to delete": callers treat ``None`` as
    "cannot date this row" and leave the row alone.
    """
    if not isinstance(value, str) or not value:
        return None
    instant, _reason = try_parse_instant(value)
    return instant


class KyberRetentionSweeper:
    """Deletes terminal, aged-out rows from Kyber's short-lived tables."""

    def __init__(
        self,
        *,
        clock: Clock = SYSTEM_CLOCK,
        policies_path: Optional[Path] = None,
        short_lived_days: Optional[int] = None,
        max_per_table: int = DEFAULT_MAX_PER_TABLE,
        hold_repo: Optional[Any] = None,
        audit_enabled: bool = True,
    ) -> None:
        self._clock = clock
        self._policies_path = policies_path
        self._short_lived_days = short_lived_days
        self._max_per_table = max(1, int(max_per_table))
        self._hold_repo = hold_repo
        self._audit_enabled = audit_enabled
        self._repos: dict[str, _TableRepository] = {}

    # ── Test / deployment seams ──────────────────────────────────────────────

    @property
    def clock(self) -> Clock:
        return self._clock

    def set_clock(self, clock: Clock) -> None:
        """Swap the clock. Tests use this instead of sleeping."""
        self._clock = clock

    @property
    def max_per_table(self) -> int:
        return self._max_per_table

    def _now(self) -> datetime:
        return self._clock.now()

    def repo(self, resource_type: str) -> _TableRepository:
        """The (cached) repository for one table."""
        repo = self._repos.get(resource_type)
        if repo is None:
            repo = _TableRepository(resource_type)
            self._repos[resource_type] = repo
        return repo

    @property
    def hold_repo(self) -> Any:
        if self._hold_repo is None:
            from repositories.repos import StorageLegalHoldRepository  # lazy

            self._hold_repo = StorageLegalHoldRepository()
        return self._hold_repo

    # ── Window resolution (registry-driven, never a local constant) ──────────

    def policy(self, resource_type: str) -> StoragePolicy:
        """Resolve a table's storage policy. Unknown types fail closed."""
        return policy_for(resource_type, self._policies_path)

    def short_lived_days(self) -> int:
        """The ``short_lived`` window, from the same setting the lifecycle uses."""
        if self._short_lived_days is not None:
            return int(self._short_lived_days)
        from config.settings import settings  # lazy — avoids import cycles

        return int(settings.storage_plane.retention_short_lived_days)

    def window_for(self, rule: TableRule) -> timedelta:
        """Effective retention window for one table, derived from the policy."""
        window = timedelta(days=max(0, self.short_lived_days()))
        divisor = max(1, int(rule.window_divisor))
        return window / divisor

    # ── Terminal / aged predicates ───────────────────────────────────────────

    @staticmethod
    def is_terminal(rule: TableRule, row: dict[str, Any], now: datetime) -> bool:
        """True when the row represents finished state, not live state."""
        if rule.terminal_statuses:
            status = str(row.get("status") or "")
            if status in LIVE_SESSION_STATUSES:
                return False
            return status in rule.terminal_statuses

        for field in rule.terminal_marker_fields:
            if row.get(field):
                return True

        if rule.expiry_field:
            expires_at = _parse(row.get(rule.expiry_field))
            if expires_at is not None and expires_at <= now:
                return True

        return False

    @staticmethod
    def aged_out(rule: TableRule, row: dict[str, Any], cutoff: datetime) -> bool:
        """True when the row's terminal moment is older than the cutoff."""
        for field in rule.age_fields:
            stamped = _parse(row.get(field))
            if stamped is not None:
                return stamped <= cutoff
        # No usable timestamp: never guess an age on a destructive path.
        return False

    # ── Legal holds ──────────────────────────────────────────────────────────

    async def active_hold(self, resource_type: str) -> Optional[dict[str, Any]]:
        """First active legal hold covering ``resource_type``, across tenants.

        Kyber's operational rows are workforce state and carry no tenant, so a
        tenant-scoped lookup would miss holds entirely. Any active hold whose
        ``resource_type`` matches (or is unscoped) blocks the whole table.
        """
        offset = 0
        while True:
            holds = await self.hold_repo.find_many(
                filters={"status": "active"}, limit=_HOLD_PAGE_SIZE, offset=offset
            )
            for hold in holds:
                hold_type = hold.get("resource_type") or ""
                if not hold_type or hold_type == resource_type:
                    return hold
            if len(holds) < _HOLD_PAGE_SIZE:
                return None
            offset += _HOLD_PAGE_SIZE

    # ── Sweeps ───────────────────────────────────────────────────────────────

    async def sweep_table(
        self, resource_type: str, *, now: Optional[datetime] = None
    ) -> dict[str, Any]:
        """Sweep one table. Returns what it did and whether more rows remain."""
        moment = now or self._now()
        rule = _RULES_BY_TYPE.get(resource_type)
        if rule is None:
            return {
                "resource_type": resource_type,
                "status": "skipped",
                "reason": "not_a_swept_resource_type",
                "scanned": 0,
                "deleted": 0,
                "more_remaining": False,
            }

        # Fail closed on an unknown type, then refuse anything the registry
        # does not class as short-lived hard-delete state. This is the guard
        # that keeps evidence safe even if a rule is added by mistake.
        policy = self.policy(resource_type)
        if (
            policy.retention_class != SWEEPABLE_RETENTION_CLASS
            or policy.delete_behavior != SWEEPABLE_DELETE_BEHAVIOR
        ):
            logger.warning(
                f"kyber retention: refusing {resource_type} "
                f"(retention_class={policy.retention_class}, "
                f"delete_behavior={policy.delete_behavior})"
            )
            return {
                "resource_type": resource_type,
                "status": "skipped",
                "reason": "policy_not_sweepable",
                "retention_class": policy.retention_class,
                "delete_behavior": policy.delete_behavior,
                "scanned": 0,
                "deleted": 0,
                "more_remaining": False,
            }

        hold = await self.active_hold(resource_type)
        if hold is not None:
            metrics.increment(
                "kyber_retention_legal_hold_blocked_total",
                labels={"resource_type": resource_type},
            )
            return {
                "resource_type": resource_type,
                "status": "skipped",
                "reason": "legal_hold_active",
                "hold_id": hold.get("hold_id"),
                "retention_class": policy.retention_class,
                "scanned": 0,
                "deleted": 0,
                "more_remaining": True,
            }

        window = self.window_for(rule)
        cutoff = moment - window
        repo = self.repo(resource_type)
        limit = self._max_per_table

        # Session rows are fetched per terminal status so a live session is
        # never even loaded into the sweeper.
        filter_sets: list[dict[str, Any]] = (
            [{"status": status} for status in rule.terminal_statuses]
            if rule.terminal_statuses
            else [{}]
        )

        scanned = 0
        deleted = 0
        more_remaining = False

        for filters in filter_sets:
            if deleted >= limit:
                more_remaining = True
                break
            rows = await repo.find_many(filters, limit=limit, sort_by="created_at",
                                        sort_order="asc")
            scanned += len(rows)
            if len(rows) >= limit:
                more_remaining = True
            for row in rows:
                if deleted >= limit:
                    more_remaining = True
                    break
                if not self.is_terminal(rule, row, moment):
                    continue
                if not self.aged_out(rule, row, cutoff):
                    continue
                record_id = str(row.get("id") or row.get(rule.id_field) or "")
                if not record_id:
                    continue
                if await repo.delete(record_id):
                    deleted += 1
                    metrics.increment(
                        "kyber_retention_swept_total",
                        labels={"resource_type": resource_type},
                    )

        if deleted:
            logger.info(
                f"kyber retention: swept {deleted} row(s) from {resource_type} "
                f"older than {cutoff.isoformat()}"
            )

        return {
            "resource_type": resource_type,
            "status": "swept",
            "retention_class": policy.retention_class,
            "window_seconds": window.total_seconds(),
            "cutoff": cutoff.isoformat(),
            "scanned": scanned,
            "deleted": deleted,
            "more_remaining": more_remaining,
        }

    async def sweep(self, *, now: Optional[datetime] = None) -> dict[str, Any]:
        """Sweep every short-lived Kyber table and audit the run once."""
        moment = now or self._now()
        tables: dict[str, Any] = {}
        deleted_total = 0
        more_remaining = False
        errors: list[str] = []

        for rule in SWEEP_RULES:
            try:
                result = await self.sweep_table(rule.resource_type, now=moment)
            except Exception as exc:  # noqa: BLE001 - one table must not stop the rest
                logger.error(f"kyber retention: {rule.resource_type} sweep failed: {exc}")
                metrics.increment(
                    "kyber_retention_error_total",
                    labels={"resource_type": rule.resource_type},
                )
                errors.append(f"{rule.resource_type}: {exc}")
                tables[rule.resource_type] = {
                    "resource_type": rule.resource_type,
                    "status": "error",
                    "reason": str(exc),
                    "scanned": 0,
                    "deleted": 0,
                    "more_remaining": True,
                }
                more_remaining = True
                continue
            tables[rule.resource_type] = result
            deleted_total += int(result.get("deleted", 0))
            more_remaining = more_remaining or bool(result.get("more_remaining"))

        summary: dict[str, Any] = {
            "swept_at": moment.isoformat(),
            "short_lived_days": self.short_lived_days(),
            "max_per_table": self._max_per_table,
            "deleted_total": deleted_total,
            "more_remaining": more_remaining,
            "tables": tables,
            "protected_resource_types": list(KYBER_EVIDENCE_TABLES),
            "errors": errors,
        }
        await self._audit(summary)
        return summary

    async def _audit(self, summary: dict[str, Any]) -> None:
        """One summary audit record per run, through the shared ledger."""
        if not self._audit_enabled:
            return
        try:
            from services.security.audit_ledger import audit_ledger
        except ImportError as exc:  # pragma: no cover - ledger always present
            logger.warning(f"kyber retention: audit ledger unavailable: {exc}")
            return
        try:
            await audit_ledger.record(
                actor_id="system",
                actor_type="system",
                event_type="kyber.retention.swept",
                resource_type="kyber_retention",
                action="sweep",
                outcome="allowed",
                metadata={
                    "swept_at": summary["swept_at"],
                    "short_lived_days": summary["short_lived_days"],
                    "deleted_total": summary["deleted_total"],
                    "more_remaining": summary["more_remaining"],
                    "deleted_by_resource_type": {
                        rt: result.get("deleted", 0) for rt, result in summary["tables"].items()
                    },
                    "protected_resource_types": summary["protected_resource_types"],
                    "errors": summary["errors"],
                },
            )
        except Exception as exc:  # noqa: BLE001 - never fail a sweep on audit
            logger.error(f"kyber retention: audit record failed: {exc}")


#: Process-wide sweeper.
kyber_retention_sweeper = KyberRetentionSweeper()


def interval_seconds() -> int:
    """How often the supervised worker sweeps."""
    return max(
        _MIN_INTERVAL_SECONDS,
        _env_int("KYBER_RETENTION_SWEEP_INTERVAL_S", _DEFAULT_INTERVAL_SECONDS),
    )


class KyberRetentionWorker:
    """Long-running sweep loop for the ``maintenance`` runtime role."""

    def __init__(self, sweeper: Optional[KyberRetentionSweeper] = None) -> None:
        self.sweeper = sweeper or kyber_retention_sweeper
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        logger.info("kyber retention sweep worker started")
        while self._running:
            try:
                await self.sweeper.sweep()
            except asyncio.CancelledError:  # pragma: no cover - shutdown path
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                logger.error(f"kyber retention sweep failed: {exc}")
                metrics.increment("kyber_retention_error_total")
            await asyncio.sleep(interval_seconds())

    def stop(self) -> None:  # pragma: no cover - shutdown path
        self._running = False


def build_kyber_retention_coro() -> Coroutine:
    """Zero-arg factory: a fresh supervised Kyber retention sweep coroutine.

    Same shape as ``services.kyber.identity.directory_sync``'s
    ``build_directory_sync_coro`` so the runtime supervisor registers it under
    the existing ``maintenance`` role without a special case.
    """
    return KyberRetentionWorker().run_forever()


#: Every ``SessionStatus`` literal, partitioned above into terminal vs live.
ALL_SESSION_STATUSES: frozenset[str] = frozenset(str(v) for v in get_args(SessionStatus))


__all__ = [
    "ALL_SESSION_STATUSES",
    "DEFAULT_MAX_PER_TABLE",
    "KYBER_EVIDENCE_TABLES",
    "KyberRetentionSweeper",
    "KyberRetentionWorker",
    "LIVE_SESSION_STATUSES",
    "SWEEP_RULES",
    "SWEPT_RESOURCE_TYPES",
    "TERMINAL_SESSION_STATUSES",
    "TableRule",
    "build_kyber_retention_coro",
    "interval_seconds",
    "kyber_retention_sweeper",
]
