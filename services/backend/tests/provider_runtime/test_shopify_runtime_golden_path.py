"""Golden path through the production-backed Shopify provider runtime.

The Shopify pull capability is represented by a provider response fixture, and
the outbound event bus transport is captured at its boundary. The runtime
registry, scheduler, Bronze stores, Shopify normalizer, sync-run lifecycle,
evidence capture, and identity candidate adapter are the real implementations.

This proves that the active pull path retains provider raw evidence while
quarantining records that lack a verified source-license admission. Quarantined
records do not produce normalized commerce events or candidate-visible identity
evidence.
"""

from __future__ import annotations

import pytest

from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from services.comms.sync_runs import SyncRunRepository, SyncRunService
from services.identity.import_candidate_adapter import ImportIdentityCandidateAdapter
from services.identity.repository import IdentityResolutionRepository
from services.identity.source_identity_registry import SourceIdentityRegistry
from services.provider_runtime import bridge as bridge_module
from services.provider_runtime.connection import ProviderConnection, ProviderConnectionRepository
from services.provider_runtime.registry import ProviderRegistry
from services.provider_runtime.scheduler import PullScheduler
from services.providers.shopify.plugin import ShopifyOrdersPlugin
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.events import ReadBatch, make_raw_record
from shared.integration_contracts.results import AdapterResult


class _PullFixture:
    """Provider response fixture at the remote API boundary."""

    async def fetch(self, context, *, cursor, limit=None):
        record = make_raw_record(
            provider_identity=context.provider_identity,
            provider_record_id="771",
            provider_record_type="order",
            tenant_id=context.tenant_id,
            connection_id=context.connection_id,
            account_id=context.account_id,
            payload={
                "id": 771,
                "name": "#771",
                "created_at": "2026-10-01T10:00:00Z",
                "updated_at": "2026-10-01T10:05:00Z",
                "financial_status": "paid",
                "currency": "USD",
                "subtotal_price": "24.50",
                "total_price": "24.50",
                "customer": {
                    "id": 991,
                    "email": "Customer@Example.com",
                    "phone": "+1 415 555 0771",
                },
                "line_items": [{
                    "id": 1,
                    "title": "Notebook",
                    "quantity": 1,
                    "price": "24.50",
                }],
            },
        )
        return AdapterResult.ok(ReadBatch(records=[record]))


@pytest.fixture(autouse=True)
def _isolated_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_shopify_sync_retains_but_does_not_promote_quarantined_record(monkeypatch):
    published: list[tuple[str, object]] = []

    async def capture_publish(tenant_id, event):
        published.append((tenant_id, event))

    monkeypatch.setattr(bridge_module, "_publish_event", capture_publish)

    class _GoldenPlugin(ShopifyOrdersPlugin):
        """Keep the real Shopify normalizer while fixing remote API output."""

        def pull(self):
            return _PullFixture()

    plugin = _GoldenPlugin()
    identity = plugin.identity().key
    registry = ProviderRegistry(auto_install_legacy=False)
    assert registry.register(plugin, source="golden-path-test") == identity
    connection = ProviderConnection(
        connection_id="conn-golden",
        tenant_id="tenant-golden",
        provider_identity=identity,
        state=ConnectionState.CONNECTED,
        selected_accounts=["shop-golden"],
        config={},
    )
    connections = ProviderConnectionRepository()
    await connections.upsert(connection)

    async def no_op_meter(*_args):
        return None

    scheduler = PullScheduler(
        registry=registry,
        connections=connections,
        sync_runs=SyncRunService(),
        meters=no_op_meter,
    )
    result = await scheduler.run_sync(connection)

    assert result.status == "partial"
    assert result.records_received == 1
    assert result.records_rejected == 1
    assert result.facts_written == 0
    assert result.cursor_after is None

    raw_rows = await BronzeRepository("provider_records").find_many(
        filters={"tenant_id": "tenant-golden"}, limit=20,
    )
    assert len(raw_rows) == 1
    raw_row = raw_rows[0]
    raw = raw_row["payload"]
    assert raw["provider_identity"] == identity
    assert raw["provider_record_id"] == "771"
    assert raw["tenant_id"] == "tenant-golden"
    assert raw["connection_id"] == "conn-golden"
    assert raw["account_id"] == "shop-golden"
    # The provider manifest supplies no verified license/terms evidence, so
    # Bronze retains the row but quarantine blocks downstream promotion.
    assert raw_row["quarantine_status"] == "quarantined"
    assert raw_row["license_status"] == "unknown"
    assert raw_row["commercial_use_status"] == "unknown"
    assert published == []

    identity_repo = IdentityResolutionRepository()
    source = await SourceIdentityRegistry(identity_repo).find_existing_source_identity(
        "tenant-golden", "shopify:shop-golden:conn-golden", external_id="991",
    )
    assert source is None

    run_rows = await SyncRunRepository().list_for_connector(
        "tenant-golden", "conn-golden", limit=10,
    )
    assert len(run_rows) == 1 and run_rows[0]["status"] == "partial"
    assert run_rows[0]["records_rejected"] == 1
    assert run_rows[0]["safe_error_code"] == "source_rights_rejected"
    assert await scheduler.cursors.get_cursor(
        "tenant-golden", "conn-golden", identity,
    ) is None

    candidates = ImportIdentityCandidateAdapter(identity_repo)
    same_tenant = await candidates.evaluate(
        tenant_id="tenant-golden", claims={"email": "customer@example.com"},
    )
    other_tenant = await candidates.evaluate(
        tenant_id="tenant-other", claims={"email": "customer@example.com"},
    )
    assert same_tenant.outcome == "no_match"
    assert same_tenant.candidate_source_identity_ids == []
    assert other_tenant.outcome == "no_match"
