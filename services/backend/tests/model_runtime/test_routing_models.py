"""Routing/policy data model tests — modes, entitlements, fallbacks, audit."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.model_runtime.models import ModelProvider
from services.model_runtime.routing.models import (
    EntitlementDecision,
    RouteAuditEntry,
    RouteSelection,
    RoutingMode,
    RoutingNotEntitled,
    RoutingPolicyViolation,
    RoutingRequest,
    RoutingResolutionError,
    RoutingUnavailable,
)
from shared.model_governance.generated_task_profiles import ROUTING_MODES


def test_routing_mode_values_match_generated_registry():
    # Every generated ROUTING_MODES value must string-match an enum member.
    assert tuple(m.value for m in RoutingMode) == ROUTING_MODES
    assert set(m.value for m in RoutingMode) == set(ROUTING_MODES)
    # And the enum is str-backed so values coerce cleanly to/from strings.
    assert RoutingMode.AUTO.value == "auto"
    assert RoutingMode.TENANT_DEFAULT.value == "tenant_default"
    assert RoutingMode.EXPLICIT.value == "explicit"
    assert RoutingMode.POLICY_REQUIRED.value == "policy_required"
    assert isinstance(RoutingMode.AUTO, str)


def test_entitlement_decision_roundtrip():
    decision = EntitlementDecision(
        model_id="claude-haiku-4-5-20251001",
        tenant_id="tenant-acme",
        entitled=True,
        reason="on tenant allowlist",
    )
    dumped = decision.model_dump()
    assert dumped["model_id"] == "claude-haiku-4-5-20251001"
    assert dumped["tenant_id"] == "tenant-acme"
    assert dumped["entitled"] is True
    assert dumped["reason"] == "on tenant allowlist"
    restored = EntitlementDecision.model_validate(dumped)
    assert restored == decision


def test_route_selection_roundtrip():
    selection = RouteSelection(
        model_id="claude-haiku-4-5-20251001",
        provider=ModelProvider.ANTHROPIC,
        mode=RoutingMode.AUTO,
        entitled=True,
        fallback=False,
        fallback_reason=None,
    )
    dumped = selection.model_dump()
    assert dumped["model_id"] == "claude-haiku-4-5-20251001"
    assert dumped["provider"] == ModelProvider.ANTHROPIC
    assert dumped["mode"] == RoutingMode.AUTO
    assert dumped["entitled"] is True
    assert dumped["fallback"] is False
    assert dumped["fallback_reason"] is None
    restored = RouteSelection.model_validate(dumped)
    assert restored == selection


def test_route_selection_fallback():
    selection = RouteSelection(
        model_id="claude-haiku-4-5-20251001",
        provider=ModelProvider.ANTHROPIC,
        mode=RoutingMode.EXPLICIT,
        entitled=True,
        fallback=True,
        fallback_reason="requested model over budget; fell back to default",
    )
    assert selection.fallback is True
    assert selection.fallback_reason.startswith("requested model over budget")
    assert selection.mode == RoutingMode.EXPLICIT


def test_route_audit_entry_roundtrip():
    entry = RouteAuditEntry(
        tenant_id="tenant-acme",
        profile_id="grounded_answer_synthesis",
        requested_model="claude-opus-5",
        selected_model="claude-haiku-4-5-20251001",
        mode=RoutingMode.AUTO,
        entitled=True,
        fallback=True,
        fallback_reason="requested model unavailable",
        decision_ms=3.5,
        correlation_id="corr-123",
    )
    dumped = entry.model_dump()
    assert dumped["tenant_id"] == "tenant-acme"
    assert dumped["profile_id"] == "grounded_answer_synthesis"
    assert dumped["requested_model"] == "claude-opus-5"
    assert dumped["selected_model"] == "claude-haiku-4-5-20251001"
    assert dumped["mode"] == RoutingMode.AUTO
    assert dumped["entitled"] is True
    assert dumped["fallback"] is True
    assert dumped["fallback_reason"] == "requested model unavailable"
    assert dumped["decision_ms"] == 3.5
    assert dumped["correlation_id"] == "corr-123"
    restored = RouteAuditEntry.model_validate(dumped)
    assert restored == entry


def test_route_audit_entry_defaults_and_nullables():
    # profile_id / requested_model / fallback_reason are required-but-nullable;
    # correlation_id defaults to None.
    entry = RouteAuditEntry(
        tenant_id="tenant-acme",
        profile_id=None,
        requested_model=None,
        selected_model="gpt-4o-mini",
        mode=RoutingMode.TENANT_DEFAULT,
        entitled=False,
        fallback=True,
        fallback_reason="tenant default not entitled",
        decision_ms=0.0,
    )
    assert entry.profile_id is None
    assert entry.requested_model is None
    assert entry.fallback_reason == "tenant default not entitled"
    assert entry.correlation_id is None


def test_routing_request_roundtrip():
    req = RoutingRequest(
        tenant_id="tenant-acme",
        profile_id="entity_classification",
        mode=RoutingMode.EXPLICIT,
        requested_model="gpt-4o-mini",
        tenant_default_model="claude-haiku-4-5-20251001",
        entitled_model_ids={"gpt-4o-mini", "claude-haiku-4-5-20251001"},
    )
    dumped = req.model_dump()
    assert dumped["tenant_id"] == "tenant-acme"
    assert dumped["profile_id"] == "entity_classification"
    assert dumped["mode"] == RoutingMode.EXPLICIT
    assert dumped["requested_model"] == "gpt-4o-mini"
    assert dumped["tenant_default_model"] == "claude-haiku-4-5-20251001"
    assert dumped["entitled_model_ids"] == {"gpt-4o-mini", "claude-haiku-4-5-20251001"}
    restored = RoutingRequest.model_validate(dumped)
    assert restored == req
    assert restored.entitled_model_ids == {"gpt-4o-mini", "claude-haiku-4-5-20251001"}


def test_routing_request_defaults():
    # mode None -> profile default/auto; optional fields default to None.
    req = RoutingRequest(tenant_id="tenant-acme")
    assert req.profile_id is None
    assert req.mode is None
    assert req.requested_model is None
    assert req.tenant_default_model is None
    assert req.entitled_model_ids is None


def test_entitlement_decision_is_frozen():
    decision = EntitlementDecision(
        model_id="claude-haiku-4-5-20251001",
        tenant_id="tenant-acme",
        entitled=True,
        reason="on tenant allowlist",
    )
    with pytest.raises(ValidationError):
        decision.entitled = False


def test_route_selection_is_frozen():
    selection = RouteSelection(
        model_id="claude-haiku-4-5-20251001",
        provider=ModelProvider.ANTHROPIC,
        mode=RoutingMode.AUTO,
        entitled=True,
        fallback=False,
        fallback_reason=None,
    )
    with pytest.raises(ValidationError):
        selection.fallback = True


def test_route_audit_entry_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        RouteAuditEntry(
            tenant_id="tenant-acme",
            profile_id=None,
            requested_model=None,
            selected_model="gpt-4o-mini",
            mode=RoutingMode.AUTO,
            entitled=True,
            fallback=False,
            fallback_reason=None,
            decision_ms=1.0,
            bogus=1,
        )


def test_routing_request_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        RoutingRequest(tenant_id="tenant-acme", api_key="sekret")


def test_routing_resolution_error_hierarchy():
    assert issubclass(RoutingNotEntitled, RoutingResolutionError)
    assert issubclass(RoutingUnavailable, RoutingResolutionError)
    assert issubclass(RoutingPolicyViolation, RoutingResolutionError)
    assert issubclass(RoutingResolutionError, Exception)
