"""Focused contract tests for the native Workflow360 projection provider."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "workflow360-test-secret")

from intelligence.workflow.workflow360_provider import (  # noqa: E402
    OUTPUT_SECTIONS,
    PROJECTION_ID,
    RepositoryWorkflow360Source,
    WorkflowAgentExecutionRead,
    WorkflowAgentIdentityRead,
    Workflow360Provider,
    WorkflowRunInvocationRead,
    register_provider,
)
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.registry import ProviderRegistry  # noqa: E402

TENANT_A = "tenant-workflow-a"
RUN_ID = "workflow-run-a"


class FakeWorkflowSource:
    def __init__(
        self,
        read: WorkflowRunInvocationRead,
        identities: WorkflowAgentIdentityRead | None = None,
        agent_executions: WorkflowAgentExecutionRead | None = None,
    ) -> None:
        self.read = read
        self.identities = identities or WorkflowAgentIdentityRead((), True, True)
        self.agent_execution_read = agent_executions or WorkflowAgentExecutionRead(
            (), True, True
        )
        self.calls: list[tuple[str, str, int]] = []
        self.identity_calls: list[tuple[str, set[str], int]] = []
        self.agent_execution_calls: list[tuple[str, str, int]] = []

    async def run_invocations(
        self, *, tenant_id: str, workflow_run_id: str, limit: int
    ) -> WorkflowRunInvocationRead:
        self.calls.append((tenant_id, workflow_run_id, limit))
        return self.read

    async def run_agent_executions(
        self, *, tenant_id: str, workflow_run_id: str, limit: int
    ) -> WorkflowAgentExecutionRead:
        self.agent_execution_calls.append((tenant_id, workflow_run_id, limit))
        return self.agent_execution_read

    async def actor_identities(
        self, *, tenant_id: str, agent_ids: set[str], limit: int
    ) -> WorkflowAgentIdentityRead:
        self.identity_calls.append((tenant_id, set(agent_ids), limit))
        return self.identities


def _row(
    invocation_id: str,
    *,
    tenant_id: str = TENANT_A,
    workflow_run_id: str = RUN_ID,
    status: str = "succeeded",
    task_type: str = "summarize",
    observed_at: str = "2026-10-18T10:00:00Z",
) -> dict[str, Any]:
    return {
        "invocation_id": invocation_id,
        "tenant_id": tenant_id,
        "workflow_run_id": workflow_run_id,
        "status": status,
        "task_type": task_type,
        "provider": "provider-x",
        "model": "model-y",
        "observed_at": observed_at,
        "provenance": {"source": "runtime", "raw_event_hash": "private-hash"},
        # These potentially sensitive fields are intentionally never projected.
        "prompt_text": "private prompt",
        "completion_text": "private completion",
        "error_code": "private-provider-error",
        "agent_id": "unresolved-agent-claim",
        "outcome_id": "unverified-outcome-ref",
    }


def _agent_execution_row(
    execution_id: str = "agent-execution-a",
    *,
    tenant_id: str = TENANT_A,
    workflow_run_id: str = RUN_ID,
) -> dict[str, Any]:
    return {
        "execution_id": execution_id,
        "agent_id": "canonical-agent-a",
        "tenant_id": tenant_id,
        "workflow_run_id": workflow_run_id,
        "status": "completed",
        "started_at": "2026-10-18T10:00:00Z",
        "ended_at": "2026-10-18T10:00:02Z",
        "triggered_by_event_id": "event-a",
        "delegation_id": "delegation-a",
        # Private execution material must never enter the projected step.
        "reasoning": "private reasoning",
        "input_snapshot": {"secret": "private input"},
        "output": {"secret": "private output"},
        "error": {"secret": "private error"},
        "policy_log": {"secret": "private policy detail"},
    }


def _request(
    *, subject_kind: str = "workflow_run", subject_id: str = RUN_ID
) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId=PROJECTION_ID,
        tenantId=TENANT_A,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        includeClaims=True,
        includeSections=list(OUTPUT_SECTIONS),
    )


def _context() -> ProjectionContext:
    return ProjectionContext(
        projectionId=PROJECTION_ID,
        tenantId=TENANT_A,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )


def _sections(result) -> dict[str, Any]:
    return {section.id: section for section in result.sections}


def test_workflow360_registers_through_provider_registry() -> None:
    registry = ProviderRegistry()

    register_provider(registry)

    assert registry.get(PROJECTION_ID) is not None


@pytest.mark.asyncio
async def test_workflow360_projects_exact_run_invocation_facts_and_unknowns() -> None:
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            rows=(
                _row("invocation-a"),
                _row(
                    "invocation-b",
                    status="failed",
                    task_type="classify",
                    observed_at="2026-10-18T11:00:00-04:00",
                ),
            ),
            available=True,
            complete=True,
        )
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    assert result.projectionId == PROJECTION_ID
    assert result.tenantId == TENANT_A
    assert [section.id for section in result.sections] == list(OUTPUT_SECTIONS)
    assert source.calls == [(TENANT_A, RUN_ID, 200)]
    sections = _sections(result)

    runs = sections["runs"]
    assert runs.state == "available"
    assert runs.content["workflowRunState"] == "unknown"
    assert runs.content["workflowRunAuthorityState"] == "unknown"
    assert runs.content["freshness"] == {
        "state": "unknown",
        "latestReturnedObservedAt": "2026-10-18T15:00:00+00:00",
        "evidenceReadComplete": True,
        "thresholdSeconds": None,
        "freshnessAuthorityState": "unknown",
        "reasonCode": "workflow_run_freshness_threshold_not_configured",
        "evidenceScope": "exactly linked AI invocation facts returned by this bounded read",
    }
    assert runs.content["aiInvocationCount"] == 2
    assert [row["invocationId"] for row in runs.content["aiInvocationRecords"]] == [
        "invocation-a",
        "invocation-b",
    ]
    assert "prompt_text" not in str(runs.content)
    assert "completion_text" not in str(runs.content)
    assert "private-provider-error" not in str(runs.content)
    assert "unresolved-agent-claim" not in str(runs.content)
    assert "unverified-outcome-ref" not in str(runs.content)

    failures = sections["failures"]
    assert failures.state == "degraded"
    assert failures.content["failureScope"] == "ai_invocation_status_only"
    assert failures.content["workflowFailureAuthorityState"] == "unknown"
    assert [row["invocationId"] for row in failures.content["observedAiInvocationFailures"]] == [
        "invocation-b"
    ]
    assert "private-provider-error" not in str(failures.content)

    evidence_trace = sections["evidence_trace"]
    assert evidence_trace.state == "degraded"
    assert evidence_trace.content["workflowEventLineageState"] == "unknown"
    assert {row["source"] for row in evidence_trace.content["aiInvocationFactRefs"]} == {
        "ai_execution_facts"
    }
    assert len(result.claims) == 2
    assert all(claim.claimState == EpistemicStatus.OBSERVED for claim in result.claims)
    assert all(claim.domainSlotIds == ["runs", "evidence_trace"] for claim in result.claims)

    unsupported = {
        "workflow_summary",
        "triggers",
        "actors",
        "approvals",
        "agent_steps",
        "actions",
        "outcomes",
        "risk",
    }
    assert all(sections[slot_id].state == "unknown" for slot_id in unsupported)
    assert all(sections[slot_id].content["reasonCode"] for slot_id in unsupported)


@pytest.mark.asyncio
async def test_workflow360_resolves_only_canonical_agent_refs_for_actor_slot() -> None:
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((_row("invocation-a"),), True, True),
        WorkflowAgentIdentityRead(
            rows=(
                {
                    "tenant_id": TENANT_A,
                    "agent_id": "unresolved-agent-claim",
                    "canonical_agent_entity_id": "agent-entity-a",
                    "identity_evidence_id": "agent-entity-a",
                    "identity_evidence_source": "entities",
                    "identity_binding_authority": "canonical_agent_entity",
                    "identity_bound_at": "2026-10-18T09:00:00Z",
                },
            ),
            available=True,
            complete=True,
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    actors = _sections(result)["actors"]
    assert actors.state == "degraded"
    assert actors.content["actorCoverageState"] == "partial_ai_invocation_actor_refs_only"
    assert actors.content["identityResolutionCompleteForReportedRefs"] is True
    assert actors.content["actors"] == [
        {
            "canonicalAgentEntityId": "agent-entity-a",
            "observedAiInvocationIds": ["invocation-a"],
            "identityResolution": "tenant_canonical_agent_identity",
            "identityEvidenceRefs": [
                {
                    "id": "agent-entity-a",
                    "type": "entity",
                    "source": "entities",
                    "observedAt": "2026-10-18T09:00:00+00:00",
                    "confidence": None,
                    "uri": "store://entities/agent-entity-a",
                }
            ],
            "invocationEvidenceRefs": [
                {
                    "id": "invocation-a",
                    "type": "event",
                    "source": "ai_execution_facts",
                    "observedAt": "2026-10-18T10:00:00+00:00",
                    "confidence": None,
                    "uri": "store://ai_execution_facts/tenant-workflow-a%3Ainvocation-a",
                }
            ],
            "lastObservedAt": "2026-10-18T10:00:00+00:00",
        }
    ]
    assert source.identity_calls == [
        (TENANT_A, {"unresolved-agent-claim"}, 200)
    ]
    actor_claim = next(claim for claim in result.claims if "actor" in claim.id)
    assert actor_claim.claimState == EpistemicStatus.OBSERVED
    assert actor_claim.domainSlotIds == ["actors"]
    assert {ref.source for ref in actor_claim.evidenceRefs} == {
        "ai_execution_facts",
        "entities",
    }
    assert "human actors" in actor_claim.claims[0]
    assert "unresolved-agent-claim" not in str(actors.content)


@pytest.mark.asyncio
async def test_workflow360_keeps_actor_claim_unknown_for_cross_tenant_identity() -> None:
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((_row("invocation-a"),), True, True),
        WorkflowAgentIdentityRead(
            rows=(
                {
                    "tenant_id": "tenant-workflow-b",
                    "agent_id": "unresolved-agent-claim",
                    "canonical_agent_entity_id": "private-agent-entity",
                    "identity_evidence_id": "private-agent-entity",
                    "identity_evidence_source": "entities",
                    "identity_binding_authority": "canonical_agent_entity",
                },
            ),
            available=True,
            complete=True,
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    actors = _sections(result)["actors"]
    assert actors.state == "unknown"
    assert actors.content["actors"] == []
    assert actors.content["reasonCode"] == "workflow_agent_identity_scope_mismatch"
    assert "private-agent-entity" not in str(actors.content)
    assert not any("private-agent-entity" in str(claim) for claim in result.claims)


@pytest.mark.asyncio
async def test_workflow360_does_not_infer_human_actors_from_unjoined_ids() -> None:
    invocation = _row("invocation-a")
    invocation.update(
        {
            "actor_id": "raw-human-actor",
            "user_id": "raw-user-reference",
            "initiated_by": "raw-initiator-reference",
            "initiating_principal_user_id": "raw-principal-reference",
            "approver_id": "raw-approver-reference",
            "approval_id": "unjoined-approval-reference",
            "approval_decision_id": "unjoined-decision-reference",
            "authority_id": "unjoined-authority-reference",
        }
    )
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((invocation,), True, True),
        identities=WorkflowAgentIdentityRead((), True, True),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    actors = _sections(result)["actors"]
    assert actors.state == "unknown"
    assert actors.content["actorCoverageState"] == "unknown"
    assert actors.content["workflowActorAuthorityState"] == "unknown"
    assert actors.content["actors"] == []
    assert _sections(result)["approvals"].state == "unknown"
    serialized = str(actors.content) + str(result.claims)
    for raw_reference in (
        "raw-human-actor",
        "raw-user-reference",
        "raw-initiator-reference",
        "raw-principal-reference",
        "raw-approver-reference",
        "unjoined-approval-reference",
        "unjoined-decision-reference",
        "unjoined-authority-reference",
    ):
        assert raw_reference not in serialized


@pytest.mark.asyncio
async def test_workflow360_projects_only_exact_tenant_run_linked_agent_executions() -> None:
    valid = _agent_execution_row()
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((_row("invocation-a"),), True, True),
        agent_executions=WorkflowAgentExecutionRead(
            rows=(
                valid,
                _agent_execution_row("private-tenant-execution", tenant_id="tenant-b"),
                _agent_execution_row("wrong-run-execution", workflow_run_id="other-run"),
            ),
            available=True,
            complete=True,
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    steps = _sections(result)["agent_steps"]
    assert source.agent_execution_calls == [(TENANT_A, RUN_ID, 200)]
    assert steps.state == "available"
    assert steps.content["stepCoverageState"] == (
        "partial_exactly_linked_agent_execution_records_only"
    )
    assert steps.content["sourceReadCompleteForExactLinks"] is False
    assert steps.content["reasonCode"] == "unscoped_or_invalid_agent_execution_rows_dropped"
    assert steps.content["steps"] == [
        {
            "executionId": "agent-execution-a",
            "agentId": "canonical-agent-a",
            "status": "completed",
            "startedAt": "2026-10-18T10:00:00+00:00",
            "endedAt": "2026-10-18T10:00:02+00:00",
            "triggeredByEventId": "event-a",
            "delegationId": "delegation-a",
            "sourceRecordKind": "canonical_agent_execution",
        }
    ]
    assert "private" not in str(steps.content)
    assert steps.content["policyState"] == "unknown"
    assert steps.content["freshness"]["state"] == "unknown"
    evidence = steps.content["evidenceRefs"][0]
    assert evidence["source"] == "agent_executions"
    assert evidence["uri"] == (
        "store://agent_executions/tenant-workflow-a%3Aagent-execution-a"
    )
    step_claims = [claim for claim in result.claims if "agent_steps" in claim.domainSlotIds]
    assert len(step_claims) == 1
    assert step_claims[0].evidenceRefs[0].id == "agent-execution-a"
    assert "agent-execution-a" in str(_sections(result)["evidence_trace"].content)
    assert "private-tenant-execution" not in str(result)


@pytest.mark.asyncio
async def test_workflow360_does_not_infer_agent_steps_from_ai_agent_identity_alone() -> None:
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((_row("invocation-a"),), True, True),
        agent_executions=WorkflowAgentExecutionRead((), True, True),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    steps = _sections(result)["agent_steps"]
    assert steps.state == "unknown"
    assert steps.content["steps"] == []
    assert steps.content["reasonCode"] == "agent_execution_workflow_run_link_not_available"
    assert not any("agent_steps" in claim.domainSlotIds for claim in result.claims)


@pytest.mark.asyncio
async def test_workflow360_does_not_call_no_invocations_an_empty_workflow_run() -> None:
    source = FakeWorkflowSource(WorkflowRunInvocationRead((), True, True))

    result = await Workflow360Provider(source=source).project(_request(), _context())

    sections = _sections(result)
    assert sections["runs"].state == "unknown"
    assert "aiInvocationCount" not in sections["runs"].content
    assert sections["runs"].content["workflowRunAuthorityState"] == "unknown"
    assert sections["failures"].state == "unknown"
    assert sections["evidence_trace"].state == "unknown"
    assert result.claims == []


@pytest.mark.asyncio
async def test_workflow360_accepts_run_subject_kind_with_exact_run_id() -> None:
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((_row("invocation-a"),), True, True)
    )

    result = await Workflow360Provider(source=source).project(
        _request(subject_kind="run"), _context()
    )

    assert source.calls == [(TENANT_A, RUN_ID, 200)]
    assert _sections(result)["runs"].state == "available"


@pytest.mark.asyncio
async def test_workflow360_drops_cross_scope_facts_and_degrades_without_zero_claim() -> None:
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            rows=(
                _row("private-tenant-fact", tenant_id="tenant-workflow-b"),
                _row("wrong-run-fact", workflow_run_id="other-run"),
            ),
            available=True,
            complete=True,
        )
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    sections = _sections(result)
    assert sections["runs"].state == "unknown"
    assert sections["runs"].content["aiInvocationRecords"] == []
    assert "aiInvocationCount" not in sections["runs"].content
    assert sections["runs"].content["reasonCode"] == (
        "unscoped_or_invalid_ai_execution_facts_dropped"
    )
    assert sections["failures"].content["observedAiInvocationFailures"] == []
    assert all("private" not in str(section.content) for section in result.sections)
    assert result.claims == []


@pytest.mark.asyncio
async def test_workflow360_marks_truncated_invocation_read_degraded() -> None:
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            rows=(_row("invocation-a"),),
            available=True,
            complete=False,
            reason="ai_execution_fact_read_truncated",
        )
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    sections = _sections(result)
    assert sections["runs"].state == "degraded"
    assert "aiInvocationCount" not in sections["runs"].content
    assert sections["runs"].content["returnedAiInvocationCount"] == 1
    assert sections["failures"].state == "degraded"
    assert sections["evidence_trace"].state == "degraded"


@pytest.mark.asyncio
async def test_workflow360_keeps_unsupported_subjects_unknown_without_querying() -> None:
    source = FakeWorkflowSource(WorkflowRunInvocationRead((), True, True))

    result = await Workflow360Provider(source=source).project(
        _request(subject_kind="workflow", subject_id="workflow-definition-a"),
        _context(),
    )

    assert source.calls == []
    sections = _sections(result)
    assert sections["runs"].state == "unknown"
    assert sections["runs"].content["reasonCode"] == (
        "subject_kind_not_supported_by_workflow_run_evidence"
    )
    assert sections["evidence_trace"].state == "unknown"
    assert result.claims == []


@pytest.mark.asyncio
async def test_workflow360_degrades_source_failure_without_asserting_zero() -> None:
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (),
            available=False,
            complete=False,
            reason="ai_execution_fact_repository_unavailable",
        )
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    sections = _sections(result)
    assert sections["runs"].state == "unknown"
    assert "aiInvocationCount" not in sections["runs"].content
    assert sections["failures"].state == "unknown"
    assert sections["evidence_trace"].state == "unknown"
    assert result.claims == []


@pytest.mark.asyncio
async def test_repository_source_uses_tenant_and_exact_run_id(monkeypatch) -> None:
    from types import SimpleNamespace

    import config.settings as settings_module
    from value.economic import ai_aggregation

    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_list_facts(tenant_id: str, **filters: Any) -> list[dict[str, Any]]:
        calls.append((tenant_id, filters))
        return [_row("invocation-a")]

    monkeypatch.setattr(
        settings_module,
        "settings",
        SimpleNamespace(
            ai_economics=SimpleNamespace(execution_facts_enabled=True)
        ),
    )
    monkeypatch.setattr(ai_aggregation, "list_facts", fake_list_facts)

    read = await RepositoryWorkflow360Source().run_invocations(
        tenant_id=TENANT_A,
        workflow_run_id=RUN_ID,
        limit=20,
    )

    assert calls == [(TENANT_A, {"workflow_run_id": RUN_ID, "limit": 21})]
    assert read.available is True
    assert read.complete is True
    assert read.rows == (_row("invocation-a"),)


@pytest.mark.asyncio
async def test_repository_source_reads_only_exact_run_linked_agent_executions(
    monkeypatch,
) -> None:
    import repositories.repos as repos_module

    calls: list[tuple[dict[str, Any], int]] = []

    class AgentExecutions:
        async def find_many(self, *, filters: dict[str, Any], limit: int) -> list[dict[str, Any]]:
            calls.append((filters, limit))
            return [_agent_execution_row()]

    monkeypatch.setattr(repos_module, "AgentExecutionRepository", AgentExecutions)

    read = await RepositoryWorkflow360Source().run_agent_executions(
        tenant_id=TENANT_A,
        workflow_run_id=RUN_ID,
        limit=20,
    )

    assert calls == [({"tenant_id": TENANT_A, "workflow_run_id": RUN_ID}, 21)]
    assert read.available is True
    assert read.complete is True
    assert read.rows == (_agent_execution_row(),)
