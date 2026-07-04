from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture()
def provider_framework(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    return importlib.import_module("services.agentic_observability.provider_framework")

def test_x_reference_adapter_verifies_matching_provider_snapshot(provider_framework):
    adapter = provider_framework.XReferenceAdapter()
    action = adapter.normalize_action(
        "tenant-a",
        {
            "action_type": "content_created",
            "provider_request_id": "req-1",
            "external_object_id": "post-1",
            "authorization_id": "auth-1",
            "external_account_id": "acct-1",
        },
    )

    verification = adapter.verify_action(action, {"external_object_id": "post-1", "action_type": "content_created", "evidence_ref": "evidence:x:post-1"})

    assert verification.verification_status == provider_framework.ProviderVerificationStatus.PROVIDER_CONFIRMED
    assert verification.verification_source == "provider_api_read"
    assert verification.confidence == 0.95
    assert verification.evidence_ref == "evidence:x:post-1"


def test_x_reference_adapter_contradicts_mismatched_provider_snapshot(provider_framework):
    adapter = provider_framework.XReferenceAdapter()
    action = adapter.normalize_action("tenant-a", {"action_type": "content_created", "external_object_id": "post-1"})

    verification = adapter.verify_action(action, {"external_object_id": "post-2", "action_type": "content_created"})

    assert verification.verification_status == provider_framework.ProviderVerificationStatus.CONTRADICTED
    assert verification.contradiction_reason == "provider_snapshot_mismatch"


def test_webhook_signature_validation_is_read_only(provider_framework):
    adapter = provider_framework.XReferenceAdapter()
    secret = "webhook-secret"
    body = json.dumps({"action_type": "content_created", "external_object_id": "post-1"}).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()

    records = adapter.consume_webhook("tenant-a", body, {"x-x-signature": signature}, secret=secret)

    assert len(records) == 1
    assert records[0].verification_status == provider_framework.ProviderVerificationStatus.PROVIDER_CONFIRMED
    with pytest.raises(ValueError, match="invalid provider webhook signature"):
        adapter.consume_webhook("tenant-a", body, {"x-x-signature": "bad"}, secret=secret)


def test_permission_findings_detect_unused_expired_revoked_and_unexpected_scope(provider_framework):
    adapter = provider_framework.XReferenceAdapter()
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    grant = adapter.normalize_authorization(
        "tenant-a",
        {
            "authorization_id": "auth-1",
            "external_account_id": "acct-1",
            "grantor_id": "owner-1",
            "scopes": ["tweet.read", "tweet.write", "dm.write"],
            "expires_at": expired,
            "revoked_at": expired,
            "evidence_ref": "evidence:grant:auth-1",
        },
    )
    action = adapter.normalize_action("tenant-a", {"action_type": "content_created", "authorization_id": "auth-1", "external_object_id": "post-1"})

    findings = provider_framework.compute_permission_findings(
        tenant_id="tenant-a",
        grants=[grant],
        actions=[action],
        approved_scope_baselines={"owner-1": {"tweet.read"}},
    )

    assert {finding.finding_type for finding in findings} == {"expired_grant", "revoked_grant_used", "unexpected_new_scope"}
    assert any(finding.severity == "critical" for finding in findings)
    assert all(finding.tenant_id == "tenant-a" for finding in findings)


def test_provider_neutral_graph_projection_uses_tenant_id_and_generic_types(provider_framework):
    adapter = provider_framework.XReferenceAdapter()
    account = adapter.normalize_account("tenant-a", {"external_account_id": "acct-1", "handle": "aether"})
    grant = adapter.normalize_authorization("tenant-a", {"authorization_id": "auth-1", "external_account_id": "acct-1", "scopes": ["tweet.read"]})
    action = adapter.normalize_action("tenant-a", {"action_type": "content_created", "external_object_id": "post-1"})
    verification = adapter.verify_action(action, {"external_object_id": "post-1", "action_type": "content_created"})

    records = provider_framework.build_provider_graph_projection(account, grant, action, verification)

    assert {record["type"] for record in records if record["kind"] == "vertex"} == {"ExternalAccount", "AuthorizationGrant", "ProviderAction", "ProviderVerification"}
    assert all(record["tenantId"] == "tenant-a" for record in records)
    assert not any(record["type"] == "XPost" for record in records)


def test_registry_exposes_x_adapter_metadata(provider_framework):
    metadata = {item.provider_id: item for item in provider_framework.provider_registry.list_metadata()}

    assert "x" in metadata
    assert metadata["x"].verification_support is True
    assert "content_created" in metadata["x"].supported_events
