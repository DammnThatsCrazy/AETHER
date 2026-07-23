from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.integrations import webhook_policy
from services.integrations.connectors.adapters import ShopifyConnector, WebhookConnector
from services.integrations.connectors.service import ConnectorService
from services.integrations.webhook_quarantine import webhook_quarantine
from services.security.integration_security import sign_payload


def _gate(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        integration_consent=SimpleNamespace(
            control_plane_v2_enabled=enabled,
            connector_policy_gate_enabled=enabled,
        )
    )


@pytest.mark.asyncio
async def test_control_plane_preserves_absent_admin_values_and_explicit_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def _evaluate(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            allowed=True,
            reasonCode=None,
            quarantineRequired=False,
            decisionId="icpd_test",
        )

    import services.integrations.consent_policy as consent_policy

    monkeypatch.setattr(webhook_policy, "settings", _gate())
    monkeypatch.setattr(
        consent_policy, "evaluate_connector_processing", _evaluate
    )

    outcome = await webhook_policy.evaluate_consent_control_plane(
        tenant_id="tenant-1",
        connector_type="webhook",
        connector_config={
            "purpose": "analytics",
            "processing_basis": "contract",
        },
        payload_fields=["event", "anonymous_id"],
        anonymous_id="anon-1",
    )

    assert outcome.allowed is True
    assert captured["purpose"] == "analytics"
    assert captured["processing_basis"] == "contract"
    assert captured["tenant_admin_approved"] is None
    assert captured["provider_admin_installed"] is None


@pytest.mark.asyncio
async def test_control_plane_passes_explicit_false_admin_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def _evaluate(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            allowed=False,
            reasonCode="tenant_admin_approval_required",
            quarantineRequired=True,
            decisionId="icpd_denied",
        )

    import services.integrations.consent_policy as consent_policy

    monkeypatch.setattr(webhook_policy, "settings", _gate())
    monkeypatch.setattr(
        consent_policy, "evaluate_connector_processing", _evaluate
    )
    outcome = await webhook_policy.evaluate_consent_control_plane(
        tenant_id="tenant-1",
        connector_type="shopify",
        connector_config={
            "purpose": "commerce",
            "processing_basis": "contract",
            "tenant_admin_approved": False,
            "provider_admin_installed": False,
        },
    )

    assert outcome.allowed is False
    assert outcome.quarantine_required is True
    assert captured["tenant_admin_approved"] is False
    assert captured["provider_admin_installed"] is False


@pytest.mark.asyncio
async def test_malformed_admin_values_remain_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def _evaluate(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            allowed=True,
            reasonCode=None,
            quarantineRequired=False,
            decisionId="icpd_test",
        )

    import services.integrations.consent_policy as consent_policy

    monkeypatch.setattr(webhook_policy, "settings", _gate())
    monkeypatch.setattr(
        consent_policy, "evaluate_connector_processing", _evaluate
    )
    await webhook_policy.evaluate_consent_control_plane(
        tenant_id="tenant-1",
        connector_type="shopify",
        connector_config={
            "purpose": "commerce",
            "processing_basis": "contract",
            "tenant_admin_approved": "banana",
            "provider_admin_installed": 2,
        },
    )

    assert captured["tenant_admin_approved"] is None
    assert captured["provider_admin_installed"] is None


@pytest.mark.asyncio
async def test_control_plane_import_failure_denies_when_gate_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(webhook_policy, "settings", _gate())
    monkeypatch.setitem(
        sys.modules, "services.integrations.consent_policy", None
    )

    outcome = await webhook_policy.evaluate_consent_control_plane(
        tenant_id="tenant-1",
        connector_type="webhook",
        connector_config={
            "purpose": "analytics",
            "processing_basis": "contract",
        },
    )

    assert outcome.allowed is False
    assert outcome.quarantine_required is True
    assert outcome.reason_code == webhook_policy.POLICY_RUNTIME_UNAVAILABLE


def test_provider_native_and_generic_signatures_use_declared_schemes() -> None:
    secret = "whsec_test"
    raw = b'{"id":"order-1"}'

    import base64
    import hashlib
    import hmac

    shopify_signature = base64.b64encode(
        hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    ).decode()
    assert webhook_policy.verify_provider_webhook_signature(
        ShopifyConnector(),
        raw_body=raw,
        headers={"X-Shopify-Hmac-SHA256": shopify_signature},
        secret=secret,
    )

    generic_headers = sign_payload(secret, raw)
    assert webhook_policy.verify_provider_webhook_signature(
        WebhookConnector(),
        raw_body=raw,
        headers=generic_headers,
        secret=secret,
        signature=generic_headers["X-Aether-Signature"],
        timestamp=generic_headers["X-Aether-Timestamp"],
    )


@pytest.mark.asyncio
async def test_quarantine_persists_hash_and_reference_not_raw_payload() -> None:
    reset_in_memory_stores()
    raw = b'{"email":"sensitive@example.com"}'
    record = await webhook_quarantine.quarantine(
        tenant_id="tenant-1",
        connector_type="webhook",
        raw_body=raw,
        reason_code="purpose_not_approved",
        inbox_id="inbox-1",
        policy_decision_id="icpd_denied",
    )

    assert record["encrypted_payload_ref"] == "webhook_inbox:inbox-1"
    assert record["payload_size_bytes"] == len(raw)
    assert raw.decode() not in str(record)


@pytest.mark.asyncio
async def test_connector_service_quarantines_control_plane_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_in_memory_stores()
    service = ConnectorService()

    async def _find_config(record_id: str) -> dict:
        return {
            "tenant_id": "tenant-1",
            "connector_type": "webhook",
            "enabled": True,
            "config": {
                "purpose": "analytics",
                "processing_basis": "contract",
            },
        }

    async def _deny(**kwargs) -> webhook_policy.WebhookPolicyOutcome:
        return webhook_policy.WebhookPolicyOutcome(
            allowed=False,
            reason_code="purpose_not_approved",
            quarantine_required=True,
            policy_decision_id="icpd_denied",
        )

    class _Inbox:
        async def insert(self, record_id: str, data: dict) -> dict:
            return data

    monkeypatch.setattr(service.repo, "find_by_id", _find_config)
    monkeypatch.setattr(
        webhook_policy, "evaluate_consent_control_plane", _deny
    )

    result = await service.ingest_webhook(
        "webhook",
        "tenant-1",
        raw_body=b'{"event":"page_view"}',
        webhook_inbox_repo=_Inbox(),
    )

    assert result["accepted"] is False
    assert result["quarantined"] is True
    quarantined = await webhook_quarantine.find_many(
        filters={"tenant_id": "tenant-1"}
    )
    assert len(quarantined) == 1
    assert quarantined[0]["reason_code"] == "purpose_not_approved"
