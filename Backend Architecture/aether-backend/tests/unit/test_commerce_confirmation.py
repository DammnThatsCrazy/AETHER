"""WS2 — server-side commerce signal confirmation tests.

The confirmation service resolves an SDK signal's lineage against Bronze
``provider_records`` and delegates the verdict to Team A's
``shared.integration_contracts.commerce_bridge.confirm_interaction``. Covers the
four-outcome contract (matched / unconfirmed / replay / not_found) plus the
replay stamp living on the existing raw record (no new store).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from shared.integration_contracts.commerce_bridge import SDKCommerceSignal
from shared.integration_contracts.events import AetherEvent
from services.provider_runtime.confirmation import ConfirmInteractionService

_TENANT = "t1"
_PROVIDER = "shopify.admin.orders_read"
_CONFIRMED_KEY = "confirmed_signal_ids"


def _raw_row(
    *,
    record_id: str = "rec-123",
    provider_record_id: str = "ord-123",
    idempotency_key: str = "ik-1",
    confirmed_ids: list[str] | None = None,
    provider_occurred_at: str = "2026-08-08T00:00:00+00:00",
) -> dict:
    payload = {
        "record_id": record_id,
        "tenant_id": _TENANT,
        "provider_identity": _PROVIDER,
        "provider_record_id": provider_record_id,
        "provider_record_type": "order",
        "acquisition_mode": "poll",
        "schema_version": "1",
        "observed_at": "2026-08-08T00:00:00+00:00",
        "provider_occurred_at": provider_occurred_at,
        "payload": {"order_id": "ord-123", "total": "10.00"},
        "metadata": {},
    }
    if confirmed_ids is not None:
        payload["metadata"][_CONFIRMED_KEY] = confirmed_ids
    return {
        "id": f"bronze-{record_id}",
        "tenant_id": _TENANT,
        "source": _PROVIDER,
        "provider_record_id": provider_record_id,
        "idempotency_key": idempotency_key,
        "payload": payload,
    }


class FakeBronze:
    """Minimal in-memory Bronze seam: find_many(filters, limit) + update(id, data)."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = list(rows)
        self.updates: list[tuple] = []

    async def find_many(self, filters=None, limit=50):
        filters = filters or {}
        matched = []
        for row in self.rows:
            if all(row.get(k) == v for k, v in filters.items()):
                matched.append(row)
        return matched[:limit]

    async def update(self, record_id: str, data: dict) -> None:
        self.updates.append((record_id, data))
        for i, row in enumerate(self.rows):
            if row.get("id") == record_id:
                self.rows[i] = data


def _signal(signal_id: str, source_record_id: str | None) -> SDKCommerceSignal:
    return SDKCommerceSignal(
        signal_id=signal_id,
        signal_type="order_confirmed",
        occurred_at="2026-08-08T00:00:00+00:00",
        source_url="https://shop.myshopify.com",
        lineage={"source_record_id": source_record_id},
        payload={"order_id": "ord-123", "total": "10.00"},
    )


def _lineage_signal(signal_id: str, lineage: dict) -> SDKCommerceSignal:
    """A signal carrying an arbitrary lineage (e.g. ONLY provider_record_id or
    idempotency_key, with no source_record_id) — the C-4 dead-lineage cases."""
    return SDKCommerceSignal(
        signal_id=signal_id,
        signal_type="order_confirmed",
        occurred_at="2026-08-08T00:00:00+00:00",
        source_url="https://shop.myshopify.com",
        lineage=lineage,
        payload={"order_id": "ord-123", "total": "10.00"},
    )


# ── matched / replay via lineage resolution ─────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_matched_resolves_lineage_and_stamps() -> None:
    bronze = FakeBronze([_raw_row()])
    service = ConfirmInteractionService(bronze=bronze)
    signal = _signal("sig-1", "rec-123")
    result = await service.confirm(
        signal, tenant_id=_TENANT, provider_identity=_PROVIDER
    )
    assert result.confirmation_state == "matched"
    assert result.confirmed is True
    # The replay stamp lives on the existing raw record (no new store).
    assert bronze.updates, "matched confirmation must persist the replay stamp"
    stamped = bronze.updates[0][1]["payload"]["metadata"][_CONFIRMED_KEY]
    assert "sig-1" in stamped


@pytest.mark.asyncio
async def test_confirm_replay_on_duplicate_signal_delivery() -> None:
    bronze = FakeBronze([_raw_row(confirmed_ids=["sig-1"])])
    service = ConfirmInteractionService(bronze=bronze)
    signal = _signal("sig-1", "rec-123")
    result = await service.confirm(
        signal, tenant_id=_TENANT, provider_identity=_PROVIDER
    )
    assert result.confirmation_state == "replay"
    assert result.confirmed is False


