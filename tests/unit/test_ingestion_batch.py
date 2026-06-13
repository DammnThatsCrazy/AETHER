"""
Unit tests for the canonical POST /v1/batch ingestion endpoint.

Covers:
- Batch envelope validation (1-500 events, required fields)
- Per-event validation (canonical types, timestamp format)
- Sensitive field scrubbing (backend-side defense)
- Tenant-scoped idempotency (duplicate detection, cross-tenant isolation)
- Idempotency key derivation
- Canonical event type registry completeness
- API key not present in sendBeacon URL
- Bronze idempotency key includes tenant_id
"""

from __future__ import annotations

import hashlib
import importlib
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path():
    """Add backend root to sys.path and clean up stale module cache."""
    original = list(sys.path)
    stale_prefixes = (
        "config", "services", "shared", "middleware", "dependencies", "repositories",
    )
    for prefix in stale_prefixes:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in stale_prefixes:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


# ── Canonical event types ────────────────────────────────────────────────────

def test_canonical_event_types_match_typescript():
    """
    Python CANONICAL_EVENT_TYPES must match the TypeScript EventType union.
    This test encodes the expected set. If packages/shared/events.ts changes,
    update this test to match.
    """
    expected = {
        "track", "page", "screen", "heartbeat", "error", "performance", "experiment",
        "journey_started", "journey_paused", "journey_resumed", "journey_continued",
        "journey_completed", "journey_abandoned", "journey_checkpoint",
        "identify", "consent",
        "conversion", "payment_initiated", "payment_completed", "payment_failed",
        "approval_requested", "approval_resolved",
        "entitlement_granted", "entitlement_revoked",
        "access_granted", "access_denied",
        "wallet", "transaction", "contract_action",
        # Agent — legacy
        "agent_task", "agent_decision", "a2h_interaction",
        # Agent — lifecycle (granular)
        "agent_registered", "agent_updated", "agent_authorized", "agent_deauthorized",
        "agent_capability_granted", "agent_capability_revoked",
        "agent_task_created", "agent_task_decomposed", "agent_task_started",
        "agent_task_completed", "agent_task_failed", "agent_tool_called",
        "agent_resource_requested", "agent_delegated_task", "agent_subagent_spawned",
        "agent_policy_evaluated", "agent_handoff", "agent_escalated_to_human",
        "agent_outcome_recorded",
        # x402 — legacy
        "x402_payment",
        # x402 — lifecycle (granular)
        "x402_resource_requested", "x402_payment_required", "x402_quote_received",
        "x402_authorization_requested", "x402_authorization_resolved",
        "x402_payment_intent_created", "x402_payment_submitted", "x402_payment_settled",
        "x402_payment_failed", "x402_payment_timeout", "x402_receipt_verified",
        "x402_access_granted", "x402_access_denied", "x402_refund_or_reversal",
    }
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        assert m.CANONICAL_EVENT_TYPES == expected, (
            "CANONICAL_EVENT_TYPES diverged from packages/shared/events.ts. "
            "Update services/ingestion/batch.py to match."
        )


def test_unknown_event_type_is_rejected():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        # unknown type should not be in canonical set
        assert "custom_unknown_xyz" not in m.CANONICAL_EVENT_TYPES


# ── Sensitive field scrubbing ────────────────────────────────────────────────

def test_scrub_sensitive_fields_removes_private_key():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        props = {"action": "transfer", "private_key": "0xsecret", "amount": 100}
        scrubbed, had = m._scrub_sensitive_fields(props)
        assert scrubbed["private_key"] == "[REDACTED]"
        assert scrubbed["action"] == "transfer"
        assert scrubbed["amount"] == 100
        assert had is True


def test_scrub_sensitive_fields_nested():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        props = {"meta": {"password": "hunter2", "label": "test"}}
        scrubbed, had = m._scrub_sensitive_fields(props)
        assert scrubbed["meta"]["password"] == "[REDACTED]"
        assert scrubbed["meta"]["label"] == "test"
        assert had is True


def test_scrub_sensitive_fields_clean():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        props = {"product_id": "abc", "quantity": 3}
        scrubbed, had = m._scrub_sensitive_fields(props)
        assert scrubbed == props
        assert had is False


def test_scrub_sensitive_fields_api_key():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        props = {"api_key": "ak_live_secret", "user": "alice"}
        scrubbed, had = m._scrub_sensitive_fields(props)
        assert scrubbed["api_key"] == "[REDACTED]"
        assert had is True


def test_scrub_sensitive_fields_seed_phrase():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        for key in ("seedphrase", "seed_phrase", "mnemonic"):
            props = {key: "word1 word2 word3"}
            scrubbed, had = m._scrub_sensitive_fields(props)
            assert scrubbed[key] == "[REDACTED]", f"key {key!r} was not scrubbed"
            assert had is True


# ── Idempotency key ──────────────────────────────────────────────────────────

