"""Source-authority invariants #3, #12 and #15 (docs/architecture/target/source-authority.md).

#3  Clients cannot submit authoritative RightsDecision references, on any intake path.
#12 Public reference (Olympus-scope) data never becomes tenant identity evidence.
#15 Access Kit transport cannot circumvent intake, tenant, consent or rights authorities.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
ACCESS_KIT_SRC = REPO / "packages" / "access-kit" / "src"

FORGED = {
    "rights": {"source_id": "feed:forged", "rights_decision_refs": ["rdec_forged"]},
    "rights_decision_refs": ["rdec_forged"],
    "source_grant_refs": ["drg_forged"],
    "source_relationship": "olympus_source",
}


# ── #3 ──────────────────────────────────────────────────────────────────────

def test_sdk_events_cannot_carry_rights_references():
    from ingestion.ingestion.observation_envelope import build_sdk_observation_envelope

    now = datetime.now(timezone.utc).isoformat()
    envelope = build_sdk_observation_envelope({
        "event_id": "e1", "tenant_id": "t1", "event_type": "track",
        "timestamp": now, "received_at": now, "ingested_at": now,
        "properties": dict(FORGED), "context": dict(FORGED),
    })
    assert envelope is not None
    assert envelope.rights is None
    assert envelope.source.source_relationship == "first_party_application"


def test_feed_requests_cannot_set_source_rights():
    from ingestion.ingestion.routes import APIFeedEvent

    event = APIFeedEvent(source="dune", entity_type="row", data={}, external_id="x",
                         source_rights=dict(FORGED), **{k: v for k, v in FORGED.items() if k != "rights"})
    dumped = event.model_dump()
    assert not set(dumped) & {"source_rights", "rights", "rights_decision_refs", "source_grant_refs", "source_relationship"}


def test_provider_events_cannot_carry_rights_references():
    from ingestion.ingestion.adapters.provider import ProviderIngressAdapter

    envelope = ProviderIngressAdapter().build_observation_envelope({
        "event_id": "e1", "tenant_id": "t1", "event_type": "commerce.order.created",
        "occurred_at": "2026-11-21T00:00:00Z", "observed_at": "2026-11-21T00:00:01Z",
        "provider_identity": "shopify.admin.orders_read", "source_record_id": "raw1",
        "data": dict(FORGED), "context": dict(FORGED),
    }, raw_record=None)
    assert envelope.rights is None
    assert envelope.source.source_relationship == "unclassified"


# ── #12 ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_olympus_scope_records_never_become_tenant_identity_evidence():
    from identity.identity.provider_evidence import capture_durable_provider_customer_evidence
    from repositories.repos import reset_in_memory_stores
    from shared.integration_contracts.events import RawProviderRecord, compute_checksum
    from shared.integration_contracts.source_relationship import OLYMPUS_SOURCE_TENANT_ID

    reset_in_memory_stores()
    payload = {"orderId": "w-1", "customerEmailId": "buyer@example.test"}

    async def capture(tenant_id: str) -> int:
        record = RawProviderRecord(
            provider_identity="walmart.marketplace.orders_read", tenant_id=tenant_id,
            connection_id="c", account_id="a", provider_record_type="order",
            provider_record_id=f"r-{tenant_id}", payload=payload, checksum=compute_checksum(payload),
        )
        return await capture_durable_provider_customer_evidence(
            [record], [(record, True)], tenant_id=tenant_id, connection_id="c", account_id="a",
            lifecycle_type="provider_sync_run", lifecycle_id=f"run-{tenant_id}",
        )

    # Control: the same record in a tenant scope does produce identity evidence.
    assert await capture("tenant-1") > 0
    assert await capture(OLYMPUS_SOURCE_TENANT_ID) == 0


# ── #15 ─────────────────────────────────────────────────────────────────────

SOURCE_OR_RIGHTS_PREFIXES = (
    "/v1/integrations/data-rights", "/v1/admin/kyber/data-rights", "/v1/provider-connections",
    "/v1/derivatives", "/v1/admin", "/v1/kyber", "/v1/ingest", "/v1/imports",
)


def test_delegated_mcp_tokens_reach_only_reads_and_never_source_or_rights_routes():
    from middleware import middleware as mw

    for path in mw._MCP_OAUTH_READ_ROUTES:
        assert not path.startswith(SOURCE_OR_RIGHTS_PREFIXES), path
    for (method, path) in mw._ACCESS_KIT_CAPABILITIES:
        assert not path.startswith(SOURCE_OR_RIGHTS_PREFIXES), (method, path)


def test_access_kit_writes_observations_only_through_canonical_batch_intake():
    paths = set()
    for source in ACCESS_KIT_SRC.glob("*.mjs"):
        paths.update(re.findall(r"/v1/[A-Za-z0-9_\-/{}$]+", source.read_text(encoding="utf-8")))
    assert paths, "Access Kit sources not found"
    assert not {p for p in paths if p.startswith(SOURCE_OR_RIGHTS_PREFIXES)}
    assert "/v1/batch" in paths