@pytest.mark.asyncio
async def test_confirm_second_delivery_becomes_replay() -> None:
    """First confirm is matched + stamped; a repeat delivery is replay."""
    bronze = FakeBronze([_raw_row()])
    service = ConfirmInteractionService(bronze=bronze)
    signal = _signal("sig-1", "rec-123")
    first = await service.confirm(
        signal, tenant_id=_TENANT, provider_identity=_PROVIDER
    )
    assert first.confirmation_state == "matched"
    second = await service.confirm(
        signal, tenant_id=_TENANT, provider_identity=_PROVIDER
    )
    assert second.confirmation_state == "replay"
    assert second.confirmed is False


# ── C-4: provider_record_id / idempotency_key-only lineage (must reach matched)


@pytest.mark.asyncio
async def test_confirm_provider_record_id_only_lineage_matches() -> None:
    """A signal carrying ONLY provider_record_id (no source_record_id) resolves
    the row by that key; confirmation injects the resolved row's record_id into
    the S2 comparison so the signal reaches ``matched`` (C-4)."""
    bronze = FakeBronze([_raw_row()])
    service = ConfirmInteractionService(bronze=bronze)
    signal = _lineage_signal("sig-prov-1", {"provider_record_id": "ord-123"})
    result = await service.confirm(
        signal, tenant_id=_TENANT, provider_identity=_PROVIDER
    )
    assert result.confirmation_state == "matched"
    assert result.confirmed is True
    assert bronze.updates, "matched confirmation must persist the replay stamp"


@pytest.mark.asyncio
async def test_confirm_idempotency_key_only_lineage_matches() -> None:
    """A signal carrying ONLY idempotency_key resolves the row by that key and
    reaches ``matched`` via the resolved row's record_id (C-4)."""
    bronze = FakeBronze([_raw_row()])
    service = ConfirmInteractionService(bronze=bronze)
    signal = _lineage_signal("sig-ik-1", {"idempotency_key": "ik-1"})
    result = await service.confirm(
        signal, tenant_id=_TENANT, provider_identity=_PROVIDER
    )
    assert result.confirmation_state == "matched"
    assert result.confirmed is True
    assert bronze.updates, "matched confirmation must persist the replay stamp"


@pytest.mark.asyncio
async def test_stamp_failure_never_fails_the_confirmation() -> None:
    """C-6 current guarantee: the replay stamp is best-effort read-modify-write
    (BronzeRepository.update has no atomic append). A stamp failure degrades to
    'this delivery confirmed' and never raises — the confirmation verdict is
    never held hostage by the stamp."""
    from services.provider_runtime.confirmation import ConfirmInteractionService

    class _BrokenUpdateBronze(FakeBronze):
        async def update(self, record_id: str, data: dict) -> None:
            raise RuntimeError("bronze update down")

    bronze = _BrokenUpdateBronze([_raw_row()])
    service = ConfirmInteractionService(bronze=bronze)
    signal = _signal("sig-stamp-fail", "rec-123")
    result = await service.confirm(
        signal, tenant_id=_TENANT, provider_identity=_PROVIDER
    )
    assert result.confirmation_state == "matched"
    assert result.confirmed is True


# ── C-3: deterministic bounded source_record_id fallback scan ───────────────


def test_scan_sort_key_orders_newest_first() -> None:
    """The fallback-scan sort key orders by provider_occurred_at DESC (a
    missing timestamp falls back to created_at, then a far-past sentinel) so the
    bounded scan is deterministic."""
    from services.provider_runtime.confirmation import _scan_sort_key

    rows = [
        _raw_row(record_id="r1", provider_occurred_at="2026-08-07T00:00:00+00:00"),
        _raw_row(record_id="r3", provider_occurred_at="2026-08-09T00:00:00+00:00"),
        _raw_row(record_id="r2", provider_occurred_at="2026-08-08T00:00:00+00:00"),
    ]
    ordered = sorted(rows, key=_scan_sort_key, reverse=True)
    assert [(r.get("payload") or {}).get("record_id") for r in ordered] == [
        "r3",
        "r2",
        "r1",
    ]


