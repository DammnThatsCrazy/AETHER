"""Durable, metadata-only payment-provider receipt lifecycle.

Every provider delivery (a verified webhook or a polled record) gets ONE durable
receipt that is the delivery ledger: it tracks the observation through every
processing stage and links it to the funding session, canonical event id(s), and
outbox record it produced. The receipt is the source of truth the scheduled
canonical-repair worker scans to find and re-drive incomplete deliveries.

Design:
- **Metadata only.** A receipt never stores plaintext credentials or raw
  sensitive provider payloads — only a sha256 body hash, classifications, ids,
  timestamps, and stage state.
- **Deterministic id.** ``receipt_id`` is a uuid5 over
  (tenant, provider, endpoint_id, provider_event_id | body_hash), so a provider
  retry, a webhook/polling overlap, or a repair all map to the SAME receipt —
  the ledger is idempotent.
- **Forward-only stage machine.** ``advance`` never moves a receipt backward
  (a stale re-observation cannot un-complete a delivery); terminal states are
  set explicitly.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.logger.logger import get_logger
from shared.store import get_store

from services.integrations.providers.payment_rails.models import new_id, utc_now_iso

logger = get_logger("aether.payment_rails.receipts")


class ReceiptStage:
    """Ordered processing stages of a provider delivery."""

    RECEIVED = "received"
    ENDPOINT_RESOLVED = "endpoint_resolved"
    SIGNATURE_VERIFIED = "signature_verified"
    PARSED = "parsed"
    NORMALIZED = "normalized"
    FUNDING_SESSION_PERSISTED = "funding_session_persisted"
    CANONICAL_EVENT_WRITTEN = "canonical_event_written"
    OUTBOX_ENQUEUED = "outbox_enqueued"
    OUTBOX_PUBLISHED = "outbox_published"
    CONSUMED_OR_PROJECTED = "consumed_or_projected"
    COMPLETED = "completed"


# Ordered progression — index is the stage rank used for forward-only advance.
STAGE_ORDER: tuple[str, ...] = (
    ReceiptStage.RECEIVED,
    ReceiptStage.ENDPOINT_RESOLVED,
    ReceiptStage.SIGNATURE_VERIFIED,
    ReceiptStage.PARSED,
    ReceiptStage.NORMALIZED,
    ReceiptStage.FUNDING_SESSION_PERSISTED,
    ReceiptStage.CANONICAL_EVENT_WRITTEN,
    ReceiptStage.OUTBOX_ENQUEUED,
    ReceiptStage.OUTBOX_PUBLISHED,
    ReceiptStage.CONSUMED_OR_PROJECTED,
    ReceiptStage.COMPLETED,
)
_STAGE_RANK = {stage: i for i, stage in enumerate(STAGE_ORDER)}


class ReceiptState:
    """Terminal / recoverable receipt states (orthogonal to the stage)."""

    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    RETRY_PENDING = "retry_pending"
    REPAIR_PENDING = "repair_pending"
    DEAD_LETTERED = "dead_lettered"


TERMINAL_STATES: frozenset[str] = frozenset(
    {ReceiptState.REJECTED, ReceiptState.QUARANTINED, ReceiptState.DEAD_LETTERED}
)

# Stages at which a receipt is considered fully delivered (no repair needed).
COMPLETE_STAGES: frozenset[str] = frozenset(
    {ReceiptStage.OUTBOX_PUBLISHED, ReceiptStage.CONSUMED_OR_PROJECTED, ReceiptStage.COMPLETED}
)

_RECEIPT_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://aether.dev/payment_rails/receipt"
)
_SEP = "\x1f"


def receipt_id(
    tenant_id: str, provider: str, endpoint_id: Optional[str],
    provider_event_id: Optional[str], body_hash: Optional[str],
) -> str:
    """Deterministic receipt id for one logical provider delivery.

    Identity is (tenant, provider, endpoint_id, provider_event_id | body_hash):
    a provider retry or webhook/polling overlap of the same observation resolves
    to the same receipt. Falls back to the body hash when the provider supplies
    no event id, so an unparseable/rejected delivery is still deduped.
    """
    discriminator = provider_event_id or body_hash or new_id()
    key = f"{tenant_id}{_SEP}{provider}{_SEP}{endpoint_id or ''}{_SEP}{discriminator}"
    return str(uuid.uuid5(_RECEIPT_NAMESPACE, key))


class ProviderReceiptRepository:
    """Durable, tenant-scoped provider-receipt ledger (metadata only)."""

    def __init__(self) -> None:
        self._store = get_store("payment_provider_receipts")

    @staticmethod
    def _key(tenant_id: str, rid: str) -> str:
        return f"{tenant_id}:{rid}"

    async def get(self, tenant_id: str, rid: str) -> Optional[dict]:
        return await self._store.get(self._key(tenant_id, rid))

    async def open(
        self,
        tenant_id: str,
        provider: str,
        *,
        provider_event_id: Optional[str] = None,
        body_hash: Optional[str] = None,
        environment: Optional[str] = None,
        endpoint_id: Optional[str] = None,
        source: str = "webhook",
        stage: str = ReceiptStage.RECEIVED,
        trace_id: Optional[str] = None,
    ) -> dict:
        """Create (or re-open) the deterministic receipt for a delivery.

        Idempotent on the deterministic receipt id: a repeat delivery increments
        the processing-attempt counter and stamps ``last_attempted_at`` without
        losing prior stage progress. Returns the current receipt record.
        """
        rid = receipt_id(tenant_id, provider, endpoint_id, provider_event_id, body_hash)
        key = self._key(tenant_id, rid)
        now = utc_now_iso()
        existing = await self._store.get(key)
        if existing is not None:
            existing["processing_attempts"] = int(existing.get("processing_attempts", 0)) + 1
            existing["last_attempted_at"] = now
            await self._store.set(key, existing)
            return existing
        record = {
            "receipt_id": rid,
            "id": rid,
            "tenant_id": tenant_id,
            "provider": provider,
            "endpoint_id": endpoint_id,
            "environment": environment,
            "provider_event_id": provider_event_id,
            "body_hash": body_hash,
            "source": source,
            "current_stage": stage,
            "verification_state": None,
            "rejection_reason": None,
            "funding_session_id": None,
            "canonical_event_ids": [],
            "outbox_record_id": None,
            "outbox_publication_state": None,
            "processing_attempts": 1,
            "repair_attempts": 0,
            "last_error_classification": None,
            "trace_id": trace_id or new_id(),
            "received_at": now,
            "first_attempted_at": now,
            "last_attempted_at": now,
            "completed_at": None,
            "repair_history": [],
        }
        await self._store.set(key, record)
        return record

    async def advance(
        self, tenant_id: str, rid: str, stage: str, **fields: Any
    ) -> Optional[dict]:
        """Move a receipt FORWARD to ``stage`` (never backward) and merge fields.

        A stale re-observation whose stage rank is not greater than the current
        one leaves ``current_stage`` untouched but still merges any new linkage
        fields (e.g. a late funding_session_id). Reaching a completion stage
        stamps ``completed_at``.
        """
        key = self._key(tenant_id, rid)
        record = await self._store.get(key)
        if record is None:
            return None
        cur_rank = _STAGE_RANK.get(record.get("current_stage"), -1)
        new_rank = _STAGE_RANK.get(stage, -1)
        if new_rank > cur_rank:
            record["current_stage"] = stage
        for field, value in fields.items():
            if field == "canonical_event_ids" and value:
                merged = list(dict.fromkeys([*record.get("canonical_event_ids", []), *value]))
                record["canonical_event_ids"] = merged
            elif value is not None:
                record[field] = value
        if record["current_stage"] in COMPLETE_STAGES and not record.get("completed_at"):
            record["completed_at"] = utc_now_iso()
        record["last_attempted_at"] = utc_now_iso()
        await self._store.set(key, record)
        return record

    async def mark_state(
        self, tenant_id: str, rid: str, state: str, *, reason: Optional[str] = None,
        error_classification: Optional[str] = None,
    ) -> Optional[dict]:
        """Set a terminal/recoverable state token on the receipt (rejected,
        quarantined, retry_pending, repair_pending, dead_lettered)."""
        key = self._key(tenant_id, rid)
        record = await self._store.get(key)
        if record is None:
            return None
        record["current_stage"] = state
        if reason is not None:
            record["rejection_reason"] = reason
        if error_classification is not None:
            record["last_error_classification"] = error_classification
        if state in (ReceiptState.REJECTED, ReceiptState.QUARANTINED):
            record["verification_state"] = "rejected"
        record["last_attempted_at"] = utc_now_iso()
        await self._store.set(key, record)
        return record

    async def open_terminal(
        self,
        tenant_id: str,
        provider: str,
        *,
        state: str,
        body_hash: Optional[str] = None,
        provider_event_id: Optional[str] = None,
        environment: Optional[str] = None,
        endpoint_id: Optional[str] = None,
        source: str = "webhook",
        reason: Optional[str] = None,
    ) -> dict:
        """Open a receipt for a delivery that is rejected/quarantined before it
        ever produces an event (a bad signature or oversized body). One durable
        record per rejected delivery, keyed by body hash."""
        record = await self.open(
            tenant_id, provider, provider_event_id=provider_event_id,
            body_hash=body_hash, environment=environment, endpoint_id=endpoint_id,
            source=source, stage=ReceiptStage.RECEIVED,
        )
        await self.mark_state(tenant_id, record["receipt_id"], state, reason=reason)
        record["current_stage"] = state
        return record

    async def record_repair(
        self, tenant_id: str, rid: str, *, outcome: str, detail: Optional[str] = None
    ) -> Optional[dict]:
        """Increment the repair counter and append a bounded repair-history entry."""
        key = self._key(tenant_id, rid)
        record = await self._store.get(key)
        if record is None:
            return None
        record["repair_attempts"] = int(record.get("repair_attempts", 0)) + 1
        history = list(record.get("repair_history", []))
        history.append({"at": utc_now_iso(), "outcome": outcome, "detail": detail})
        record["repair_history"] = history[-20:]  # bounded
        await self._store.set(key, record)
        return record

    async def list_for_tenant(
        self, tenant_id: str, provider: Optional[str] = None, *, limit: int = 200
    ) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if provider:
            filters["provider"] = provider
        records = await self._store.find(**filters)
        records.sort(key=lambda r: r.get("received_at") or "", reverse=True)
        return records[: max(1, min(limit, 1000))]

    async def list_all(self) -> list[dict]:
        """Cross-tenant listing — operator aggregates + repair worker only."""
        return await self._store.find()

    async def list_incomplete(self, *, limit: int = 500) -> list[dict]:
        """Receipts that have not reached a completion stage and are not in a
        hard-terminal state — the repair worker's work-list."""
        out = [
            r for r in await self._store.find()
            if r.get("current_stage") not in COMPLETE_STAGES
            and r.get("current_stage") not in TERMINAL_STATES
        ]
        out.sort(key=lambda r: r.get("received_at") or "")
        return out[: max(1, min(limit, 2000))]
