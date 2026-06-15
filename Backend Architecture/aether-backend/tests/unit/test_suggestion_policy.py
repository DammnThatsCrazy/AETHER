"""Unit tests for the Suggestion policy evaluation and tenant redaction."""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from unittest.mock import MagicMock

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionPolicyDecision,
    SuggestionSource,
    SuggestionSubject,
)
from services.suggestions.policy import (
    OPERATOR_ONLY_FIELDS,
    SENSITIVE_KEYS,
    evaluate_suggestion_policy,
    redact_for_tenant,
    requires_approval,
)


def _run(coro):
    return asyncio.run(coro)


def _make_create(**overrides) -> SuggestionCreate:
    base = {
        "tenant_id": "tenant_abc",
        "subject": SuggestionSubject(kind="entity", id="ent_1"),
        "source": SuggestionSource.RULE,
        "suggestion_class": SuggestionClass.DATA_QUALITY,
        "title": "Test Suggestion",
        "summary": "A test summary",
        "what": "What is happening",
        "why": "Why it matters",
        "impact": "Impact description",
        "confidence_score": 0.8,
    }
    base.update(overrides)
    return SuggestionCreate(**base)


def _make_tenant(tenant_id: str = "tenant_abc") -> MagicMock:
    tenant = MagicMock()
    tenant.tenant_id = tenant_id
    return tenant


# ---------------------------------------------------------------------------
# requires_approval function
# ---------------------------------------------------------------------------

def test_security_class_requires_approval():
    result = requires_approval(SuggestionClass.SECURITY, risk_score=None, reversible=None)
    assert result is True


def test_governance_class_requires_approval():
    result = requires_approval(SuggestionClass.GOVERNANCE, risk_score=None, reversible=None)
    assert result is True


def test_identity_class_requires_approval():
    result = requires_approval(SuggestionClass.IDENTITY, risk_score=None, reversible=None)
    assert result is True


def test_reliability_class_requires_approval():
    result = requires_approval(SuggestionClass.RELIABILITY, risk_score=None, reversible=None)
    assert result is True


def test_low_risk_reversible_data_quality_does_not_require_approval():
    result = requires_approval(
        SuggestionClass.DATA_QUALITY,
        risk_score=0.1,
        reversible=True,
    )
    assert result is False


def test_high_risk_score_requires_approval():
    result = requires_approval(
        SuggestionClass.DATA_QUALITY,
        risk_score=0.7,
        reversible=True,
    )
    assert result is True


def test_irreversible_action_requires_approval():
    result = requires_approval(
        SuggestionClass.DATA_QUALITY,
        risk_score=0.1,
        reversible=False,
    )
    assert result is True


def test_none_risk_reversible_data_quality_does_not_require_approval():
    result = requires_approval(
        SuggestionClass.DATA_QUALITY,
        risk_score=None,
        reversible=None,
    )
    assert result is False


# ---------------------------------------------------------------------------
# evaluate_suggestion_policy
# ---------------------------------------------------------------------------

def test_evaluate_policy_returns_policy_decision():
    create = _make_create()
    tenant = _make_tenant("tenant_abc")
    decision = _run(evaluate_suggestion_policy(create, tenant))
    assert isinstance(decision, SuggestionPolicyDecision)


def test_evaluate_policy_security_class_requires_approval_true():
    create = _make_create(suggestion_class=SuggestionClass.SECURITY)
    tenant = _make_tenant("tenant_abc")
    decision = _run(evaluate_suggestion_policy(create, tenant))
    assert decision.requires_approval is True
    assert decision.allowed is True


def test_evaluate_policy_governance_class_requires_approval_true():
    create = _make_create(suggestion_class=SuggestionClass.GOVERNANCE)
    tenant = _make_tenant("tenant_abc")
    decision = _run(evaluate_suggestion_policy(create, tenant))
    assert decision.requires_approval is True


def test_evaluate_policy_low_risk_reversible_data_quality_requires_approval_false():
    create = _make_create(
        suggestion_class=SuggestionClass.DATA_QUALITY,
        risk_score=0.1,
        reversible=True,
    )
    tenant = _make_tenant("tenant_abc")
    decision = _run(evaluate_suggestion_policy(create, tenant))
    assert decision.requires_approval is False


def test_evaluate_policy_tenant_isolation_mismatch_returns_not_allowed():
    create = _make_create(tenant_id="tenant_abc")
    tenant = _make_tenant("tenant_xyz")
    decision = _run(evaluate_suggestion_policy(create, tenant))
    assert decision.allowed is False
    assert "tenant_isolation" in decision.policies