def test_idempotency_key_is_tenant_scoped():
    """Same event_id from different tenants must produce different keys."""
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        event_id = str(uuid.uuid4())
        key_t1 = m._make_idempotency_key("tenant_A", event_id, "1.0.0")
        key_t2 = m._make_idempotency_key("tenant_B", event_id, "1.0.0")
        assert key_t1 != key_t2, "Same event_id must produce different keys for different tenants"


def test_idempotency_key_stable():
    """Same inputs must always produce the same key."""
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        k1 = m._make_idempotency_key("t1", "evt_abc", "1.0.0")
        k2 = m._make_idempotency_key("t1", "evt_abc", "1.0.0")
        assert k1 == k2


def test_idempotency_key_length():
    """Key must be a 40-char hex string (first 40 chars of SHA-256)."""
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        key = m._make_idempotency_key("t", "e", "v")
        assert len(key) == 40
        assert all(c in "0123456789abcdef" for c in key)


# ── Bronze idempotency key includes tenant_id ────────────────────────────────

def test_bronze_idempotency_key_includes_tenant():
    """
    make_raw_record must include tenant_id in the idempotency hash so two
    tenants with the same provider_record_id never collide.
    """
    with backend_path():
        lake = importlib.import_module("repositories.lake")
        r1 = lake.make_raw_record(
            source="sdk", source_tag="batch:1",
            provider_record_id="event-abc", payload={},
            schema_version="1.0", tenant_id="tenant_A",
        )
        r2 = lake.make_raw_record(
            source="sdk", source_tag="batch:1",
            provider_record_id="event-abc", payload={},
            schema_version="1.0", tenant_id="tenant_B",
        )
        assert r1["idempotency_key"] != r2["idempotency_key"], (
            "Different tenants with same provider_record_id must have different idempotency keys"
        )


def test_bronze_idempotency_key_stable():
    with backend_path():
        lake = importlib.import_module("repositories.lake")
        r1 = lake.make_raw_record(
            source="sdk", source_tag="t",
            provider_record_id="e", payload={},
            tenant_id="tenant_A",
        )
        r2 = lake.make_raw_record(
            source="sdk", source_tag="t",
            provider_record_id="e", payload={},
            tenant_id="tenant_A",
        )
        assert r1["idempotency_key"] == r2["idempotency_key"]


# ── SDK API key transport — no query param leak ──────────────────────────────

def test_web_sdk_no_api_key_in_query_param():
    """
    The sendBeacon path must NOT send the API key as a URL query parameter.
    Regression guard: ensures ?token= is not present in event-queue.ts.
    """
    event_queue_path = (
        ROOT / "packages" / "web" / "src" / "core" / "event-queue.ts"
    )
    source = event_queue_path.read_text(encoding="utf-8")
    assert "?token=" not in source, (
        "sendBeacon must not pass apiKey as ?token= query param. "
        "Use fetch+keepalive instead."
    )
    assert "sendBeacon(" not in source or "apiKey" not in source.split("sendBeacon(")[1].split(")")[0], (
        "sendBeacon call must not reference apiKey directly."
    )


def test_web_sdk_uses_authorization_header():
    """fetch() calls must use Authorization: Bearer header, not query params."""
    event_queue_path = (
        ROOT / "packages" / "web" / "src" / "core" / "event-queue.ts"
    )
    source = event_queue_path.read_text(encoding="utf-8")
    assert "Authorization" in source
    assert "Bearer" in source
    # Ensure the keepalive path uses the header
    assert "keepalive: true" in source


# ── Event family mapping ─────────────────────────────────────────────────────

def test_all_canonical_types_have_family():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        for event_type in m.CANONICAL_EVENT_TYPES:
            family = m._get_event_family(event_type)
            assert family in {"core", "journey", "identity", "consent", "commerce", "wallet", "agent", "x402"}, (
                f"Event type {event_type!r} has unexpected family {family!r}"
            )


def test_all_canonical_types_have_consent_purpose():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        for event_type in m.CANONICAL_EVENT_TYPES:
            assert event_type in m.EVENT_CONSENT_PURPOSE, (
                f"Event type {event_type!r} has no consent purpose mapping"
            )


# ── Pydantic model validation ────────────────────────────────────────────────

def test_base_event_requires_id():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            m.BaseEvent(
                id="",  # min_length=1 → should fail
                type="track",
                timestamp="2024-01-01T00:00:00Z",
                sessionId="s1",
                anonymousId="anon1",
            )


def test_base_event_rejects_invalid_timestamp():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            m.BaseEvent(
                id="evt1",
                type="track",
                timestamp="not-a-date",
                sessionId="s1",
                anonymousId="anon1",
            )


def test_batch_request_max_500():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        from pydantic import ValidationError
        events = [
            m.BaseEvent(
                id=str(i),
                type="track",
                timestamp="2024-01-01T00:00:00Z",
                sessionId="s1",
                anonymousId="anon1",
            )
            for i in range(501)
        ]
        with pytest.raises(ValidationError):
            m.BatchRequest(batch=events, sentAt="2024-01-01T00:00:00Z")


def test_batch_request_min_1():
    with backend_path():
        m = importlib.import_module("services.ingestion.batch")
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            m.BatchRequest(batch=[], sentAt="2024-01-01T00:00:00Z")
