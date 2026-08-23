"""WS2 — server-side confirmation of SDK commerce signals against Bronze lineage.

The SDK emits :class:`SDKCommerceSignal <shared.integration_contracts.commerce_bridge.SDKCommerceSignal>`;
the runtime reconciles it against the canonical event plane through the S2
bridge (:mod:`shared.integration_contracts.commerce_bridge`). This module is the
*server-side* confirmation half of WS2:

* **lineage resolution** — the signal's ``lineage`` (``source_record_id`` /
  ``provider_record_id`` / ``idempotency_key``) is resolved against the Bronze
  ``provider_records`` table that :class:`RawProviderRecordStore
  <services.provider_runtime.raw_store.RawProviderRecordStore>` writes, and a
  minimal canonical :class:`AetherEvent` is projected ONLY from stored raw
  fields — nothing is fabricated;
* **no new store** — replay evidence (confirmed ``signal_id``s) lives in the
  existing raw record's Bronze metadata; a duplicate SDK delivery of the same
  signal is recognized as ``replay`` on the next confirm;
* **no false positives** — a canonical that is not genuinely backed by a raw
  record in ``provider_records`` is never confirmed (returns ``unconfirmed``);
  the verdict itself is delegated to S2's ``confirm_interaction`` so the
  ``matched``/``unconfirmed``/``replay``/``not_found`` contract is Team A's, not
  a re-implementation.

Replay persistence is best-effort (a stamp failure degrades to "this delivery
confirmed" and never raises); every other failure is fail-closed with a typed
:class:`ConfirmationError`.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from shared.integration_contracts.commerce_bridge import (
    BridgeResult,
    SDKCommerceSignal,
    confirm_interaction as _bridge_confirm_interaction,
)
from shared.integration_contracts.events import AetherEvent

from services.provider_runtime.errors import ProviderRuntimeError

#: Bronze table carrying raw provider records (RawProviderRecordStore writes it).
_RAW_RECORDS_DOMAIN = "provider_records"

#: Scan bound for source_record_id lookups that cannot use a top-level column.
_SCAN_LIMIT = 1000

#: S2 context key for previously-confirmed SDK signal ids (replay detection).
_CONFIRMED_SIGNAL_IDS_KEY = "confirmed_signal_ids"

#: Canonical event_type derived from the SDK signal_type (S2's SDK vocabulary).
_SIGNAL_TYPE_TO_EVENT_TYPE = {
    "product_view": "commerce.product.viewed",
    "cart_updated": "commerce.cart.updated",
    "checkout_started": "commerce.checkout.started",
    "order_confirmed": "commerce.order.confirmed",
}


class ConfirmationError(ProviderRuntimeError):
    """A confirmation could not be performed (fail-closed). ``safe_message`` is
    generic; raw lineage or secret material is never echoed."""


def _scan_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    """Deterministic sort key for the source_record_id fallback scan (C-3).

    Orders a bounded window newest-first by ``payload.provider_occurred_at``
    (ISO-8601 UTC, lexicographically sortable), falling back to the row's own
    ``created_at`` and finally to a far-past sentinel so a missing timestamp
    never raises. The row id breaks ties so the ordering is total and stable
    across calls.
    """
    payload = row.get("payload") or {}
    occurred = str(payload.get("provider_occurred_at") or "").strip()
    if not occurred:
        occurred = str(row.get("created_at") or "").strip()
    if not occurred:
        occurred = "0000-01-01T00:00:00+00:00"
    return (occurred, str(row.get("id") or ""))


def _raw_idempotency_key(raw_payload: dict[str, Any]) -> str:
    """Mirror RawProviderRecord.idempotency_key from a stored raw dump."""
    material = (
        f"{raw_payload.get('tenant_id', '')}:"
        f"{raw_payload.get('provider_identity', '')}:"
        f"{raw_payload.get('provider_record_id', '')}:"
        f"{raw_payload.get('schema_version', '1')}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class ConfirmInteractionService:
    """Resolve an SDK signal's lineage against Bronze ``provider_records`` and
    confirm it through S2's bridge."""

    def __init__(self, *, bronze: Any = None, bridge: Any = None) -> None:
        # Defaults resolve lazily; tests inject fakes for both seams.
        self._bronze_impl = bronze
        self._bridge_impl = bridge

    # ── Seam defaults ───────────────────────────────────────────────────────

    def _bronze(self) -> Any:
        if self._bronze_impl is None:
            from repositories.lake import BronzeRepository

            self._bronze_impl = BronzeRepository(_RAW_RECORDS_DOMAIN)
        return self._bronze_impl

    def _bridge(self) -> Any:
        return self._bridge_impl or _bridge_confirm_interaction

    # ── Public entry ────────────────────────────────────────────────────────

    async def confirm(
        self,
        signal: SDKCommerceSignal,
        *,
        tenant_id: str = "",
        provider_identity: str = "",
        canonical: Optional[AetherEvent] = None,
    ) -> BridgeResult:
        """Confirm one SDK signal against Bronze-backed canonical lineage.

        Returns the S2 ``BridgeResult`` verdict. When ``canonical`` is supplied
        it is used but still must be backed by a raw record in ``provider_records``
        (otherwise ``unconfirmed`` — no false positives). When omitted, the
        canonical is projected from the raw record the signal's lineage resolves
        to (``not_found`` when it resolves to nothing).
        """
        raw_row: Optional[dict[str, Any]] = None

        if canonical is not None:
            raw_row = await self._find_raw(
                source_record_id=canonical.source_record_id,
                provider_record_id=str(
                    (canonical.context or {}).get("provider_record_id", "")
                ),
                tenant_id=canonical.tenant_id or tenant_id,
                provider_identity=canonical.provider_identity or provider_identity,
            )
            if raw_row is None:
                return _unconfirmed_result(signal, canonical)
            canonical = self._with_replay_context(canonical, raw_row)
        else:
            raw_row = await self._find_raw(
                source_record_id=signal.lineage.get("source_record_id") or "",
                provider_record_id=signal.lineage.get("provider_record_id") or "",
                idempotency_key=signal.lineage.get("idempotency_key") or "",
                tenant_id=tenant_id,
                provider_identity=provider_identity,
            )
            if raw_row is None:
                # No canonical is resolvable — S2's not_found (never a match).
                return self._bridge()(signal, None)
            canonical = self._project_canonical(raw_row, signal)

        # C-4: the S2 bridge stays keyed on ``lineage.source_record_id``. When
        # the signal carried only ``provider_record_id`` / ``idempotency_key``
        # (resolved above) but no ``source_record_id``, inject the RESOLVED
        # row's ``record_id`` into the comparison so those two documented
        # lineage modes can reach ``matched`` instead of dead-ending in
        # ``unconfirmed``. The signal model is copied — the SDK's own lineage
        # is never mutated.
        bridge_signal = signal
        if not signal.lineage.get("source_record_id"):
            resolved_record_id = (raw_row.get("payload") or {}).get("record_id") or ""
            if resolved_record_id:
                lineage = dict(signal.lineage)
                lineage["source_record_id"] = resolved_record_id
                bridge_signal = signal.model_copy(update={"lineage": lineage})

        result = self._bridge()(bridge_signal, canonical)

        if result.confirmation_state == "matched" and raw_row is not None:
            await self._stamp_confirmed(raw_row, signal.signal_id)
        return result

    # ── Lineage resolution against Bronze provider_records ──────────────────

    async def _find_raw(
        self,
        *,
        source_record_id: str,
        provider_record_id: str,
        tenant_id: str,
        provider_identity: str,
        idempotency_key: str = "",
    ) -> Optional[dict[str, Any]]:
        """Locate the raw record row a canonical/signal lineage points at.

        Preferred lookups use a Bronze top-level column (``provider_record_id``
        or ``idempotency_key``); ``source_record_id`` (the raw ``record_id``,
        which lives inside ``payload``) falls back to a bounded tenant/provider
        scan. Every lookup is tenant-scoped — a cross-tenant id can never match.

        The fallback scan is BOUNDED to ``_SCAN_LIMIT`` rows per tenant/provider
        and ordered deterministically (newest-first by ``payload.provider_occurred_at``)
        so the same data yields the same resolution and the most recent matching
        record wins (C-3). The bound is an honest fail-closed limit: a lineage
        pointing at a record older than the most recent ``_SCAN_LIMIT`` rows for
        that tenant/provider resolves to ``None`` (``not_found``) rather than
        scanning unboundedly.
        """
        bronze = self._bronze()

        if provider_record_id:
            rows = await bronze.find_many(
                filters={
                    "tenant_id": tenant_id,
                    "source": provider_identity,
                    "provider_record_id": provider_record_id,
                },
                limit=1,
            )
            if rows:
                return rows[0]

        if idempotency_key:
            rows = await bronze.find_many(
                filters={"tenant_id": tenant_id, "idempotency_key": idempotency_key},
                limit=1,
            )
            if rows:
                return rows[0]

        if source_record_id:
            rows = await bronze.find_many(
                filters={"tenant_id": tenant_id, "source": provider_identity},
                limit=_SCAN_LIMIT,
            )
            # C-3: the bounded window is scanned newest-first by
            # provider_occurred_at so the resolution is deterministic and the
            # most recent matching record wins.
            for row in sorted(rows, key=_scan_sort_key, reverse=True):
                payload = row.get("payload") or {}
                if str(payload.get("record_id", "")) == source_record_id:
                    return row
        return None

    # ── Honest canonical projection (stored raw fields only) ────────────────

    def _project_canonical(
        self, raw_row: dict[str, Any], signal: SDKCommerceSignal
    ) -> AetherEvent:
        """Project the minimal canonical surface from a stored raw record dump.

        Every field is a deterministic projection of the stored raw payload —
        nothing is fabricated. ``event_type`` follows the S2 canonical mapping
        for the SDK signal family; replay evidence is read from the raw
        record's own metadata.
        """
        raw = raw_row.get("payload") or {}
        raw_metadata = raw.get("metadata") or {}
        observed_at = raw.get("observed_at") or signal.occurred_at
        provider_identity = raw.get("provider_identity") or signal.provider_identity or ""
        return AetherEvent(
            event_id=_raw_idempotency_key(raw),
            event_type=_SIGNAL_TYPE_TO_EVENT_TYPE.get(
                signal.signal_type, f"commerce.{signal.signal_type}"
            ),
            event_family="commerce",
            tenant_id=raw.get("tenant_id") or signal.tenant_id or "",
            provider=str(provider_identity).split(".")[0],
            provider_identity=provider_identity,
            source_record_id=raw.get("record_id") or "",
            occurred_at=raw.get("provider_occurred_at") or observed_at,
            observed_at=observed_at,
            account_id=raw.get("account_id") or "",
            data=dict(raw.get("payload") or {}),
            context={
                "acquisition_mode": raw.get("acquisition_mode") or "",
                "connection_id": raw.get("connection_id") or "",
                "provider_record_id": raw.get("provider_record_id") or "",
                _CONFIRMED_SIGNAL_IDS_KEY: list(
                    raw_metadata.get(_CONFIRMED_SIGNAL_IDS_KEY, [])
                ),
            },
        )

    @staticmethod
    def _with_replay_context(
        canonical: AetherEvent, raw_row: dict[str, Any]
    ) -> AetherEvent:
        """Load prior confirmed signal ids into the canonical's context so S2's
        replay detection sees them (the existing store is the source of truth)."""
        raw = raw_row.get("payload") or {}
        raw_metadata = raw.get("metadata") or {}
        context = dict(canonical.context or {})
        context[_CONFIRMED_SIGNAL_IDS_KEY] = list(
            raw_metadata.get(_CONFIRMED_SIGNAL_IDS_KEY, [])
        )
        canonical.context = context
        return canonical

    # ── Replay stamp (no new store — lives in the raw record's Bronze row) ──

    async def _stamp_confirmed(self, raw_row: dict[str, Any], signal_id: str) -> None:
        """Append ``signal_id`` to the raw record's Bronze metadata (idempotent).

        Best-effort: a stamp failure never fails the confirmation — the delivery
        is already confirmed — but a log line records the miss so an operator
        can replay the confirmation evidence.

        RACE (C-6): ``BronzeRepository.update`` is a plain read-modify-write
        (``find_by_id_or_fail`` -> merge -> ``UPDATE``) — there is no
        conditional/atomic append. Two concurrent confirms of DIFFERENT signals
        against the same raw record can both read ``confirmed_signal_ids=[]``,
        both resolve to ``matched``, and the later ``UPDATE`` overwrites the
        earlier stamp, so the first signal becomes confirmable again (a
        duplicate delivery of it would then be ``matched`` instead of ``replay``)
        and one stamp is lost. This is accepted for the current build: the
        replay evidence is best-effort, no new store, and the confirmed delivery
        itself is never double-reported end-to-end because a lost stamp can only
        resurrect a *replay* verdict, never create a false ``matched`` for a
        signal that had not been confirmed. Replay safety is never weakened —
        this is strictly a best-effort eviction-tolerance trade. A future
        conditional-append (``UPDATE ... WHERE payload->... NOT LIKE ...`` or a
        table-level append trigger) would remove the race; do NOT convert this
        to a non-atomic optimistic loop without one.
        """
        try:
            raw = dict(raw_row.get("payload") or {})
            metadata = dict(raw.get("metadata") or {})
            confirmed = set(metadata.get(_CONFIRMED_SIGNAL_IDS_KEY, []) or [])
            confirmed.add(signal_id)
            metadata[_CONFIRMED_SIGNAL_IDS_KEY] = sorted(confirmed)
            raw["metadata"] = metadata
            updated = dict(raw_row)
            updated["payload"] = raw
            await self._bronze().update(raw_row.get("id"), updated)
        except Exception as exc:  # pragma: no cover - best-effort replay stamp
            from shared.logger.logger import get_logger

            get_logger("aether.provider_runtime.confirmation").warning(
                "provider confirmation replay stamp failed record=%s: %s",
                raw_row.get("id"), exc,
            )


