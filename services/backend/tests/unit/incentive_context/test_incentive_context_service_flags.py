"""Runtime facade flag gating (M5 is OFF by default).

The facade is the runtime emission point: with Social360 disabled it returns
``None`` (consumers treat the activity as NOT incentive-assessed — never as
organic). Env wins so tests need not import ``config.settings``; the settings
fallback is itself fail-closed (returns False when the flag/import is absent).
"""

from __future__ import annotations

import asyncio

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from services.incentive_context.service import (  # noqa: E402
    IncentiveContextService,
    campaign_evidence_from_record,
    incentive_context_enabled,
    social360_enabled,
)
from services.incentive_context.resolver import IncentiveAssessment  # noqa: E402


@dataclass
class _FakeResult:
    status: str = "resolved"
    campaign_id: Optional[str] = None
    method: Optional[str] = None
    confidence: Optional[Decimal] = None


class _FakeCampaignResolver:
    def __init__(self, campaign_id: str = "cmp-fake") -> None:
        self.calls = 0
        self._campaign_id = campaign_id

    async def resolve_one(self, tenant_id: str, **kwargs: object) -> _FakeResult:
        self.calls += 1
        return _FakeResult(
            campaign_id=self._campaign_id, method="canonical_uuid", confidence=Decimal("1.00")
        )


def _evidence(campaign_id: Optional[str] = None) -> dict:
    evidence = {
        "social_identity_ref": "si-1",
        "interaction_ref": "in-1",
        "occurred_at": "2026-05-01T00:00:00Z",
        "source_scope": "tenant_connected",
        "evidence_basis": "provider_api",
    }
    if campaign_id:
        evidence["canonical_campaign_id"] = campaign_id
    return evidence


def test_default_flags_are_off(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AETHER_SOCIAL360_ENABLED", raising=False)
    monkeypatch.delenv("AETHER_INCENTIVE_CONTEXT_ENABLED", raising=False)
    assert social360_enabled() is False
    assert incentive_context_enabled() is False


def test_flags_accept_explicit_env_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AETHER_SOCIAL360_ENABLED", "true")
    monkeypatch.delenv("AETHER_INCENTIVE_CONTEXT_ENABLED", raising=False)
    assert social360_enabled() is True
    assert incentive_context_enabled() is True


def test_incentive_specific_flag_enables_m5(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Even if the umbrella Social360 flag is absent, the M5-specific flag on is
    # sufficient (explicit opt-in); both default off.
    monkeypatch.delenv("AETHER_SOCIAL360_ENABLED", raising=False)
    monkeypatch.setenv("AETHER_INCENTIVE_CONTEXT_ENABLED", "1")
    assert incentive_context_enabled() is True


def test_facade_returns_none_when_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AETHER_SOCIAL360_ENABLED", raising=False)
    monkeypatch.delenv("AETHER_INCENTIVE_CONTEXT_ENABLED", raising=False)
    svc = IncentiveContextService()
    assert svc.enabled is False
    out = asyncio.run(svc.resolve("ten-1", evidence=_evidence()))
    assert out is None


def test_facade_resolves_when_enabled_with_campaign_lookup(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AETHER_SOCIAL360_ENABLED", raising=False)
    monkeypatch.delenv("AETHER_INCENTIVE_CONTEXT_ENABLED", raising=False)
    resolver = _FakeCampaignResolver()
    svc = IncentiveContextService(campaign_resolver=resolver, enabled=True)
    assert svc.enabled is True

    async def _run() -> None:
        ctx = await svc.resolve(
            "ten-1",
            evidence=_evidence(campaign_id="00000000-0000-0000-0000-000000000abc"),
            campaign_record={
                "campaign_id": "00000000-0000-0000-0000-000000000abc",
                "name": "Q2 Creator Reward",
                "status": "active",
                "properties": {"reward_program": True, "reward_condition": "per_interaction"},
            },
            assessment=IncentiveAssessment(scope="window_bounded"),
            timeline=["2026-05-01T00:00:00Z"],
        )
        assert ctx is not None
        assert resolver.calls == 1  # Campaign360 resolver was consumed
        assert ctx.campaign_ref == "cmp-fake"
        assert ctx.status == "observed"

    asyncio.run(_run())


def test_campaign_evidence_from_record_preserves_unknown_reward() -> None:
    # reward_program absent in properties stays None (unknown) — never False.
    row = {
        "campaign_id": "cmp-1",
        "name": "Brand Lift",
        "status": "active",
        "properties": {},
    }
    ev = campaign_evidence_from_record(row, campaign_ref="cmp-1")
    assert ev.reward_program is None
    assert ev.reward_condition is None

    ev2 = campaign_evidence_from_record(
        {**row, "properties": {"reward_program": False, "reward_condition": "x"}},
        campaign_ref="cmp-1",
    )
    assert ev2.reward_program is False
    assert ev2.reward_condition == "x"