def test_evaluate_policy_has_decision_id():
    create = _make_create()
    tenant = _make_tenant("tenant_abc")
    decision = _run(evaluate_suggestion_policy(create, tenant))
    assert decision.decision_id
    assert len(decision.decision_id) > 0


def test_evaluate_policy_has_evaluated_at():
    create = _make_create()
    tenant = _make_tenant("tenant_abc")
    decision = _run(evaluate_suggestion_policy(create, tenant))
    assert decision.evaluated_at


def test_evaluate_policy_default_policy_when_no_risks():
    create = _make_create()
    tenant = _make_tenant("tenant_abc")
    decision = _run(evaluate_suggestion_policy(create, tenant))
    assert "default_suggestion_policy" in decision.policies


def test_evaluate_policy_high_risk_score_policy_included():
    create = _make_create(risk_score=0.75)
    tenant = _make_tenant("tenant_abc")
    decision = _run(evaluate_suggestion_policy(create, tenant))
    assert "high_risk_score_approval" in decision.policies


def test_evaluate_policy_irreversible_policy_included():
    create = _make_create(reversible=False)
    tenant = _make_tenant("tenant_abc")
    decision = _run(evaluate_suggestion_policy(create, tenant))
    assert "irreversible_action_approval" in decision.policies


# ---------------------------------------------------------------------------
# redact_for_tenant
# ---------------------------------------------------------------------------

def test_redact_for_tenant_removes_operator_notes():
    suggestion = {
        "id": "sug_1",
        "title": "Test",
        "operator_notes": "Private notes for operator only",
        "status": "suggested",
    }
    result = redact_for_tenant(suggestion)
    assert "operator_notes" not in result


def test_redact_for_tenant_removes_audit_trail():
    suggestion = {
        "id": "sug_1",
        "audit_trail": [{"action": "created"}],
        "status": "suggested",
    }
    result = redact_for_tenant(suggestion)
    assert "audit_trail" not in result


def test_redact_for_tenant_removes_policy_decision():
    suggestion = {
        "id": "sug_1",
        "policy_decision": {"allowed": True},
        "status": "suggested",
    }
    result = redact_for_tenant(suggestion)
    assert "policy_decision" not in result


def test_redact_for_tenant_removes_source_ref():
    suggestion = {
        "id": "sug_1",
        "source_ref": {"id": "rec_123", "service": "engine"},
        "status": "suggested",
    }
    result = redact_for_tenant(suggestion)
    assert "source_ref" not in result


def test_redact_for_tenant_removes_lineage_event_ids():
    suggestion = {
        "id": "sug_1",
        "lineage_event_ids": ["evt_1", "evt_2"],
        "status": "suggested",
    }
    result = redact_for_tenant(suggestion)
    assert "lineage_event_ids" not in result


def test_redact_for_tenant_redacts_api_key_deeply():
    suggestion = {
        "id": "sug_1",
        "evidence": [{"api_key": "secret123", "type": "event"}],
        "status": "suggested",
    }
    result = redact_for_tenant(suggestion)
    assert result["evidence"][0]["api_key"] == "[REDACTED]"
    assert result["evidence"][0]["type"] == "event"


def test_redact_for_tenant_redacts_token_field():
    suggestion = {
        "id": "sug_1",
        "metadata": {"token": "my_token_value", "name": "safe_name"},
    }
    result = redact_for_tenant(suggestion)
    assert result["metadata"]["token"] == "[REDACTED]"
    assert result["metadata"]["name"] == "safe_name"


def test_redact_for_tenant_redacts_secret_field():
    suggestion = {
        "id": "sug_1",
        "payload": {"secret": "s3cr3t", "other": "visible"},
    }
    result = redact_for_tenant(suggestion)
    assert result["payload"]["secret"] == "[REDACTED]"


def test_redact_for_tenant_preserves_safe_fields():
    suggestion = {
        "id": "sug_1",
        "title": "A safe title",
        "status": "suggested",
        "priority": "P2",
    }
    result = redact_for_tenant(suggestion)
    assert result["id"] == "sug_1"
    assert result["title"] == "A safe title"
    assert result["status"] == "suggested"
    assert result["priority"] == "P2"


def test_redact_for_tenant_removes_all_operator_only_fields():
    suggestion = {k: "value" for k in OPERATOR_ONLY_FIELDS}
    suggestion["id"] = "sug_1"
    result = redact_for_tenant(suggestion)
    for field in OPERATOR_ONLY_FIELDS:
        assert field not in result
    assert result["id"] == "sug_1"
