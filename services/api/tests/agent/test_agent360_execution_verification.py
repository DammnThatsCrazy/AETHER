"""Agent360 lineage section labels how the agent's own events were verified.

Unsigned (source_reported) events must never read as verified.
See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
"""

from __future__ import annotations

import dataclasses

import pytest

T = "tenant-ev"


def _projection(subject_id: str):
    from shared.intelligence_projections import ProjectionContext, ProjectionRequest, ProjectionSubject
    from shared.intelligence_projections.contracts import ProjectionReadAuthorization

    subject = ProjectionSubject(kind="agent", id=subject_id)
    req = ProjectionRequest(projectionId="agent360", tenantId=T, subject=subject)
    auths = [ProjectionReadAuthorization(
        tenantId=T, sourceSurfaceId="agent360", sourceSubject=subject, sourceSlotId="behavior",
        consumerProjectionId="agent360", targetProjectionId="agent360",
        capabilityKey="agent_behavior", policyState="allowed")]
    ctx = ProjectionContext(projectionId="agent360", tenantId=T, registryState="in_flight",
                            dependencyState=[], warnings=[], experience360ReadAuthorizations=auths)
    return req, ctx


class _Service:
    def __init__(self, node):
        self.node = node

    async def agent_detail(self, tenant_id, agent):
        return {"agent_entity_id": agent, "node": self.node, "principals": [], "ancestors": [],
                "counts": {}, "disclosure": {"completeness": "complete"}}


async def _section(monkeypatch, node):
    from actions.agent import agent360_provider as provider_mod
    from actions.agent_lineage import service as lineage_service
    from config.settings import settings

    monkeypatch.setattr(settings, "external_agent_telemetry",
                        dataclasses.replace(settings.external_agent_telemetry, registry_enabled=True))

    async def _get_service():
        return _Service(node)

    monkeypatch.setattr(lineage_service, "get_service", _get_service)
    provider = provider_mod.Agent360Provider(source=None)
    req, ctx = _projection("agent-x")
    return await provider._lineage_section(req, ctx, T, "agent-x")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("states", "strongest", "label", "warns"),
    [
        (["attested"], "attested", "signed", False),
        (["deployment_verified", "source_reported"], "deployment_verified", "registry_validated", True),
        (["source_reported"], "source_reported", "source_reported", True),
    ],
)
async def test_lineage_section_labels_execution_verification(monkeypatch, states, strongest, label, warns):
    node = {"agent_entity_id": "agent-x", "execution_verification_states": states,
            "strongest_execution_verification": strongest,
            "has_source_reported_facts": "source_reported" in states}
    section = await _section(monkeypatch, node)
    ev = section.content["executionVerification"]
    assert ev["label"] == label and ev["strongest"] == strongest
    assert ev["hasSourceReported"] is ("source_reported" in states)
    assert bool(section.warnings) is warns


@pytest.mark.asyncio
async def test_node_without_verification_data_is_unknown_not_signed(monkeypatch):
    section = await _section(monkeypatch, {"agent_entity_id": "agent-x"})
    assert section.content["executionVerification"]["label"] == "unknown"
