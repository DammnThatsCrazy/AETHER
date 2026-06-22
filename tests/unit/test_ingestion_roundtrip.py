"""Round-trip tests: verify all EventContext fields survive ingestion without dropping.

Tests that the 38-field EventContext model accepts all canonical SDK-emitted fields
and that the sensitive field scrubber correctly redacts nested and list-wrapped values.
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def batch_mod(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        mod = importlib.import_module("services.ingestion.batch")
        yield mod


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# EventContext round-trip
# ---------------------------------------------------------------------------

class TestEventContextFields:
    """All 38+ EventContext fields must parse without validation error."""

    def test_all_core_context_fields(self, batch_mod):
        ctx = batch_mod.EventContext(
            library={"name": "aether-web", "version": "8.9.0"},
            page={"url": "https://example.com", "title": "Home"},
            device={"type": "desktop", "brand": "Apple"},
            os={"name": "macOS", "version": "14.0"},
            network={"type": "wifi"},
            locale="en-US",
            timezone="America/New_York",
            userAgent="Mozilla/5.0",
            ip="1.2.3.4",
            consent={"analytics": True, "marketing": False},
        )
        assert ctx.locale == "en-US"
        assert ctx.library["name"] == "aether-web"

    def test_campaign_and_journey_fields(self, batch_mod):
        ctx = batch_mod.EventContext(
            campaign={"source": "google", "medium": "cpc", "name": "spring"},
            journey={"id": "j-1", "step": "onboarding_complete"},
        )
        assert ctx.campaign["source"] == "google"
        assert ctx.journey["step"] == "onboarding_complete"

    def test_fingerprint_field(self, batch_mod):
        ctx = batch_mod.EventContext(
            fingerprint={"id": "fp-abc123", "confidence": 0.95},
        )
        assert ctx.fingerprint["id"] == "fp-abc123"

    def test_org_and_identity_fields(self, batch_mod):
        ctx = batch_mod.EventContext(
            tenantId="tenant-1",
            orgId="org-1",
            actorId="actor-1",
            actorKind="human",
            beneficiaryActorId="actor-2",
            delegationId="deleg-1",
            delegationScope=["read", "write"],
            identityConfidence=0.98,
        )
        assert ctx.tenantId == "tenant-1"
        assert ctx.identityConfidence == 0.98

    def test_reward_fields(self, batch_mod):
        ctx = batch_mod.EventContext(
            rewardCampaignId="rc-1",
            rewardRuleId="rr-1",
            rewardIdempotencyKey="ikey-1",
            rewardWalletAddress="0xdeadbeef",
        )
        assert ctx.rewardWalletAddress == "0xdeadbeef"

    def test_attribution_and_fraud_fields(self, batch_mod):
        ctx = batch_mod.EventContext(
            attributionResultId="attr-1",
            fraudDecisionId="fraud-1",
            consentSnapshotId="snap-1",
        )
        assert ctx.fraudDecisionId == "fraud-1"

    def test_observability_fields(self, batch_mod):
        ctx = batch_mod.EventContext(
            correlationId="corr-1",
            causationId="cause-1",
            traceId="trace-abc",
            provenance={"source": "web-sdk", "schemaVersion": "1.0.0"},
            semantic={"intent": "purchase"},
            trafficSource={"type": "organic"},
            privacy={"gpcObserved": True},
            sampling={"rate": 0.1},
            sequence={"index": 5, "total": 10},
        )
        assert ctx.traceId == "trace-abc"
        assert ctx.provenance["source"] == "web-sdk"

    def test_impressions_field(self, batch_mod):
        ctx = batch_mod.EventContext(
            impressions=[
                {"contentId": "c-1", "position": 0},
                {"contentId": "c-2", "position": 1},
            ],
        )
        assert len(ctx.impressions) == 2

    def test_unknown_field_rejected(self, batch_mod):
        """extra='forbid' must reject any unrecognized field."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            batch_mod.EventContext(nonExistentField="boom")


# ---------------------------------------------------------------------------
# Batch consent — Optional, not required
# ---------------------------------------------------------------------------

