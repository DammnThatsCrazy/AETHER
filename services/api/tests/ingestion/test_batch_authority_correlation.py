"""Joined proof for SDK intake, consent, metering, audit, and response refs."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from billing.billing.revops import UsageMeteringEventRepository
from billing.metering_evidence.service import MeteringEvidenceService
from config.settings import Environment, settings
from governance.consent import authority as consent_authority
from governance.security import audit_ledger as audit_module
from governance.security.audit_ledger import audit_ledger
from governance.security.request_context import bind_current_request
from ingestion.ingestion import batch
from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from shared.auth.auth import Permissions, Role, TenantContext


class _Cache:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def set_nx(self, key: str, _value: str, _ttl: int) -> bool:
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def delete(self, key: str) -> None:
        self.keys.discard(key)


class _Producer:
    async def publish_batch(self, _events) -> None:
        return None


@pytest.fixture(autouse=True)
def isolated_stores():
    reset_in_memory_stores()
    audit_module._TENANT_TAIL.clear()
    audit_module._TENANT_SEQ.clear()
    yield
    reset_in_memory_stores()
    audit_module._TENANT_TAIL.clear()
    audit_module._TENANT_SEQ.clear()


@pytest.mark.asyncio
async def test_batch_joins_actual_consent_usage_audit_and_request_references(monkeypatch):
    tenant_id = "tenant-correlation"
    request_id = "req-correlation-joined"
    receipt_id = "consent-receipt-joined"
    event_id = "event-correlation-joined"

    monkeypatch.setattr(settings, "env", Environment.LOCAL)
    monkeypatch.setattr(settings, "consent_authority", replace(
        settings.consent_authority,
        authoritative_consent_enforcement_enabled=True,
    ))
    monkeypatch.setattr(settings, "ingestion_v2", replace(
        settings.ingestion_v2,
        enabled=False,
        canary_tenants=frozenset(),
    ))
    monkeypatch.setattr(settings, "observation_envelope", replace(
        settings.observation_envelope,
        enabled=True,
    ))
    monkeypatch.setattr(settings, "ingress_gateway", replace(
        settings.ingress_gateway,
        enabled=False,
    ))
    monkeypatch.setattr(
        batch,
        "get_registry",
        lambda: SimpleNamespace(cache=_Cache()),
    )

    await consent_authority._receipt_repo.record(
        receipt_id,
        tenant_id,
        "analytics",
        "granted",
        anonymous_id="anonymous-correlation",
        lawful_basis="contract",
    )

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/batch",
        "headers": [(b"x-correlation-id", request_id.encode())],
        "server": ("test", 80),
        "client": ("127.0.0.1", 12345),
    })
    request.state.tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="user-correlation",
        role=Role.ADMIN,
        permissions=[Permissions.WRITE],
    )
    request.state.request_id = request_id
    request.state.context = SimpleNamespace(
        tenant_id=tenant_id,
        correlation_id=request_id,
    )

    body = batch.BatchRequest(
        batch=[batch.BaseEvent(
            id=event_id,
            type="track",
            timestamp="2026-10-12T12:00:00+00:00",
            sessionId="session-correlation",
            anonymousId="anonymous-correlation",
            properties={"event": "opened"},
        )],
        sentAt="2026-10-12T12:00:01+00:00",
    )

    bind_current_request(request)
    try:
        response = await batch.ingest_batch(request, body, _Producer())
    finally:
        bind_current_request(None)

    assert response["accepted"] == 1
    assert response["requestId"] == request_id
    assert response["consentReceiptIds"] == [receipt_id]
    assert response["usageEventId"]
    assert response["usageEvidenceId"]
    assert response["auditEventId"]

    bronze_rows = await BronzeRepository("sdk_events").find_many(
        filters={"tenant_id": tenant_id}, limit=10,
    )
    assert len(bronze_rows) == 1
    payload = bronze_rows[0]["payload"]
    assert payload["privacy"]["consent_snapshot"] == receipt_id
    assert payload["observation_envelope"]["privacy"]["consent_snapshot"] == receipt_id

    consent_row = await consent_authority._receipt_repo.latest_for(
        tenant_id, "analytics", anonymous_id="anonymous-correlation",
    )
    assert consent_row["receipt_id"] == receipt_id

    evidence = await MeteringEvidenceService().explain(
        response["usageEvidenceId"], tenant_id=tenant_id,
    )
    usage = await UsageMeteringEventRepository().find_by_id(response["usageEventId"])
    assert evidence["event_id"] == response["batchId"]
    assert evidence["metadata"]["correlation_id"] == request_id
    assert usage["source_id"] == response["batchId"]
    assert usage["metadata"]["correlation_id"] == request_id

    audit_row = await audit_ledger._repo.find_by_id(response["auditEventId"])
    assert audit_row["resource_id"] == response["batchId"]
    assert audit_row["correlation_id"] == request_id
    assert audit_row["metadata"]["usage_event_id"] == response["usageEventId"]
    assert audit_row["metadata"]["usage_evidence_id"] == response["usageEvidenceId"]
    assert audit_row["metadata"]["consent_receipt_ids"] == [receipt_id]
    assert (await audit_ledger.verify_chain(tenant_id))["chain_intact"] is True
