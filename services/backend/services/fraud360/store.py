"""FraudHypothesis persistence — tenant-scoped BaseRepository JSONB pattern.

Hypotheses are stored as tenant-scoped JSONB records (table
``fraud_hypotheses``, auto-created by ``BaseRepository``; in-memory when
``AETHER_ENV=local``). Record ids are tenant-qualified (``{tenant_id}:
{hypothesis_id}``) and every read re-checks the tenant before returning a row.
NO alembic migration — ``BaseRepository`` owns the schema (the convention PR 1
established for new stores; mirrored from ``services/intelligence/comparison/store.py``).

FraudHypothesis **runs** are NOT stored here — they live on the canonical
``computation_runs`` substrate (``new_run_id()`` / ``context_hash``); this
store persists only hypothesis records.
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository

from services.fraud360.contracts import (
    EpistemicStatus,
    FraudHypothesis,
    FraudHypothesisState,
    FraudHypothesisStateMachine,
)


class FraudHypothesisRepository(BaseRepository):
    """Tenant-qualified JSONB store for ``FraudHypothesis`` records."""

    #: Key inside the payload that holds the natural (caller-visible) id.
    natural_id_key: str = "hypothesis_id"

    def __init__(self) -> None:
        super().__init__("fraud_hypotheses")

    @staticmethod
    def _record_id(tenant_id: str, hypothesis_id: str) -> str:
        return f"{tenant_id}:{hypothesis_id}"

    @staticmethod
    def _to_payload(hypothesis: FraudHypothesis) -> dict[str, Any]:
        # mode="json" renders nested canonical models (EvidenceRef,
        # GraphSnapshotRef, MonetaryAmount) as plain JSON-friendly primitives.
        return hypothesis.model_dump(mode="json")

    @staticmethod
    def _public_record(record: dict[str, Any]) -> dict[str, Any]:
        """Drop the tenant-qualified repo ``id`` (the envelope ``created_at`` /
        ``updated_at`` are retained — the FraudHypothesis contract carries them).
        """
        return {k: v for k, v in record.items() if k != "id"}

    @classmethod
    def _to_hypothesis(cls, record: dict[str, Any]) -> FraudHypothesis:
        return FraudHypothesis.model_validate(cls._public_record(record))

    async def create(self, tenant_id: str, hypothesis: FraudHypothesis) -> FraudHypothesis:
        """Persist a hypothesis under ``tenant_id`` and return the stored record."""
        if hypothesis.tenant_id != tenant_id:
            raise ValueError(
                f"FraudHypothesis tenant_id {hypothesis.tenant_id!r} does not match "
                f"repository scope {tenant_id!r}"
            )
        stored = await self.insert(
            self._record_id(tenant_id, hypothesis.hypothesis_id),
            self._to_payload(hypothesis),
        )
        return self._to_hypothesis(stored)

    async def get(self, tenant_id: str, hypothesis_id: str) -> Optional[FraudHypothesis]:
        """Fetch one tenant-scoped hypothesis, or None (missing / other tenant)."""
        record = await self.find_by_id(self._record_id(tenant_id, hypothesis_id))
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return self._to_hypothesis(record)

    async def list(
        self,
        tenant_id: str,
        *,
        state: Optional[FraudHypothesisState | str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FraudHypothesis]:
        """List hypotheses scoped to ``tenant_id``, optionally filtered by state."""
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if state is not None:
            filters["state"] = FraudHypothesisState(state).value
        rows = await self.find_many(filters=filters, limit=limit, offset=offset)
        return [self._to_hypothesis(r) for r in rows]

    async def update_state(
        self,
        tenant_id: str,
        hypothesis_id: str,
        new_state: FraudHypothesisState | str,
        *,
        claim_state: Optional[EpistemicStatus | str] = None,
        evidence_refs: Optional[list] = None,
    ) -> Optional[FraudHypothesis]:
        """Transition a stored hypothesis through the legal state machine.

        Enforces :class:`FraudHypothesisStateMachine` at the storage boundary:
        ``confirmed`` requires a factual ``claim_state``, ``rejected`` requires
        ``evidence_refs``. Returns the updated record, or None when the
        hypothesis is missing or belongs to another tenant.
        """
        existing = await self.get(tenant_id, hypothesis_id)
        if existing is None:
            return None

        target = FraudHypothesisState(new_state)
        resolved_claim = (
            EpistemicStatus(claim_state)
            if claim_state is not None
            else existing.claim_state
        )
        FraudHypothesisStateMachine.transition(
            existing.state,
            target,
            evidence_refs=evidence_refs,
            claim_state=resolved_claim,
        )

        patch: dict[str, Any] = {"state": target.value}
        if claim_state is not None:
            patch["claim_state"] = resolved_claim.value
        stored = await self.update(self._record_id(tenant_id, hypothesis_id), patch)
        return self._to_hypothesis(stored)


__all__ = ["FraudHypothesisRepository"]
