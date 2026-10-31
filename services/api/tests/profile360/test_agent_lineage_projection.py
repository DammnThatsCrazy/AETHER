"""AO-7: Profile360 Agent Activity / Delegation projection (summary only)."""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from identity.profile.agent_lineage import (
    COHORT_NAVIGATION,
    compose_agent_activity,
)
from identity.profile.composer import ProfileComposer
from shared.agent_lineage.models import Disclosure, LineageSummary
from shared.graph.graph import GraphClient

TENANT = "tenant-a"
PRINCIPAL = "human-1"


def _run(coro):
    return asyncio.run(coro)


def _summary(**overrides) -> LineageSummary:
    base = dict(
        tenant_id=TENANT,
        principal_entity_id=PRINCIPAL,
        agent_instances=318_902,
        agent_runs=4_700_000,
        active_agents=8_911,
        historical_agents=65_370,
        direct_agents=43,
        indirect_agents=74_238,
        unresolved_agents=819,
        revoked_agents=12,
        risk_flagged_agents=127,
        max_delegation_depth=14,
        tools_used=31,
        services_used=9,
        verified_links=2_000,
        inferred_links=72_281,
        disclosure=Disclosure(
            projection_version="1", completeness="complete", as_of="2026-10-30T00:00:00Z"
        ),
    )
    base.update(overrides)
    return LineageSummary(**base)


class _Reader:
    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error
        self.calls: list[tuple[str, str]] = []

    async def summary(self, tenant_id, principal_entity_id):
        self.calls.append((tenant_id, principal_entity_id))
        if self._error:
            raise self._error
        return self._result


def test_no_reader_degrades_to_unavailable_with_null_counts_never_zero():
    out = _run(compose_agent_activity(None, TENANT, PRINCIPAL))
    assert out["completeness"] == "unavailable"
    assert out["disclosure"]["completeness"] == "unavailable"
    assert all(value is None for value in out["counts"].values())
    assert out["verified_links"] is None and out["inferred_links"] is None
    assert out["reason"] == "lineage_reader_not_configured"


def test_summary_maps_counts_and_keeps_unclassified_counts_unknown():
    reader = _Reader(_summary())
    out = _run(compose_agent_activity(reader, TENANT, PRINCIPAL))
    counts = out["counts"]
    assert reader.calls == [(TENANT, PRINCIPAL)]
    assert counts["total_agents"] == 74_281
    assert counts["directly_authorized_agents"] == 43
    assert counts["indirectly_delegated_agents"] == 74_238
    assert counts["agent_runs"] == 4_700_000
    assert counts["unresolved_associations"] == 819
    assert counts["revoked_relationships"] == 12
    assert counts["max_delegation_depth"] == 14
    # Not carried by the seam summary: unknown, with a reason, never 0.
    for key in (
        "ephemeral_agent_instances",
        "agent_mediated_communications",
        "agent_directed_financial_activity",
        "agent_outcomes",
    ):
        assert counts[key] is None
        assert key in out["unavailable_counts"]
    assert out["completeness"] == "complete"


def test_total_is_unknown_when_either_side_is_unknown():
    out = _run(compose_agent_activity(_Reader(_summary(indirect_agents=None)), TENANT, PRINCIPAL))
    assert out["counts"]["total_agents"] is None
    assert out["counts"]["directly_authorized_agents"] == 43
    # An explicit measured zero is preserved as zero.
    zero = _run(compose_agent_activity(_Reader(_summary(revoked_agents=0)), TENANT, PRINCIPAL))
    assert zero["counts"]["revoked_relationships"] == 0


def test_truncated_disclosure_is_carried_through():
    disclosure = Disclosure(
        projection_version="1",
        completeness="truncated",
        truncated=True,
        truncation_reasons=["interactive_budget"],
    )
    out = _run(compose_agent_activity(_Reader(_summary(disclosure=disclosure)), TENANT, PRINCIPAL))
    assert out["completeness"] == "truncated"
    assert out["disclosure"]["truncated"] is True
    assert out["disclosure"]["truncation_reasons"] == ["interactive_budget"]


def test_reader_failure_missing_summary_and_scope_mismatch_all_degrade():
    failed = _run(compose_agent_activity(_Reader(error=RuntimeError("boom")), TENANT, PRINCIPAL))
    assert failed["completeness"] == "unavailable"
    assert failed["reason"] == "lineage_reader_failed"
    missing = _run(compose_agent_activity(_Reader(None), TENANT, PRINCIPAL))
    assert missing["reason"] == "lineage_summary_not_materialized"
    foreign = _run(
        compose_agent_activity(_Reader(_summary(tenant_id="tenant-b")), TENANT, PRINCIPAL)
    )
    assert foreign["reason"] == "lineage_summary_scope_mismatch"
    assert all(value is None for value in foreign["counts"].values())


def test_navigation_lists_every_cohort_without_rows():
    out = _run(compose_agent_activity(_Reader(_summary()), TENANT, PRINCIPAL))
    assert [item["label"] for item in out["navigation"]] == [
        "Direct", "Delegated", "Platform", "Operator", "Authority", "Agent family",
        "Deployment", "Risk", "Value", "Communication", "Time", "Depth", "Status",
    ]
    assert len(COHORT_NAVIGATION) == 13
    assert out["default_view"] == "summary"
    assert "rows" not in out and "items" not in out


class _IdentityRepo:
    async def get_profile(self, tenant_id, user_id):
        return {"user_id": user_id, "tenant_id": tenant_id}


class _Stub:
    async def query_events(self, *a, **k):
        return []

    async def get_consent(self, *a, **k):
        return None

    async def get_all_identifiers(self, *a, **k):
        return []


def _composer(reader=None) -> ProfileComposer:
    stub = _Stub()
    return ProfileComposer(
        identity_repo=_IdentityRepo(),
        analytics_repo=stub,
        consent_repo=stub,
        graph=GraphClient(),
        cache=object(),
        resolver=stub,
        lineage_reader=reader,
    )


def _dimension(profile, name):
    return next(d for d in profile["readiness"]["dimensions"] if d["dimension"] == name)


def test_composer_is_opt_in_and_default_profile_is_unchanged():
    profile = _run(_composer().get_full_profile(PRINCIPAL, TENANT, include_graph=False,
                                                include_intelligence=False, include_lake=False,
                                                include_timeline=False))
    assert profile["agent_lineage"] == {}
    assert all(d["dimension"] != "agent_lineage" for d in profile["readiness"]["dimensions"])


def test_composer_without_reader_reports_degraded_not_zero_agents():
    profile = _run(_composer().get_full_profile(
        PRINCIPAL, TENANT, include_graph=False, include_intelligence=False,
        include_lake=False, include_timeline=False, include_agent_lineage=True))
    assert profile["agent_lineage"]["completeness"] == "unavailable"
    assert _dimension(profile, "agent_lineage")["state"] == "degraded"
    assert all(v is None for v in profile["agent_lineage"]["counts"].values())


def test_composer_with_reader_reports_ready_and_kyber_surface_section():
    composer = _composer(_Reader(_summary()))
    profile = _run(composer.get_full_profile(
        PRINCIPAL, TENANT, include_graph=False, include_intelligence=False,
        include_lake=False, include_timeline=False, include_agent_lineage=True))
    assert _dimension(profile, "agent_lineage")["state"] == "ready"
    surface = _run(composer.get_profile360_surface(
        "human", PRINCIPAL, TENANT, include=["identity", "agent_lineage"]))
    section = surface["sections"]["agent_lineage"][0]
    assert section["data"]["counts"]["total_agents"] == 74_281
