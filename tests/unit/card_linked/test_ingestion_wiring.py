"""The card-linked pipeline is wired end-to-end: ingestion → flows store →
read surfaces → graph mirror → SDK-pipeline hook.

Before this wiring, CardLinkedIngestionService had zero runtime callers and
every read surface queried a store nothing wrote (the audit's BLOCKER 2).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from config.settings import get_settings  # noqa: E402
from services.card_linked_payments import ingestion as ingestion_mod  # noqa: E402
from services.card_linked_payments.ingestion import CardLinkedIngestionService  # noqa: E402


def _webhook_payload(**overrides):
    payload = {
        "id": "pw_wire_1",
        "provider": "rain",
        "provider_event_id": "evt-wire-1",
        "card_program_id": "redotpay",
        "issuer_id": "rain",
        "payment_network": "visa",
        "basis": "spend",
        "amount_usd": "42.50",
        "occurred_at": "2026-07-10T10:00:00Z",
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def service(monkeypatch):
    # Fresh repositories per test: the card-linked repo factory caches, so
    # reset its singleton the same way the existing card_linked conftest does.
    from services.card_linked_payments import repositories as repos_mod

    monkeypatch.setattr(repos_mod, "_repos", None, raising=False)
    monkeypatch.setattr(ingestion_mod, "_service", None, raising=False)
    return CardLinkedIngestionService(get_settings())


async def test_ingested_flow_is_visible_to_read_surfaces(service):
    record, disposition = await service.ingest_provider_webhook(
        "tenant-wire", _webhook_payload()
    )
    assert disposition == "created"
    flows = await service._repos.flows.list_for_tenant("tenant-wire")
    assert any(f.get("id") == record["id"] for f in flows), (
        "ingested flow not visible in the store the read surfaces query"
    )


async def test_ingested_flow_is_mirrored_to_graph(service):
    from dependencies.providers import get_graph

    graph = get_graph()
    record, disposition = await service.ingest_provider_webhook(
        "tenant-graph", _webhook_payload(provider_event_id="evt-graph-1")
    )
    assert disposition == "created"
    vertex = await graph.get_vertex(f"card_linked_flow:{record['id']}")
    assert vertex is not None, "flow vertex missing — graph projection did not run"


async def test_duplicate_ingest_does_not_reproject(service, monkeypatch):
    calls = []

    async def _spy(tenant_id, result):
        calls.append(result[1])
        return None

    payload = _webhook_payload(provider_event_id="evt-dup-1")
    await service.ingest_provider_webhook("tenant-dup", payload)
    monkeypatch.setattr(service, "_project_to_graph", _spy)
    _, disposition = await service.ingest_provider_webhook("tenant-dup", payload)
    assert disposition == "duplicate"
    assert calls == ["duplicate"], "projection hook not invoked with duplicate disposition"


def _force_flag(request, enabled: bool) -> None:
    """Flip the frozen card-linked flag for one test (restored afterwards)."""
    cfg = get_settings().card_linked_payment_rails
    original = cfg.enabled
    object.__setattr__(cfg, "enabled", enabled)
    request.addfinalizer(lambda: object.__setattr__(cfg, "enabled", original))


async def test_sdk_pipeline_hook_feeds_flow_store(request, monkeypatch):
    from services.ingestion.workers import _ingest_card_linked_context

    _force_flag(request, True)
    from services.card_linked_payments import repositories as repos_mod

    monkeypatch.setattr(repos_mod, "_repos", None, raising=False)
    monkeypatch.setattr(ingestion_mod, "_service", None, raising=False)

    payload = {
        "event_type": "payment_completed",
        "event_id": "evt-sdk-wire-1",
        "timestamp": "2026-07-10T11:00:00Z",
        "user_id": "user-1",
        "properties": {"card_program": "coinbase-card", "basis": "topup"},
    }
    await _ingest_card_linked_context("tenant-sdk-wire", payload)
    flows = await ingestion_mod.get_ingestion_service()._repos.flows.list_for_tenant(
        "tenant-sdk-wire"
    )
    assert flows, "SDK hook did not persist a card-linked flow"
    assert flows[0].get("source") == "sdk"


async def test_sdk_hook_ignores_non_card_events(request, monkeypatch):
    from services.ingestion.workers import _ingest_card_linked_context

    _force_flag(request, True)
    from services.card_linked_payments import repositories as repos_mod

    monkeypatch.setattr(repos_mod, "_repos", None, raising=False)
    monkeypatch.setattr(ingestion_mod, "_service", None, raising=False)

    await _ingest_card_linked_context(
        "tenant-sdk-noop",
        {"event_type": "page_view", "event_id": "evt-noop", "properties": {}},
    )
    flows = await ingestion_mod.get_ingestion_service()._repos.flows.list_for_tenant(
        "tenant-sdk-noop"
    )
    assert flows == []


async def test_ingest_routes_are_mounted():
    """POST ingestion endpoints exist on the card-linked router."""
    from services.card_linked_payments.routes import router

    paths = {(r.path, m) for r in router.routes for m in (r.methods or [])}
    prefix = "/v1/integrations/providers/payment-rails/card-linked"
    for suffix in ("/ingest/provider-webhook", "/ingest/onchain", "/import"):
        assert (f"{prefix}{suffix}", "POST") in paths, f"missing POST {suffix}"