@pytest.mark.asyncio
async def test_find_raw_resolves_source_record_id_regardless_of_row_order() -> None:
    """The bounded source_record_id scan sorts the window, so the target row is
    resolved deterministically even when the backend returns it in a
    non-obvious position."""
    older = _raw_row(
        record_id="rec-old", provider_occurred_at="2026-08-07T00:00:00+00:00"
    )
    target = _raw_row(
        record_id="rec-target", provider_occurred_at="2026-08-09T00:00:00+00:00"
    )
    bronze = FakeBronze([older, target])  # target is NOT first in backend order
    service = ConfirmInteractionService(bronze=bronze)
    row = await service._find_raw(
        source_record_id="rec-target",
        provider_record_id="",
        tenant_id=_TENANT,
        provider_identity=_PROVIDER,
    )
    assert row is not None
    assert (row.get("payload") or {}).get("record_id") == "rec-target"


# ── not_found / unconfirmed (no false positives) ────────────────────────────


@pytest.mark.asyncio
async def test_confirm_not_found_when_lineage_resolves_to_nothing() -> None:
    bronze = FakeBronze([_raw_row()])
    service = ConfirmInteractionService(bronze=bronze)
    signal = _signal("sig-x", "does-not-exist")
    result = await service.confirm(
        signal, tenant_id=_TENANT, provider_identity=_PROVIDER
    )
    assert result.confirmation_state == "not_found"
    assert result.confirmed is False


@pytest.mark.asyncio
async def test_confirm_canonical_not_backed_is_unconfirmed() -> None:
    """A caller-supplied canonical that is NOT backed by Bronze is never
    confirmed — unconfirmed, never a false positive."""
    bronze = FakeBronze([_raw_row()])
    service = ConfirmInteractionService(bronze=bronze)
    signal = _signal("sig-x", "rec-999")
    canonical = AetherEvent(
        event_id="evt-fake",
        event_type="commerce.order.confirmed",
        event_family="commerce",
        tenant_id=_TENANT,
        provider="shopify",
        provider_identity=_PROVIDER,
        source_record_id="rec-999",
        occurred_at="2026-08-08T00:00:00+00:00",
        observed_at="2026-08-08T00:00:00+00:00",
        data={"order_id": "ord-999"},
    )
    result = await service.confirm(
        signal, tenant_id=_TENANT, provider_identity=_PROVIDER, canonical=canonical
    )
    assert result.confirmation_state == "unconfirmed"
    assert result.confirmed is False


@pytest.mark.asyncio
async def test_confirm_backed_canonical_matches_with_replay_context() -> None:
    bronze = FakeBronze([_raw_row(confirmed_ids=["sig-prior"])])
    service = ConfirmInteractionService(bronze=bronze)
    signal = _signal("sig-2", "rec-123")
    canonical = AetherEvent(
        event_id="evt-1",
        event_type="commerce.order.confirmed",
        event_family="commerce",
        tenant_id=_TENANT,
        provider="shopify",
        provider_identity=_PROVIDER,
        source_record_id="rec-123",
        occurred_at="2026-08-08T00:00:00+00:00",
        observed_at="2026-08-08T00:00:00+00:00",
        data={"order_id": "ord-123"},
        context={"provider_record_id": "ord-123"},
    )
    result = await service.confirm(
        signal, tenant_id=_TENANT, provider_identity=_PROVIDER, canonical=canonical
    )
    assert result.confirmation_state == "matched"
    assert result.confirmed is True
    # The canonical's replay context came from the raw record's own metadata.
    assert "sig-prior" in (canonical.context or {}).get(_CONFIRMED_KEY, [])


# ── Cross-tenant isolation ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_is_tenant_scoped_no_cross_tenant_match() -> None:
    bronze = FakeBronze([_raw_row()])  # row belongs to _TENANT
    service = ConfirmInteractionService(bronze=bronze)
    signal = _signal("sig-1", "rec-123")
    result = await service.confirm(
        signal, tenant_id="other-tenant", provider_identity=_PROVIDER
    )
    # The same record id under a different tenant must not resolve — not_found.
    assert result.confirmation_state == "not_found"
    assert result.confirmed is False


# ── Public entry point (confirm_interaction) ────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_interaction_entry_point_matches() -> None:
    from services.provider_runtime.confirmation import confirm_interaction

    bronze = FakeBronze([_raw_row()])
    service = ConfirmInteractionService(bronze=bronze)
    signal = _signal("sig-entry", "rec-123")
    result = await confirm_interaction(
        signal,
        None,
        tenant_id=_TENANT,
        provider_identity=_PROVIDER,
        service=service,
    )
    assert result.confirmation_state == "matched"
    assert result.confirmed is True
