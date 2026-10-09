"""Golden path through the production-backed Shopify provider runtime.

The Shopify pull capability is represented by a provider response fixture, and
the outbound event bus transport is captured at its boundary. The runtime
registry, scheduler, Bronze stores, Shopify normalizer, sync-run lifecycle,
evidence capture, and identity candidate adapter are the real implementations.

Tenant raw-rights admission is the single gate for this path. A record without
an allowed tenant grant is never retained and produces no normalized commerce
events or candidate-visible identity evidence; with an allowed grant the same
record is retained, normalized, and published.
"""

from __future__ import annotations

import pytest

import repositories.repos as repos
from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from services.comms.sync_runs import SyncRunRepository, SyncRunService
from services.identity.import_candidate_adapter import ImportIdentityCandidateAdapter
from services.identity.repository import IdentityResolutionRepository
from services.identity.source_identity_registry import SourceIdentityRegistry
from services.provider_runtime.connection import ProviderConnection, ProviderConnectionRepository
from services.provider_runtime.errors import ProviderPullFailed
from services.provider_runtime.raw_store import RawProviderRecordStore
from services.provider_runtime.rights_admission import (
    ProviderRawRightsEvidence,
    provider_account_source_id,
)
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


class _GrantedRightsAdmission:
    """Explicit tenant-grant seam; production defaults use EffectiveRightsResolver."""

    async def admit(self, record):
        return ProviderRawRightsEvidence(
            tenant_id=record.tenant_id,
            source_id=provider_account_source_id(record.connection_id, record.account_id),
            source_grant_ref="drg_golden",
            rights_decision_ref=f"rdec_{record.idempotency_key}",
            decision_identity=f"rdid_{record.idempotency_key}",
            policy_version="irrl-2",
            evaluated_at="2026-10-03T00:00:00+00:00",
        )

    async def verify_persisted(self, record, *, current_admission):
        return None


class _GrantedBronzeRepository(BronzeRepository):
    """Bronze seam for rows whose provenance trusted setup has approved."""

    async def ingest(self, **kwargs):
        kwargs.update(
            provenance_status="valid",
            license_status="public_api",
            terms_status="approved",
        )
        return await super().ingest(**kwargs)


class _CapturingBridge:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def ingest_events(self, tenant_id, events) -> int:
        self.events.extend(events)
        return len(events)


class _GoldenPlugin(ShopifyOrdersPlugin):
    """Keep the real Shopify normalizer while fixing remote API output."""

    def pull(self):
        return _PullFixture()


async def _scheduler(*, raw_store, bridge):
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
        raw_store=raw_store,
        bridge=bridge,
        sync_runs=SyncRunService(),
        meters=no_op_meter,
    )
    return scheduler, connection, identity


@pytest.mark.asyncio
async def test_shopify_sync_without_tenant_rights_retains_and_promotes_nothing(monkeypatch):
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    bridge = _CapturingBridge()
    scheduler, connection, identity = await _scheduler(
        raw_store=RawProviderRecordStore(), bridge=bridge,
    )

    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(connection)

    assert exc_info.value.details["error_code"] == "provider_raw_persist_failed"
    assert exc_info.value.details["detail"] == "ProviderRawRightsDenied"
    assert bridge.events == []
    assert await BronzeRepository("provider_records").find_many(
        filters={"tenant_id": "tenant-golden"}, limit=20,
    ) == []
    assert await scheduler.cursors.get_cursor(
        "tenant-golden", "conn-golden", identity,
    ) is None

    run_rows = await SyncRunRepository().list_for_connector(
        "tenant-golden", "conn-golden", limit=10,
    )
    assert len(run_rows) == 1 and run_rows[0]["status"] == "failed"

    identity_repo = IdentityResolutionRepository()
    assert await SourceIdentityRegistry(identity_repo).find_existing_source_identity(
        "tenant-golden", "shopify:shop-golden:conn-golden", external_id="991",
    ) is None
    candidates = ImportIdentityCandidateAdapter(identity_repo)
    same_tenant = await candidates.evaluate(
        tenant_id="tenant-golden", claims={"email": "customer@example.com"},
    )
    assert same_tenant.outcome == "no_match"
    assert same_tenant.candidate_source_identity_ids == []


@pytest.mark.asyncio
async def test_shopify_sync_with_tenant_rights_retains_normalizes_and_publishes():
    bridge = _CapturingBridge()
    scheduler, connection, identity = await _scheduler(
        raw_store=RawProviderRecordStore(
            repository=_GrantedBronzeRepository("provider_records"),
            rights_admission=_GrantedRightsAdmission(),
        ),
        bridge=bridge,
    )

    result = await scheduler.run_sync(connection)

    assert result["status"] == "completed"
    run_rows = await SyncRunRepository().list_for_connector(
        "tenant-golden", "conn-golden", limit=10,
    )
    assert len(run_rows) == 1 and run_rows[0]["status"] == "completed"
    assert run_rows[0]["records_received"] == 1
    assert run_rows[0]["facts_written"] == len(bridge.events) >= 1
    raw_rows = await BronzeRepository("provider_records").find_many(
        filters={"tenant_id": "tenant-golden"}, limit=20,
    )
    assert len(raw_rows) == 1
    raw = raw_rows[0]["payload"]
    assert raw["provider_identity"] == identity
    assert raw["provider_record_id"] == "771"
    assert raw["tenant_id"] == "tenant-golden"
    assert raw["connection_id"] == "conn-golden"
    assert raw["account_id"] == "shop-golden"
    assert raw["metadata"]["aether_rights_admission"]["source_grant_ref"] == "drg_golden"
