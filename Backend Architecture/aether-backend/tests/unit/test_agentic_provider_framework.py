from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("AETHER_ENV", "local")

import hmac
import json

import pytest

from services.agentic_observability.provider_framework import (
    AuthorizationGrantRecord,
    ExternalAccountRecord,
    PermissionFinding,
    ProviderActionRecord,
    ProviderHealthRecord,
    ProviderRegistry,
    ProviderVerificationRecord,
    ProviderVerificationStatus,
    XReferenceAdapter,
    build_provider_graph_projection,
    compute_permission_findings,
    provider_registry,
)


def test_x_reference_adapter_is_read_only():
    adapter = XReferenceAdapter()
    assert adapter.metadata.read_only is True
    assert adapter.metadata.provider_id == "x_reference"
    assert adapter.metadata.webhook_supported is True


def test_normalize_account():
    adapter = XReferenceAdapter()
    raw = {
        "id": "acc-1",
        "tenant_id": "t-1",
        "external_user_id": "ext-u-1",
        "scopes": ["read"],
    }
    account = adapter.normalize_account(raw)
    assert account.account_id == "acc-1"
    assert account.external_account_id == "ext-u-1"
    assert account.provider_id == "x_reference"
    assert account.account_type == "x_user"


def test_normalize_authorization():
    adapter = XReferenceAdapter()
    raw = {"grant_id": "g-1", "tenant_id": "t-1", "scopes": ["read", "write.posts"]}
    grant = adapter.normalize_authorization(raw)
    assert grant.grant_id == "g-1"
    assert "write.posts" in grant.scopes
    assert grant.provider_id == "x_reference"
    assert grant.is_active is True


def test_scope_hash_is_order_stable():
    adapter = XReferenceAdapter()
    g1 = adapter.normalize_authorization(
        {"grant_id": "g-1", "tenant_id": "t-1", "scopes": ["read", "write"]}
    )
    g2 = adapter.normalize_authorization(
        {"grant_id": "g-2", "tenant_id": "t-1", "scopes": ["write", "read"]}
    )
    assert g1.scope_hash == g2.scope_hash


def test_normalize_action():
    adapter = XReferenceAdapter()
    raw = {"action_id": "a-1", "action_type": "post", "scopes_used": ["write.posts"]}
    action = adapter.normalize_action(raw)
    assert action.action_id == "a-1"
    assert action.action_type == "post"


def test_normalize_object():
    adapter = XReferenceAdapter()
    raw = {"object_id": "obj-1", "object_type": "tweet"}
    obj = adapter.normalize_object(raw)
    assert obj.object_id == "obj-1"
    assert obj.object_type == "tweet"


def test_verify_action_confirmed():
    adapter = XReferenceAdapter()
    action = ProviderActionRecord(action_id="a-1", provider_id="x_reference")
    snapshot = {"actions": [{"action_id": "a-1"}]}
    result = adapter.verify_action(action, snapshot)
    assert result.status == ProviderVerificationStatus.CONFIRMED
    assert result.evidence["matched"] is True


def test_verify_action_unverified_when_not_in_snapshot():
    adapter = XReferenceAdapter()
    action = ProviderActionRecord(action_id="a-99", provider_id="x_reference")
    result = adapter.verify_action(action, {"actions": []})
    assert result.status == ProviderVerificationStatus.UNVERIFIED
    assert result.evidence["matched"] is False


def test_consume_webhook_valid_hmac():
    adapter = XReferenceAdapter()
    body = json.dumps({"event": "test"}).encode()
    secret = "mysecret"
    sig = "sha256=" + hmac.new(secret.encode(), body, "sha256").hexdigest()
    result = adapter.consume_webhook("t-1", body, {"x-twitter-signature": sig}, secret)
    assert result["tenant_id"] == "t-1"
    assert result["provider"] == "x_reference"
    assert result["raw"]["event"] == "test"


def test_consume_webhook_invalid_hmac_rejected():
    adapter = XReferenceAdapter()
    body = json.dumps({"event": "test"}).encode()
    with pytest.raises(ValueError, match="HMAC"):
        adapter.consume_webhook("t-1", body, {"x-twitter-signature": "sha256=bad"}, "secret")


