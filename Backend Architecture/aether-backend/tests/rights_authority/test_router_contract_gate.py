"""Live router contract + blueprint §13 activation gate.

Two integration guards on the (now-mounted) /v1/rights surface:

1. Request-model parity with the resolver: ``source``/``purpose``/``destination``
   are required scalar strings (mirroring ``RightsDecisionRequest``), so a live
   call can never build a resolver request from a multi-ref list or a missing
   purpose/destination.
2. Rollout OFF ⇒ the authority is inert: every handler 503s until an operator
   activates a phase (``RIGHTS_AUTHORITY_ROLLOUT`` != off).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from types import SimpleNamespace

from services.rights_authority import routes
from services.rights_authority.routes import EffectiveRightsResolveRequest
from services.rights_authority.rollout import RolloutMode, configure_rollout, reset_rollout


class TestRequestModelParity:
    def test_scalar_required_fields_accepted(self):
        body = EffectiveRightsResolveRequest(
            tenant_id="t1",
            source="src_1",
            requested_use="transform",
            purpose="personalization",
            destination="profile",
        )
        assert body.source == "src_1"
        assert body.artifact is None
        assert body.as_of is None

    def test_multi_ref_source_list_rejected(self):
        # Regression: the route used to accept source as list[str], which the
        # resolver (RightsDecisionRequest.source_id: str) cannot consume.
        with pytest.raises(ValidationError):
            EffectiveRightsResolveRequest(
                tenant_id="t1",
                source=["src_1", "src_2"],
                requested_use="transform",
                purpose="personalization",
                destination="profile",
            )

    def test_missing_purpose_rejected(self):
        with pytest.raises(ValidationError):
            EffectiveRightsResolveRequest(
                tenant_id="t1",
                source="src_1",
                requested_use="transform",
                destination="profile",
            )


class TestActivationGate:
    def teardown_method(self):
        reset_rollout()

    def test_off_by_default_is_inert(self):
        assert routes._ensure_active is not None
        with pytest.raises(HTTPException) as exc:
            routes._ensure_active()
        assert exc.value.status_code == 503
        assert "rollout=off" in exc.value.detail

    def test_activated_mode_allows(self):
        configure_rollout(RolloutMode.SHADOW)
        # No exception = gate passes.
        routes._ensure_active()

    def test_enforce_mode_allows(self):
        configure_rollout(RolloutMode.ENFORCE)
        routes._ensure_active()


@pytest.mark.asyncio
async def test_shadow_and_warn_resolution_are_observational(monkeypatch):
    """Non-enforce modes expose the evaluated decision without binding it."""
    body = routes.EffectiveRightsResolveRequest(
        tenant_id="t1", source="source-1", requested_use="export",
        purpose="analytics", destination="tenant",
    )
    request = SimpleNamespace(
        state=SimpleNamespace(
            tenant=SimpleNamespace(
                tenant_id="t1", user_id="u1", permissions=["read"], role="viewer",
            )
        ),
        client=None,
        headers={},
    )

    async def _resolve(**_kwargs):
        return {"tenant_id": "t1", "allowed": False, "reason_codes": ["denied"]}

    monkeypatch.setattr(
        "services.rights_authority.resolver.effective_rights_resolver",
        SimpleNamespace(resolve=_resolve),
    )
    for mode in (RolloutMode.SHADOW, RolloutMode.WARN):
        configure_rollout(mode)
        result = await routes.resolve_effective_decision(body, request)
        data = result["data"]
        assert data["observed"] is True
        assert data["enforced"] is False
        assert data["rollout"] == mode.value
        if mode is RolloutMode.WARN:
            assert data["warnings"]