def _make_batch_event(event_type: str = "track", event_id: str = "e-1") -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "timestamp": _ts(),
        "sessionId": "sess-1",
        "anonymousId": "anon-1",
        "properties": {},
    }


class TestBatchConsentOptional:
    def test_batch_without_consents_field_is_valid(self, batch_mod):
        """BatchRequest.consents is Optional — omitting it must not raise."""
        req = batch_mod.BatchRequest(
            batch=[_make_batch_event()],
            sentAt=_ts(),
        )
        assert req.consents is None

    def test_batch_with_consents_field_is_valid(self, batch_mod):
        req = batch_mod.BatchRequest(
            batch=[_make_batch_event()],
            sentAt=_ts(),
            consents=["analytics", "marketing"],
        )
        assert req.consents == ["analytics", "marketing"]


# ---------------------------------------------------------------------------
# Sensitive field scrubbing — recursive
# ---------------------------------------------------------------------------

class TestSensitiveFieldScrubbing:
    def _scrub(self, batch_mod, payload):
        # _scrub_sensitive_fields returns (scrubbed_value, had_sensitive_bool)
        result, _ = batch_mod._scrub_sensitive_fields(payload)
        return result

    def test_top_level_password_redacted(self, batch_mod):
        result = self._scrub(batch_mod, {"password": "hunter2", "name": "Alice"})
        assert result["password"] == "[REDACTED]"
        assert result["name"] == "Alice"

    def test_nested_secret_redacted(self, batch_mod):
        result = self._scrub(batch_mod, {"user": {"api_key": "sk-abc", "email": "a@b.com"}})
        assert result["user"]["api_key"] == "[REDACTED]"
        assert result["user"]["email"] == "a@b.com"

    def test_list_of_dicts_scrubbed(self, batch_mod):
        result = self._scrub(batch_mod, {
            "items": [
                {"name": "card", "card_number": "4111-1111"},
                {"name": "plain", "value": 42},
            ]
        })
        assert result["items"][0]["card_number"] == "[REDACTED]"
        assert result["items"][1]["value"] == 42

    def test_form_value_redacted(self, batch_mod):
        result = self._scrub(batch_mod, {"form_value": "my secret text"})
        assert result["form_value"] == "[REDACTED]"

    def test_iban_redacted(self, batch_mod):
        result = self._scrub(batch_mod, {"iban": "GB29 NWBK 6016 1331 9268 19"})
        assert result["iban"] == "[REDACTED]"

    def test_non_sensitive_passthrough(self, batch_mod):
        result = self._scrub(batch_mod, {"revenue": 9.99, "items": [1, 2, 3]})
        assert result["revenue"] == 9.99
        assert result["items"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# execution_by_aether invariant
# ---------------------------------------------------------------------------

class TestExecutionByAetherInvariant:
    def test_rejection_code_is_stable(self, batch_mod):
        """The REJECT_EXECUTION_CLAIM constant must be present and non-empty."""
        assert hasattr(batch_mod, "REJECT_EXECUTION_CLAIM")
        assert batch_mod.REJECT_EXECUTION_CLAIM
        assert "execution" in batch_mod.REJECT_EXECUTION_CLAIM.lower()

    def test_execution_property_not_scrubbed(self, batch_mod):
        """execution_by_aether is a semantics field, not sensitive — must not be redacted."""
        result, _ = batch_mod._scrub_sensitive_fields(
            {"execution_by_aether": True, "action": "transfer"}
        )
        # The value must still be True (scrubber doesn't touch it — rejection logic does)
        assert result["execution_by_aether"] is True

    def test_base_event_allows_execution_property(self, batch_mod):
        """BaseEvent accepts execution_by_aether in properties — rejection happens at processing."""
        event = batch_mod.BaseEvent(
            id="e-exec",
            type="track",
            timestamp=_ts(),
            sessionId="sess-1",
            anonymousId="anon-1",
            properties={"execution_by_aether": True},
        )
        assert event.properties["execution_by_aether"] is True