def test_consume_webhook_no_secret_passes():
    adapter = XReferenceAdapter()
    body = json.dumps({"event": "test"}).encode()
    result = adapter.consume_webhook("t-1", body, {}, "")
    assert result["tenant_id"] == "t-1"


def test_health_check_returns_healthy():
    adapter = XReferenceAdapter()
    health = adapter.health_check()
    assert health.healthy is True
    assert health.provider_id == "x_reference"
    assert health.checked_at is not None


def test_provider_registry_register_and_get():
    registry = ProviderRegistry()
    adapter = XReferenceAdapter()
    registry.register(adapter)
    assert registry.get("x_reference") is adapter
    assert len(registry.list_metadata()) == 1
    assert registry.list_metadata()[0].provider_id == "x_reference"


def test_provider_registry_get_missing_returns_none():
    registry = ProviderRegistry()
    assert registry.get("nonexistent") is None


def test_global_registry_has_x_reference():
    assert provider_registry.get("x_reference") is not None
    assert provider_registry.get("x_reference").metadata.read_only is True


def test_compute_permission_findings_expired_grant():
    grant = AuthorizationGrantRecord(
        grant_id="g-1",
        tenant_id="t-1",
        provider_id="x_reference",
        scopes=["read"],
        expires_at="2020-01-01T00:00:00",
        is_active=True,
    )
    findings = compute_permission_findings("t-1", [grant], [], {})
    types = [f.finding_type for f in findings]
    assert "expired_grant" in types


def test_compute_permission_findings_write_scope_unused():
    grant = AuthorizationGrantRecord(
        grant_id="g-1",
        tenant_id="t-1",
        provider_id="x_reference",
        scopes=["read", "write.posts"],
        is_active=True,
    )
    findings = compute_permission_findings("t-1", [grant], [], {})
    types = [f.finding_type for f in findings]
    assert "write_scope_unused" in types


def test_compute_permission_findings_unexpected_new_scope():
    grant = AuthorizationGrantRecord(
        grant_id="g-1",
        tenant_id="t-1",
        provider_id="x_reference",
        scopes=["read", "dm.write"],
        is_active=True,
    )
    findings = compute_permission_findings("t-1", [grant], [], {"g-1": ["read"]})
    types = [f.finding_type for f in findings]
    assert "unexpected_new_scope" in types


def test_compute_permission_findings_revoked_grant_used():
    grant = AuthorizationGrantRecord(
        grant_id="g-1",
        tenant_id="t-1",
        provider_id="x_reference",
        scopes=["read"],
        revoked_at="2025-01-01T00:00:00",
        is_active=False,
        agent_id="agent-1",
    )
    action = ProviderActionRecord(
        action_id="a-1",
        provider_id="x_reference",
        agent_id="agent-1",
        observed_at="2025-06-01T00:00:00",
    )
    findings = compute_permission_findings("t-1", [grant], [action], {})
    types = [f.finding_type for f in findings]
    assert "revoked_grant_used" in types


def test_build_provider_graph_projection_structure():
    account = ExternalAccountRecord(
        account_id="a-1",
        provider_id="x_reference",
        tenant_id="t-1",
        external_account_id="ext-1",
    )
    grant = AuthorizationGrantRecord(
        grant_id="g-1", tenant_id="t-1", provider_id="x_reference", scopes=["read"]
    )
    action = ProviderActionRecord(action_id="act-1", provider_id="x_reference")
    verification = ProviderVerificationRecord(
        verification_id="v-1",
        provider_id="x_reference",
        status=ProviderVerificationStatus.CONFIRMED,
    )
    nodes = build_provider_graph_projection(account, grant, action, verification)
    types = [n["type"] for n in nodes]
    assert "vertex" in types
    assert "edge" in types
    assert len(nodes) >= 4
    vertex_ids = [n.get("vertex_id") for n in nodes if n["type"] == "vertex"]
    assert "account:a-1" in vertex_ids
    assert "grant:g-1" in vertex_ids