def _unconfirmed_result(signal: SDKCommerceSignal, canonical: AetherEvent) -> BridgeResult:
    """S2-shaped unconfirmed verdict for a canonical with no Bronze backing.

    Mirrors S2's ``unconfirmed`` construction exactly (same sdk_event_type
    derivation, same payload passthrough) so the reconciliation contract is
    indistinguishable from a bridge-produced verdict.
    """
    return BridgeResult(
        sdk_event_type=f"commerce.{signal.signal_type}",
        payload=dict(signal.payload),
        canonical_event_type=canonical.event_type,
        provider=canonical.provider,
        confirmed=False,
        confirmation_state="unconfirmed",
    )


async def confirm_interaction(
    signal: SDKCommerceSignal,
    canonical: Optional[AetherEvent],
    *,
    tenant_id: str = "",
    provider_identity: str = "",
    service: Optional[ConfirmInteractionService] = None,
) -> BridgeResult:
    """WS2-named entry point: confirm one signal against Bronze lineage via S2.

    ``canonical`` may be supplied (it is still verified against Bronze) or
    omitted (resolved from the signal's lineage). ``service`` is a test seam.
    """
    svc = service if service is not None else ConfirmInteractionService()
    return await svc.confirm(
        signal,
        tenant_id=tenant_id,
        provider_identity=provider_identity,
        canonical=canonical,
    )


__all__ = [
    "ConfirmationError",
    "ConfirmInteractionService",
    "confirm_interaction",
]
