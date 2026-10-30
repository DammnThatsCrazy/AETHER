"""Focused contract tests for the native Workflow360 projection provider."""

from __future__ import annotations

import os
import sys
from datetime import datetime
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
    WorkflowApprovalRead,
    WorkflowActionRead,
    Workflow360Provider,
    WorkflowPrincipalIdentityRead,
    WorkflowOutcomeRead,
    WorkflowRunInvocationRead,
    WorkflowTriggerRead,
    WorkflowRiskAssessmentRead,
    register_provider,
)
from intelligence.workflow.definitions import (  # noqa: E402
    WorkflowDefinitionRead,
    WorkflowDefinitionRepository,
    WorkflowDefinitionRevision,
    WorkflowStepDefinition,
    WorkflowTriggerDefinition,
    workflow_definition_evidence,
)
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
    TimeRangeFilter,
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
        principal_identities: WorkflowPrincipalIdentityRead | None = None,
        approvals: WorkflowApprovalRead | None = None,
        trigger_events: WorkflowTriggerRead | None = None,
        outcomes: WorkflowOutcomeRead | None = None,
        risk_assessments: WorkflowRiskAssessmentRead | None = None,
    ) -> None:
        self.read = read
        self.identities = identities or WorkflowAgentIdentityRead((), True, True)
        self.agent_execution_read = agent_executions or WorkflowAgentExecutionRead(
            (), True, True
        )
        self.principal_identity_read = principal_identities or WorkflowPrincipalIdentityRead(
            (), True, True
        )
        self.approval_read = approvals or WorkflowApprovalRead((), True, True)
        self.trigger_read = trigger_events or WorkflowTriggerRead(
            (),
            True,
            False,
            reason="workflow_execution_trigger_reference_not_recorded",
            source_read_state="available",
        )
        self.outcome_read = outcomes or WorkflowOutcomeRead((), True, True)
        self.risk_assessment_read = risk_assessments or WorkflowRiskAssessmentRead(
            (), False, False, reason="canonical_execution_risk_assessment_source_not_configured"
        )
        self.calls: list[tuple[str, str, int]] = []
        self.identity_calls: list[tuple[str, set[str], int]] = []
        self.agent_execution_calls: list[tuple[str, str, int]] = []
        self.principal_identity_calls: list[tuple[str, set[str], int]] = []
        self.trigger_event_calls: list[
            tuple[str, str, tuple[dict[str, Any], ...], int]
        ] = []
        self.outcome_calls: list[
            tuple[str, str, tuple[dict[str, Any], ...], int]
        ] = []
        self.risk_assessment_calls: list[
            tuple[str, str, tuple[dict[str, Any], ...], int]
        ] = []

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

    async def run_trigger_events(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowTriggerRead:
        self.trigger_event_calls.append(
            (tenant_id, workflow_run_id, execution_rows, limit)
        )
        return self.trigger_read

    async def actor_identities(
        self, *, tenant_id: str, agent_ids: set[str], limit: int
    ) -> WorkflowAgentIdentityRead:
        self.identity_calls.append((tenant_id, set(agent_ids), limit))
        return self.identities

    async def principal_identities(
        self, *, tenant_id: str, principal_user_ids: set[str], limit: int
    ) -> WorkflowPrincipalIdentityRead:
        self.principal_identity_calls.append((tenant_id, set(principal_user_ids), limit))
        return self.principal_identity_read

    async def run_execution_approvals(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowApprovalRead:
        return self.approval_read

    async def run_linked_outcomes(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        invocation_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowOutcomeRead:
        self.outcome_calls.append(
            (tenant_id, workflow_run_id, invocation_rows, limit)
        )
        return self.outcome_read

    async def run_execution_risk_assessments(
        self,
        *,
        tenant_id: str,
        workflow_run_id: str,
        execution_rows: tuple[dict[str, Any], ...],
        limit: int,
    ) -> WorkflowRiskAssessmentRead:
        self.risk_assessment_calls.append(
            (tenant_id, workflow_run_id, execution_rows, limit)
        )
        return self.risk_assessment_read


class FakeWorkflowDefinitionFactStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def upsert(self, fact: dict[str, Any]) -> dict[str, Any]:
        self.rows[fact["id"]] = fact
        return fact

    async def find_by_ids(
        self,
        tenant_id: str,
        record_ids: list[str] | tuple[str, ...],
        *,
        subject: str | None = None,
    ) -> list[dict[str, Any]]:
        found = []
        for record_id in record_ids:
            row = self.rows.get(record_id)
            if (
                row
                and row["tenant_id"] == tenant_id
                and (subject is None or row["subject_ref"] == subject)
            ):
                found.append({"id": record_id, "data": row["data"]})
        return found

    async def latest_for_subject(
        self, tenant_id: str, workflow_id: str
    ) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.rows.values()
            if row["tenant_id"] == tenant_id and row["subject_ref"] == workflow_id
        ]
        rows.sort(key=lambda row: row["data"]["revision"], reverse=True)
        return [
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "subject_ref": row["subject_ref"],
                "data": row["data"],
            }
            for row in rows[:2]
        ]

    async def revisions_for_subject(
        self, tenant_id: str, workflow_id: str, *, limit: int
    ) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.rows.values()
            if row["tenant_id"] == tenant_id and row["subject_ref"] == workflow_id
        ]
        rows.sort(key=lambda row: str(row["occurred_at"]), reverse=True)
        return [
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "subject_ref": row["subject_ref"],
                "occurred_at": row["occurred_at"],
                "data": row["data"],
            }
            for row in rows[:limit]
        ]


def _row(
    invocation_id: str,
    *,
    tenant_id: str = TENANT_A,
    workflow_run_id: str = RUN_ID,
    agent_id: str = "unresolved-agent-claim",
    action_id: str | None = None,
    status: str = "succeeded",
    task_type: str = "summarize",
    observed_at: str = "2026-10-18T10:00:00Z",
    outcome_id: str = "unverified-outcome-ref",
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
        "agent_id": agent_id,
        "action_id": action_id,
        "outcome_id": outcome_id,
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
        "workflow_run_invocation_ids": ["invocation-a"],
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


def _risk_assessment_row(
    assessment_id: str = "risk-assessment-a",
    *,
    tenant_id: str = TENANT_A,
    execution_id: str = "agent-execution-a",
    assessed_at: str = "2026-10-18T10:00:03Z",
) -> dict[str, Any]:
    return {
        "assessment_id": assessment_id,
        "tenant_id": tenant_id,
        "subject_kind": "execution",
        "subject_id": execution_id,
        "policy_id": "policy_agent_execution",
        "policy_version": "2",
        "dimensions": [],
        "vector": {"components": []},
        "claim_state": "unknown",
        "evidence_refs": [
            {
                "id": f"risk-input-{assessment_id}",
                "type": "event",
                "source": "risk_signals",
                "observedAt": assessed_at,
                "uri": f"store://risk_signals/risk-input-{assessment_id}",
            }
        ],
        "run_id": f"risk-run-{assessment_id}",
        "assessed_at": assessed_at,
    }


def _request(
    *,
    subject_kind: str = "workflow_run",
    subject_id: str = RUN_ID,
    as_of: str | None = None,
    temporal_mode: str | None = None,
    time_range: TimeRangeFilter | None = None,
) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId=PROJECTION_ID,
        tenantId=TENANT_A,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        includeClaims=True,
        includeSections=list(OUTPUT_SECTIONS),
        asOf=as_of,
        temporalMode=temporal_mode,
        timeRange=time_range,
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
async def test_workflow360_joins_canonical_risk_assessment_by_admitted_execution() -> None:
    invocation = _row(
        "invocation-a", agent_id="canonical-agent-a", action_id="agent-execution-a"
    )
    execution = _agent_execution_row()
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((invocation,), True, True),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        risk_assessments=WorkflowRiskAssessmentRead(
            (_risk_assessment_row(),), True, True
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    risk = _sections(result)["risk"]
    assert risk.state == "available"
    assert risk.content["assessmentCount"] == 1
    assert risk.content["assessments"][0]["executionId"] == "agent-execution-a"
    assert risk.content["assessments"][0]["associationBoundary"] == (
        "recorded_execution_subject_not_workflow_causation"
    )
    assert risk.content["freshness"]["state"] == "unknown"
    assert risk.content["policyAuthority"]["state"] == "unknown"
    assert {ref["source"] for ref in risk.content["evidenceRefs"]} == {
        "agent_executions",
        "risk_assessments",
        "risk_signals",
    }
    claim = next(
        claim
        for claim in result.claims
        if claim.kind == "risk_assessment_recorded_for_run_linked_execution"
    )
    assert claim.claimState == EpistemicStatus.OBSERVED
    assert {ref.source for ref in claim.evidenceRefs} >= {
        "agent_executions",
        "risk_assessments",
    }
    assert source.risk_assessment_calls == [
        (TENANT_A, RUN_ID, (execution,), 200)
    ]
    assert "private reasoning" not in str(result.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_workflow360_drops_risk_assessment_outside_admitted_execution_scope() -> None:
    invocation = _row(
        "invocation-a", agent_id="canonical-agent-a", action_id="agent-execution-a"
    )
    execution = _agent_execution_row()
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((invocation,), True, True),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        risk_assessments=WorkflowRiskAssessmentRead(
            (_risk_assessment_row(execution_id="another-execution"),), True, True
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    risk = _sections(result)["risk"]
    assert risk.state == "degraded"
    assert risk.content["assessments"] == []
    assert risk.content["evidenceRefs"] == []
    assert not any(
        claim.kind == "risk_assessment_recorded_for_run_linked_execution"
        for claim in result.claims
    )


@pytest.mark.asyncio
async def test_workflow360_does_not_read_current_risk_assessments_for_historical_request() -> None:
    invocation = _row(
        "invocation-a", agent_id="canonical-agent-a", action_id="agent-execution-a"
    )
    execution = _agent_execution_row()
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((invocation,), True, True),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        risk_assessments=WorkflowRiskAssessmentRead(
            (_risk_assessment_row(),), True, True
        ),
    )

    result = await Workflow360Provider(source=source).project(
        _request(as_of="2026-10-18T10:00:04Z", temporal_mode="as_of"), _context()
    )

    risk = _sections(result)["risk"]
    assert source.risk_assessment_calls == []
    assert risk.state == "unknown"
    assert risk.content["historicalRiskState"] == "unknown"
    assert risk.content["assessments"] == []


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
async def test_workflow360_projects_exact_canonical_outcome_links_without_causal_claims() -> None:
    invocation = _row("invocation-a", outcome_id="canonical-outcome-a")
    outcome_evidence = {
        "id": "outcome-event-a",
        "type": "event",
        "source": "outcome_facts",
        "observedAt": "2026-10-18T12:00:00Z",
        "uri": "store://outcome_facts/outcome-event-a",
    }
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((invocation,), True, True),
        outcomes=WorkflowOutcomeRead(
            rows=(
                {
                    "tenant_id": TENANT_A,
                    "workflow_run_id": RUN_ID,
                    "outcome_id": "canonical-outcome-a",
                    "invocation_ids": ["invocation-a"],
                    "outcome_record": {
                        "tenant_id": TENANT_A,
                        "outcome_id": "canonical-outcome-a",
                        "definition_ref": "qualified_value",
                        "state": "final",
                        "claim_type": "observed",
                        "achieved_at": "2026-10-18T12:00:00Z",
                        "value_state": "present",
                        "value_amount": "42.50",
                        "value_currency": "USD",
                        "observed_at": "2026-10-18T12:00:00Z",
                        "updated_at": "2026-10-18T12:01:00Z",
                        "evidence_refs": [outcome_evidence],
                        # Outcome subject details are not part of this public view.
                        "subject": {"kind": "entity", "id": "private-entity"},
                    },
                },
            ),
            available=True,
            complete=True,
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    outcomes = _sections(result)["outcomes"]
    assert outcomes.state == "degraded"
    assert outcomes.content["outcomeCoverageState"] == (
        "partial_explicit_invocation_outcome_refs_only"
    )
    assert outcomes.content["workflowOutcomeCausalityState"] == "not_established"
    assert outcomes.content["sourceReadCompleteForReportedOutcomeRefs"] is True
    assert outcomes.content["freshness"]["state"] == "unknown"
    assert outcomes.content["freshness"]["latestReturnedObservedAt"] == (
        "2026-10-18T12:00:00+00:00"
    )
    assert outcomes.content["outcomes"] == [
        {
            "outcomeId": "canonical-outcome-a",
            "definitionRef": "qualified_value",
            "outcomeState": "final",
            "claimType": "observed",
            "achievedAt": "2026-10-18T12:00:00+00:00",
            "valueState": "present",
            "linkedInvocationIds": ["invocation-a"],
            "outcomeEvidenceRefs": [
                {
                    "id": "outcome-event-a",
                    "type": "event",
                    "source": "outcome_facts",
                    "observedAt": "2026-10-18T12:00:00Z",
                    "confidence": None,
                    "uri": "store://outcome_facts/outcome-event-a",
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
            "evidenceRefs": [
                {
                    "id": "invocation-a",
                    "type": "event",
                    "source": "ai_execution_facts",
                    "observedAt": "2026-10-18T10:00:00+00:00",
                    "confidence": None,
                    "uri": "store://ai_execution_facts/tenant-workflow-a%3Ainvocation-a",
                },
                {
                    "id": "outcome-event-a",
                    "type": "event",
                    "source": "outcome_facts",
                    "observedAt": "2026-10-18T12:00:00Z",
                    "confidence": None,
                    "uri": "store://outcome_facts/outcome-event-a",
                },
            ],
            "valueAmount": "42.50",
            "valueCurrency": "USD",
        }
    ]
    assert "private-entity" not in str(outcomes.content)
    claim = next(claim for claim in result.claims if "outcomes" in claim.domainSlotIds)
    assert claim.claimState == EpistemicStatus.OBSERVED
    assert claim.domainSlotIds == ["outcomes", "evidence_trace"]
    assert {ref.source for ref in claim.evidenceRefs} == {
        "ai_execution_facts",
        "outcome_facts",
    }
    assert "not workflow causation" in claim.claims[0]
    assert source.outcome_calls == [
        (TENANT_A, RUN_ID, (invocation,), 200)
    ]


@pytest.mark.asyncio
async def test_workflow360_drops_cross_tenant_canonical_outcome_rows() -> None:
    invocation = _row("invocation-a", outcome_id="private-outcome")
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((invocation,), True, True),
        outcomes=WorkflowOutcomeRead(
            (
                {
                    "tenant_id": "tenant-workflow-b",
                    "workflow_run_id": RUN_ID,
                    "outcome_id": "private-outcome",
                    "invocation_ids": ["invocation-a"],
                    "outcome_record": {
                        "tenant_id": "tenant-workflow-b",
                        "outcome_id": "private-outcome",
                        "definition_ref": "private_definition",
                        "state": "final",
                        "value_state": "missing",
                        "evidence_refs": [
                            {
                                "id": "private-event",
                                "type": "event",
                                "source": "outcome_facts",
                            }
                        ],
                    },
                },
            ),
            True,
            True,
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    outcomes = _sections(result)["outcomes"]
    assert outcomes.state == "unknown"
    assert outcomes.content["outcomes"] == []
    assert outcomes.content["reasonCode"] == (
        "unscoped_or_invalid_canonical_outcome_rows_dropped"
    )
    assert "private-outcome" not in str(outcomes.content)
    assert "private-event" not in str(result.claims)


@pytest.mark.asyncio
async def test_workflow360_outcome_freshness_excludes_filtered_rows() -> None:
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (_row("invocation-a", outcome_id="outcome-a"),), True, True
        ),
        outcomes=WorkflowOutcomeRead(
            (
                {
                    "tenant_id": TENANT_A,
                    "workflow_run_id": RUN_ID,
                    "outcome_id": "outcome-a",
                    "invocation_ids": ["invocation-a"],
                    "outcome_record": {
                        "tenant_id": TENANT_A,
                        "outcome_id": "outcome-a",
                        "definition_ref": "qualified_value",
                        "state": "final",
                        "value_state": "missing",
                        "achieved_at": "2026-10-18T12:00:00Z",
                        "evidence_refs": [
                            {
                                "id": "outcome-event-a",
                                "type": "event",
                                "source": "outcome_facts",
                            }
                        ],
                    },
                },
            ),
            True,
            True,
        ),
    )

    result = await Workflow360Provider(source=source).project(
        _request(
            time_range=TimeRangeFilter(
                from_="2026-10-18T10:00:00Z",
                to="2026-10-18T11:00:00Z",
            )
        ),
        _context(),
    )

    outcomes = _sections(result)["outcomes"]
    assert outcomes.content["outcomes"] == []
    assert outcomes.content["freshness"]["latestReturnedObservedAt"] is None
    assert outcomes.content["reasonCode"] == (
        "no_canonical_workflow_outcome_in_requested_time_range"
    )


@pytest.mark.asyncio
async def test_workflow360_skips_outcome_read_when_slot_not_requested_or_historical() -> None:
    source = FakeWorkflowSource(WorkflowRunInvocationRead((_row("invocation-a"),), True, True))

    await Workflow360Provider(source=source).project(
        _request(),
        _context(),
    )
    first_read_count = len(source.outcome_calls)
    await Workflow360Provider(source=source).project(
        ProjectionRequest(
            projectionId=PROJECTION_ID,
            tenantId=TENANT_A,
            subject=ProjectionSubject(kind="workflow_run", id=RUN_ID),
            includeClaims=True,
            includeSections=["runs"],
        ),
        _context(),
    )
    assert first_read_count == 1
    assert len(source.outcome_calls) == first_read_count

    historical = _request(as_of="2026-10-18T11:00:00Z")
    await Workflow360Provider(source=source).project(historical, _context())
    assert len(source.outcome_calls) == first_read_count


@pytest.mark.asyncio
async def test_repository_source_reads_exact_tenant_outcome_ids(monkeypatch) -> None:
    from shared.backend_interpretation import flags

    class FakeOutcomeStore:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def get(self, tenant_id: str, outcome_id: str) -> dict[str, Any]:
            self.calls.append((tenant_id, outcome_id))
            return {
                "tenant_id": tenant_id,
                "outcome_id": outcome_id,
                "definition_ref": "journey_completion",
                "state": "final",
                "value_state": "missing",
                "evidence_refs": [
                    {
                        "id": "canonical-outcome-event",
                        "type": "event",
                        "source": "outcome_facts",
                    }
                ],
            }

    monkeypatch.setattr(flags, "outcome_truth_store_enabled", lambda: True)
    store = FakeOutcomeStore()
    source = RepositoryWorkflow360Source(outcome_truth_store=store)

    read = await source.run_linked_outcomes(
        tenant_id=TENANT_A,
        workflow_run_id=RUN_ID,
        invocation_rows=(
            _row("invocation-a", outcome_id="outcome-a"),
            _row("invocation-b", outcome_id="outcome-a"),
            _row("invocation-c", outcome_id="outcome-b"),
        ),
        limit=2,
    )

    assert store.calls == [(TENANT_A, "outcome-a"), (TENANT_A, "outcome-b")]
    assert read.available is True
    assert read.complete is True
    assert [row["outcome_id"] for row in read.rows] == ["outcome-a", "outcome-b"]
    assert read.rows[0]["invocation_ids"] == ["invocation-a", "invocation-b"]


@pytest.mark.asyncio
async def test_workflow360_projects_exact_trigger_event_references_without_claiming_causality() -> None:
    execution = _agent_execution_row()
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (
                _row(
                    "invocation-a",
                    agent_id="canonical-agent-a",
                    action_id="agent-execution-a",
                ),
            ),
            True,
            True,
        ),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        trigger_events=WorkflowTriggerRead(
            (
                {
                    "tenant_id": TENANT_A,
                    "workflow_run_id": RUN_ID,
                    "event_id": "event-a",
                    "event_type": "journey_started",
                    "occurred_at": "2026-10-18T09:59:59Z",
                    "execution_ids": ["agent-execution-a"],
                },
            ),
            True,
            True,
            source_read_state="available",
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    triggers = _sections(result)["triggers"]
    assert triggers.state == "degraded"
    assert triggers.content["triggerCoverageState"] == (
        "partial_exact_execution_event_references_only"
    )
    assert triggers.content["workflowTriggerAuthorityState"] == "unknown"
    assert triggers.content["causalityState"] == "reference_only"
    assert triggers.content["sourceReadCompleteForExactEventReferences"] is True
    assert triggers.content["triggers"] == [
        {
            "eventId": "event-a",
            "eventType": "journey_started",
            "occurredAt": "2026-10-18T09:59:59+00:00",
            "linkedExecutionIds": ["agent-execution-a"],
            "referenceKind": "agent_execution_triggered_by_event_id",
            "causalityState": "not_established",
            "evidenceRefs": [
                {
                    "id": "event-a",
                    "type": "event",
                    "source": "services/api/repositories/repos.py:events",
                    "observedAt": "2026-10-18T09:59:59+00:00",
                    "confidence": None,
                    "uri": "store://events/event-a",
                },
                {
                    "id": "agent-execution-a",
                    "type": "event",
                    "source": "agent_executions",
                    "observedAt": "2026-10-18T10:00:02+00:00",
                    "confidence": None,
                    "uri": "store://agent_executions/tenant-workflow-a%3Aagent-execution-a",
                },
            ],
        }
    ]
    assert source.trigger_event_calls == [
        (TENANT_A, RUN_ID, (execution,), 200)
    ]
    trigger_claim = next(
        claim for claim in result.claims if claim.kind == "tenant_event_referenced_by_workflow_run_execution"
    )
    assert trigger_claim.claimState == EpistemicStatus.OBSERVED
    assert trigger_claim.domainSlotIds == ["triggers", "evidence_trace"]
    assert {ref.source for ref in trigger_claim.evidenceRefs} == {
        "services/api/repositories/repos.py:events",
        "agent_executions",
    }
    evidence_trace = _sections(result)["evidence_trace"].content
    assert evidence_trace["triggerEventRefs"][0]["id"] == "event-a"
    assert "private input" not in str(result.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_workflow360_does_not_read_current_trigger_links_for_historical_request() -> None:
    execution = _agent_execution_row()
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (_row("invocation-a", agent_id="canonical-agent-a", action_id="agent-execution-a"),),
            True,
            True,
        ),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        trigger_events=WorkflowTriggerRead(
            (
                {
                    "tenant_id": TENANT_A,
                    "workflow_run_id": RUN_ID,
                    "event_id": "event-a",
                    "event_type": "journey_started",
                    "occurred_at": "2026-10-18T09:59:59Z",
                    "execution_ids": ["agent-execution-a"],
                },
            ),
            True,
            True,
            source_read_state="available",
        ),
    )

    result = await Workflow360Provider(source=source).project(
        _request(as_of="2026-10-18T10:00:00Z", temporal_mode="as_of"), _context()
    )

    triggers = _sections(result)["triggers"]
    assert source.trigger_event_calls == []
    assert triggers.state == "unknown"
    assert triggers.content["sourceReadState"] == "not_read"
    assert triggers.content["reasonCode"] == "workflow_trigger_historical_state_unavailable"
    assert triggers.content["triggers"] == []
    assert "journey_started" not in str(triggers.content)


@pytest.mark.parametrize(
    ("available", "source_read_state", "expected_state"),
    [
        (False, "unavailable", "degraded"),
        (True, "not_read", "unknown"),
    ],
)
@pytest.mark.asyncio
async def test_workflow360_never_projects_trigger_rows_when_event_authority_was_not_read(
    available: bool, source_read_state: str, expected_state: str
) -> None:
    execution = _agent_execution_row()
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (
                _row(
                    "invocation-a",
                    agent_id="canonical-agent-a",
                    action_id="agent-execution-a",
                ),
            ),
            True,
            True,
        ),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        # This deliberately inconsistent adapter result guards the projection
        # boundary: rows alone are not evidence if the event source was not read.
        trigger_events=WorkflowTriggerRead(
            (
                {
                    "tenant_id": TENANT_A,
                    "workflow_run_id": RUN_ID,
                    "event_id": "event-a",
                    "event_type": "journey_started",
                    "occurred_at": "2026-10-18T09:59:59Z",
                    "execution_ids": ["agent-execution-a"],
                },
            ),
            available,
            True,
            reason="workflow_trigger_event_source_unavailable",
            source_read_state=source_read_state,
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    triggers = _sections(result)["triggers"]
    assert triggers.state == expected_state
    assert triggers.content["triggers"] == []
    assert triggers.content["evidenceRefs"] == []
    assert triggers.content["sourceReadCompleteForExactEventReferences"] is False
    assert not any(
        claim.kind == "tenant_event_referenced_by_workflow_run_execution"
        for claim in result.claims
    )
    assert "journey_started" not in str(triggers.content)


@pytest.mark.asyncio
async def test_workflow360_bounds_trigger_events_to_requested_time_range() -> None:
    execution = _agent_execution_row()
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (_row("invocation-a", agent_id="canonical-agent-a", action_id="agent-execution-a"),),
            True,
            True,
        ),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        trigger_events=WorkflowTriggerRead(
            (
                {
                    "tenant_id": TENANT_A,
                    "workflow_run_id": RUN_ID,
                    "event_id": "event-a",
                    "event_type": "journey_started",
                    "occurred_at": "2026-10-18T09:59:59Z",
                    "execution_ids": ["agent-execution-a"],
                },
            ),
            True,
            True,
            source_read_state="available",
        ),
    )

    result = await Workflow360Provider(source=source).project(
        _request(
            time_range=TimeRangeFilter(
                from_="2026-10-18T10:00:00Z",
                to="2026-10-18T11:00:00Z",
            )
        ),
        _context(),
    )

    triggers = _sections(result)["triggers"]
    assert triggers.state == "unknown"
    assert triggers.content["triggers"] == []
    assert triggers.content["sourceReadCompleteForExactEventReferences"] is True
    assert triggers.content["reasonCode"] == (
        "workflow_trigger_events_outside_requested_time_range"
    )
    assert "journey_started" not in str(triggers.content)


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


def _principal_identity(
    principal_user_id: str,
    canonical_human_entity_id: str = "canonical-human-a",
    *,
    tenant_id: str = TENANT_A,
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "principal_user_id": principal_user_id,
        "canonical_human_entity_id": canonical_human_entity_id,
        "identity_evidence_refs": [
            {"id": "user-id-alias-a", "type": "entity", "source": "identity_aliases"},
            {"id": "active-human-subject-a", "type": "entity", "source": "identity_subjects"},
        ],
    }


@pytest.mark.asyncio
async def test_workflow360_resolves_exact_execution_initiator_to_canonical_human() -> None:
    execution = _agent_execution_row()
    execution["initiating_principal_user_id"] = "authenticated-user-a"
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (
                _row(
                    "invocation-a",
                    agent_id="canonical-agent-a",
                    action_id="agent-execution-a",
                ),
            ),
            True,
            True,
        ),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        principal_identities=WorkflowPrincipalIdentityRead(
            (_principal_identity("authenticated-user-a"),), True, True
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    actors = _sections(result)["actors"]
    assert actors.state == "degraded"
    assert actors.content["principalIdentityResolutionCompleteForReportedRefs"] is True
    human_actor = next(
        actor
        for actor in actors.content["actors"]
        if actor.get("canonicalHumanEntityId") == "canonical-human-a"
    )
    assert human_actor["actorKind"] == "human"
    assert human_actor["roles"] == ["initiating_principal"]
    assert human_actor["executionIds"] == ["agent-execution-a"]
    assert {ref["source"] for ref in human_actor["identityEvidenceRefs"]} == {
        "identity_aliases",
        "identity_subjects",
    }
    assert source.principal_identity_calls == [
        (TENANT_A, {"authenticated-user-a"}, 200)
    ]
    human_claim = next(
        claim for claim in result.claims if claim.kind == "tenant_canonical_human_linked_to_workflow_execution"
    )
    assert human_claim.claimState == EpistemicStatus.RESOLVED
    assert {ref.source for ref in human_claim.evidenceRefs} == {
        "agent_executions",
        "identity_aliases",
        "identity_subjects",
    }
    assert "authenticated-user-a" not in str(actors.content)


@pytest.mark.asyncio
async def test_workflow360_keeps_ambiguous_principal_identity_unknown() -> None:
    execution = _agent_execution_row()
    execution["initiating_principal_user_id"] = "ambiguous-user-a"
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (
                _row(
                    "invocation-a",
                    agent_id="canonical-agent-a",
                    action_id="agent-execution-a",
                ),
            ),
            True,
            True,
        ),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        principal_identities=WorkflowPrincipalIdentityRead(
            (
                _principal_identity("ambiguous-user-a", "canonical-human-a"),
                _principal_identity("ambiguous-user-a", "canonical-human-b"),
            ),
            True,
            True,
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    actors = _sections(result)["actors"]
    assert actors.content["principalIdentityResolutionCompleteForReportedRefs"] is False
    assert not any(
        "canonicalHumanEntityId" in actor for actor in actors.content["actors"]
    )
    assert "ambiguous-user-a" not in str(actors.content)
    assert not any(
        claim.kind == "tenant_canonical_human_linked_to_workflow_execution"
        for claim in result.claims
    )


@pytest.mark.asyncio
async def test_workflow360_joins_exact_approval_decider_to_human_actor() -> None:
    execution = _agent_execution_row()
    execution.update(
        {
            "initiating_principal_user_id": "initiator-user-a",
            "approval_id": "approval-a",
            "approval_decision_id": "decision-a",
        }
    )
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (
                _row(
                    "invocation-a",
                    agent_id="canonical-agent-a",
                    action_id="agent-execution-a",
                ),
            ),
            True,
            True,
        ),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        principal_identities=WorkflowPrincipalIdentityRead(
            (
                _principal_identity("initiator-user-a", "canonical-initiator-a"),
                _principal_identity("approver-user-a", "canonical-approver-a"),
            ),
            True,
            True,
        ),
        approvals=WorkflowApprovalRead(
            (
                {
                    "tenant_id": TENANT_A,
                    "workflow_run_id": RUN_ID,
                    "execution_id": "agent-execution-a",
                    "approval_id": "approval-a",
                    "decision_id": "decision-a",
                    "action": "approve",
                    "decided_by": "approver-user-a",
                    "decided_at": "2026-10-18T10:00:01Z",
                },
            ),
            True,
            True,
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    sections = _sections(result)
    approvals = sections["approvals"]
    assert approvals.state == "degraded"
    assert approvals.content["sourceReadCompleteForExactLinks"] is True
    assert approvals.content["workflowApprovalAuthorityState"] == "unknown"
    assert approvals.content["approvals"][0]["decidedByCanonicalHumanEntityId"] == (
        "canonical-approver-a"
    )
    actors = sections["actors"]
    approver = next(
        actor
        for actor in actors.content["actors"]
        if actor.get("canonicalHumanEntityId") == "canonical-approver-a"
    )
    assert approver["roles"] == ["approver"]
    assert approver["approvalIds"] == ["approval-a"]
    assert "approver-user-a" not in str(actors.content) + str(approvals.content)


@pytest.mark.asyncio
async def test_workflow360_keeps_exact_approval_when_decider_identity_is_unresolved() -> None:
    execution = _agent_execution_row()
    execution.update(
        {
            "approval_id": "approval-unresolved-a",
            "approval_decision_id": "decision-unresolved-a",
        }
    )
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (
                _row(
                    "invocation-a",
                    agent_id="canonical-agent-a",
                    action_id="agent-execution-a",
                ),
            ),
            True,
            True,
        ),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        approvals=WorkflowApprovalRead(
            (
                {
                    "tenant_id": TENANT_A,
                    "workflow_run_id": RUN_ID,
                    "execution_id": "agent-execution-a",
                    "approval_id": "approval-unresolved-a",
                    "decision_id": "decision-unresolved-a",
                    "action": "approve",
                    "decided_by": "unresolved-approver-user",
                    "decided_at": "2026-10-18T10:00:01Z",
                },
            ),
            True,
            True,
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    approvals = _sections(result)["approvals"]
    assert approvals.content["sourceReadCompleteForExactLinks"] is True
    assert approvals.content["decisionActorIdentityResolutionCompleteForReportedRefs"] is False
    assert approvals.content["approvals"][0]["decisionActorIdentityState"] == "unresolved"
    assert "decidedByCanonicalHumanEntityId" not in approvals.content["approvals"][0]
    assert "unresolved-approver-user" not in str(approvals.content)
    assert approvals.content["workflowApprovalAuthorityState"] == "unknown"


@pytest.mark.asyncio
async def test_workflow360_rejects_execution_when_invocation_action_link_differs() -> None:
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (
                _row(
                    "invocation-a",
                    agent_id="canonical-agent-a",
                    action_id="some-other-action",
                ),
            ),
            True,
            True,
        ),
        agent_executions=WorkflowAgentExecutionRead(
            (_agent_execution_row(),), True, True
        ),
    )

    result = await Workflow360Provider(source=source).project(_request(), _context())

    steps = _sections(result)["agent_steps"]
    assert steps.state == "unknown"
    assert steps.content["steps"] == []
    assert steps.content["reasonCode"] == "unscoped_or_invalid_agent_execution_rows_dropped"
    actors = _sections(result)["actors"]
    assert actors.content["actors"] == []


@pytest.mark.asyncio
async def test_workflow360_projects_only_exact_tenant_run_linked_agent_executions() -> None:
    valid = _agent_execution_row()
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead(
            (
                _row(
                    "invocation-a",
                    agent_id="canonical-agent-a",
                    action_id="agent-execution-a",
                ),
            ),
            True,
            True,
        ),
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


@pytest.mark.asyncio
async def test_repository_source_reads_risk_assessments_by_exact_execution_subject(
    monkeypatch,
) -> None:
    import intelligence.risk360.store as risk_store

    calls: list[tuple[str, str, str, int]] = []

    class RiskAssessments:
        async def list_by_subject(
            self, tenant_id: str, subject_kind: str, subject_id: str, *, limit: int
        ) -> list[dict[str, Any]]:
            calls.append((tenant_id, subject_kind, subject_id, limit))
            return [_risk_assessment_row(execution_id=subject_id)]

    monkeypatch.setattr(risk_store, "RiskAssessmentRepository", RiskAssessments)
    execution = _agent_execution_row()

    read = await RepositoryWorkflow360Source().run_execution_risk_assessments(
        tenant_id=TENANT_A,
        workflow_run_id=RUN_ID,
        execution_rows=(execution,),
        limit=20,
    )

    assert calls == [(TENANT_A, "execution", "agent-execution-a", 21)]
    assert read.available is True
    assert read.complete is True
    assert read.scope_mismatch is False
    assert read.rows == (_risk_assessment_row(),)


@pytest.mark.asyncio
async def test_repository_source_does_not_query_risk_for_foreign_run_execution(
    monkeypatch,
) -> None:
    import intelligence.risk360.store as risk_store

    class RiskAssessments:
        async def list_by_subject(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            pytest.fail("foreign workflow execution must not reach risk authority")

    monkeypatch.setattr(risk_store, "RiskAssessmentRepository", RiskAssessments)
    foreign = _agent_execution_row()
    foreign["workflow_run_id"] = "another-run"

    read = await RepositoryWorkflow360Source().run_execution_risk_assessments(
        tenant_id=TENANT_A,
        workflow_run_id=RUN_ID,
        execution_rows=(foreign,),
        limit=20,
    )

    assert read.available is True
    assert read.complete is False
    assert read.scope_mismatch is True
    assert read.rows == ()


@pytest.mark.asyncio
async def test_repository_source_resolves_trigger_ids_by_exact_tenant_and_event_id(
    monkeypatch,
) -> None:
    from dependencies import providers
    from repositories import repos

    calls: list[tuple[str, dict[str, str], int]] = []

    class Analytics:
        def __init__(self, cache: object) -> None:
            assert cache == "shared-cache"

        async def query_events(
            self, tenant_id: str, filters: dict[str, str], *, limit: int
        ) -> list[dict[str, Any]]:
            calls.append((tenant_id, filters, limit))
            event_id = filters["event_id"]
            event_tenant = "tenant-other" if event_id == "event-b" else tenant_id
            return [
                {
                    "tenant_id": event_tenant,
                    "event_id": event_id,
                    "event_type": "journey_started",
                    "occurred_at": "2026-10-18T10:00:00Z",
                    "properties": {"private": "must not project"},
                }
            ]

    first = _agent_execution_row()
    second = _agent_execution_row("agent-execution-b")
    second["triggered_by_event_id"] = "event-b"
    monkeypatch.setattr(providers, "get_cache", lambda: "shared-cache")
    monkeypatch.setattr(repos, "AnalyticsRepository", Analytics)

    read = await RepositoryWorkflow360Source().run_trigger_events(
        tenant_id=TENANT_A,
        workflow_run_id=RUN_ID,
        execution_rows=(first, second),
        limit=20,
    )

    assert calls == [
        (TENANT_A, {"event_id": "event-a"}, 2),
        (TENANT_A, {"event_id": "event-b"}, 2),
    ]
    assert read.available is True
    assert read.complete is False
    assert read.scope_mismatch is True
    assert read.rows == (
        {
            "tenant_id": TENANT_A,
            "workflow_run_id": RUN_ID,
            "event_id": "event-a",
            "event_type": "journey_started",
            "occurred_at": "2026-10-18T10:00:00Z",
            "execution_ids": ["agent-execution-a"],
        },
    )
    assert "private" not in str(read.rows)


@pytest.mark.parametrize("action", ["approve", "reject", "escalate", "revoke"])
@pytest.mark.asyncio
async def test_repository_source_reads_only_exact_execution_approval_references(
    monkeypatch, action: str
) -> None:
    from value.x402 import commerce_store as commerce_store_module
    from value.x402.commerce_models import ApprovalDecision, ApprovalRequest
    from value.x402.commerce_store import CommerceStore

    store = CommerceStore()
    execution = _agent_execution_row()
    execution.update(
        {"approval_id": "approval-source-a", "approval_decision_id": "decision-source-a"}
    )
    approval = ApprovalRequest(
        approval_id="approval-source-a",
        tenant_id=TENANT_A,
        challenge_id="challenge-source-a",
        resource_id="resource-source-a",
        requester_id="canonical-agent-a",
        execution_id="agent-execution-a",
        execution_action="pay",
        amount_usd=1,
        asset_symbol="USDC",
        chain="eip155:8453",
    )
    decision = ApprovalDecision(
        decision_id="decision-source-a",
        approval_id=approval.approval_id,
        tenant_id=TENANT_A,
        execution_id="agent-execution-a",
        action=action,
        decided_by="approval-user-a",
        reason="approved",
    )
    await store.put_approval(approval)
    await store.put_approval_decision(decision)
    monkeypatch.setattr(commerce_store_module, "get_commerce_store", lambda: store)

    read = await RepositoryWorkflow360Source().run_execution_approvals(
        tenant_id=TENANT_A,
        workflow_run_id=RUN_ID,
        execution_rows=(execution,),
        limit=20,
    )

    assert read.available is True
    assert read.complete is True
    assert read.rows == (
        {
            "tenant_id": TENANT_A,
            "workflow_run_id": RUN_ID,
            "execution_id": "agent-execution-a",
            "approval_id": "approval-source-a",
            "decision_id": "decision-source-a",
            "action": action,
            "requester_id": "canonical-agent-a",
            "requester_type": "agent",
            "execution_action": "pay",
            "resource_id": "resource-source-a",
            "approved_amount_usd": 1.0,
            "decided_by": "approval-user-a",
            "decided_at": decision.decided_at,
        },
    )


@pytest.mark.asyncio
async def test_repository_source_resolves_principal_through_tenant_user_alias() -> None:
    from identity.identity.hashing import hash_value
    from identity.identity.models import IdentitySignalType

    class IdentityRepository:
        async def find_aliases_by_signal(
            self, tenant_id: str, signal_type: Any, alias_hash: str, *, limit: int
        ) -> list[dict[str, Any]]:
            assert tenant_id == TENANT_A
            assert signal_type == IdentitySignalType.USER_ID
            assert alias_hash == hash_value("authenticated-user-a", scope=f"user:{TENANT_A}")
            assert limit == 101
            return [
                {
                    "id": "user-alias-a",
                    "tenant_id": TENANT_A,
                    "alias_type": IdentitySignalType.USER_ID.value,
                    "alias_value_hash": alias_hash,
                    "canonical_entity_id": "human-entity-a",
                    "confidence_tier": "deterministic",
                }
            ]

        async def resolve_surviving_canonical_entity_id(
            self, tenant_id: str, canonical_entity_id: str
        ) -> str:
            assert tenant_id == TENANT_A
            assert canonical_entity_id == "human-entity-a"
            return canonical_entity_id

        async def get_subject_by_canonical_entity_id(
            self, tenant_id: str, canonical_entity_id: str
        ) -> dict[str, Any]:
            return {
                "id": "human-subject-a",
                "tenant_id": tenant_id,
                "canonical_entity_id": canonical_entity_id,
                "entity_type": "human",
                "status": "active",
            }

    read = await RepositoryWorkflow360Source(
        principal_identity_repository=IdentityRepository()
    ).principal_identities(
        tenant_id=TENANT_A,
        principal_user_ids={"authenticated-user-a"},
        limit=20,
    )

    assert read.available is True
    assert read.complete is True
    assert read.rows[0]["canonical_human_entity_id"] == "human-entity-a"
    refs = read.rows[0]["identity_evidence_refs"]
    assert {ref["source"] for ref in refs} == {
        "identity_aliases",
        "identity_subjects",
    }


@pytest.mark.asyncio
async def test_repository_source_joins_tool_call_edges_to_exact_run_executions(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    import shared.graph.graph as graph_module

    execution = _agent_execution_row()
    edge = SimpleNamespace(
        edge_type=graph_module.EdgeType.CALLED_TOOL,
        from_vertex_id=f"{TENANT_A}:agent:{execution['agent_id']}",
        to_vertex_id=f"{TENANT_A}:tool:tool-a",
        properties={
            "tenant_id": TENANT_A,
            "execution_id": execution["execution_id"],
            "called_at": "2026-10-18T10:00:01Z",
            "idempotency_key": "tool-call-event-a",
            "action": "delete",
            "resource_id": "foreign-resource",
            "policy_decision": {"allowed": True, "action": "delete"},
            "tool_result": {"status": "succeeded"},
            "resource_operation": {"status": "succeeded"},
            "external_effect": "confirmed",
        },
    )

    class FakeGraph:
        async def get_edges_for_tenant(self, tenant_id: str, *, limit: int, edge_types: list[Any]):
            assert tenant_id == TENANT_A
            assert limit == 10_000
            assert edge_types == [graph_module.EdgeType.CALLED_TOOL]
            return [edge], False

        async def get_vertex_for_tenant(self, tenant_id: str, vertex_id: str):
            assert tenant_id == TENANT_A
            assert vertex_id == f"{TENANT_A}:tool:tool-a"
            return SimpleNamespace(
                vertex_type="Tool",
                properties={"tenant_id": tenant_id, "tool_id": "tool-a"},
            )

    monkeypatch.setattr(graph_module, "GraphClient", FakeGraph)
    read = await RepositoryWorkflow360Source().run_execution_actions(
        tenant_id=TENANT_A,
        workflow_run_id=RUN_ID,
        execution_rows=(execution,),
        limit=20,
    )

    assert read.available is True
    assert read.complete is True
    assert read.scope_mismatch is False
    assert len(read.rows) == 1
    assert read.rows[0]["execution_id"] == execution["execution_id"]
    assert read.rows[0]["tool_id"] == "tool-a"
    assert read.rows[0]["evidence_ref"]["id"] == "tool-call-event-a"
    assert read.rows[0]["evidence_ref"]["source"] == "graph_edges"
    assert read.rows[0]["tool_evidence_ref"]["id"] == f"{TENANT_A}:tool:tool-a"
    assert read.rows[0]["tool_evidence_ref"]["source"] == "graph_vertices"


@pytest.mark.asyncio
async def test_repository_source_marks_truncated_action_edge_scan_incomplete(monkeypatch) -> None:
    import shared.graph.graph as graph_module

    class TruncatedGraph:
        async def get_edges_for_tenant(self, tenant_id: str, *, limit: int, edge_types: list[Any]):
            assert tenant_id == TENANT_A
            assert edge_types == [graph_module.EdgeType.CALLED_TOOL]
            return [], True

    monkeypatch.setattr(graph_module, "GraphClient", TruncatedGraph)
    read = await RepositoryWorkflow360Source().run_execution_actions(
        tenant_id=TENANT_A,
        workflow_run_id=RUN_ID,
        execution_rows=(_agent_execution_row(),),
        limit=20,
    )

    assert read.available is True
    assert read.rows == ()
    assert read.complete is False
    assert read.scope_mismatch is False
    assert read.reason == "canonical_workflow_action_graph_read_truncated"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", f" {TENANT_A}"),
        ("execution_id", " agent-execution-a "),
        ("idempotency_key", " tool-call-event-a"),
        ("to_vertex_id", f" {TENANT_A}:tool:tool-a"),
        ("tool_vertex_tenant_id", f"{TENANT_A} "),
        ("tool_vertex_tool_id", " tool-a"),
    ],
)
async def test_repository_source_rejects_padded_tool_call_join_identifiers(
    monkeypatch, field, value
) -> None:
    from types import SimpleNamespace

    import shared.graph.graph as graph_module

    execution = _agent_execution_row()
    properties = {
        "tenant_id": TENANT_A,
        "execution_id": execution["execution_id"],
        "called_at": "2026-10-18T10:00:01Z",
        "idempotency_key": "tool-call-event-a",
    }
    vertex_tenant_id = TENANT_A
    vertex_tool_id = "tool-a"
    target_vertex_id = f"{TENANT_A}:tool:tool-a"
    if field == "to_vertex_id":
        target_vertex_id = value
    elif field == "tool_vertex_tenant_id":
        vertex_tenant_id = value
    elif field == "tool_vertex_tool_id":
        vertex_tool_id = value
    else:
        properties[field] = value
    edge = SimpleNamespace(
        edge_type=graph_module.EdgeType.CALLED_TOOL,
        from_vertex_id=f"{TENANT_A}:agent:{execution['agent_id']}",
        to_vertex_id=target_vertex_id,
        properties=properties,
    )

    class FakeGraph:
        async def get_edges_for_tenant(self, tenant_id: str, *, limit: int, edge_types: list[Any]):
            return [edge], False

        async def get_vertex_for_tenant(self, tenant_id: str, vertex_id: str):
            return SimpleNamespace(
                vertex_type="Tool",
                properties={"tenant_id": vertex_tenant_id, "tool_id": vertex_tool_id},
            )

    monkeypatch.setattr(graph_module, "GraphClient", FakeGraph)
    read = await RepositoryWorkflow360Source().run_execution_actions(
        tenant_id=TENANT_A,
        workflow_run_id=RUN_ID,
        execution_rows=(execution,),
        limit=20,
    )

    assert read.available is True
    assert read.rows == ()
    assert read.complete is False
    assert read.scope_mismatch is True


@pytest.mark.asyncio
async def test_workflow_actions_project_observed_calls_without_inference() -> None:
    invocation = _row(
        "invocation-a",
        agent_id="canonical-agent-a",
        action_id="agent-execution-a",
    )
    execution = _agent_execution_row()
    action = {
        "tenant_id": TENANT_A,
        "workflow_run_id": RUN_ID,
        "execution_id": "agent-execution-a",
        "agent_id": "canonical-agent-a",
        "tool_id": "tool-a",
        "called_at": "2026-10-18T10:00:01Z",
        "evidence_ref": {
            "id": "tool-call-event-a",
            "type": "event",
            "source": "graph_edges",
            "observedAt": "2026-10-18T10:00:01+00:00",
            "uri": "store://graph_edges/tool-call-event-a",
        },
        "tool_evidence_ref": {
            "id": f"{TENANT_A}:tool:tool-a",
            "type": "entity",
            "source": "graph_vertices",
            "uri": f"store://graph_vertices/{TENANT_A}%3Atool%3Atool-a",
        },
        # Caller or callback controlled fields on an observation must never
        # be promoted to a server execution receipt or operation result.
        "principal_id": "attacker-principal",
        "policy_decision": {"allowed": True, "policy_id": "caller-claim"},
        "tool_result": {"status": "succeeded", "value": "caller-claim"},
        "resource_id": "caller-resource",
        "resource_operation": {"status": "succeeded"},
        "external_effect": "confirmed",
        "integrity": {"signature": "caller-claim"},
    }

    class SourceWithActions(FakeWorkflowSource):
        async def run_execution_actions(
            self,
            *,
            tenant_id: str,
            workflow_run_id: str,
            execution_rows: tuple[dict[str, Any], ...],
            limit: int,
        ) -> WorkflowActionRead:
            assert tenant_id == TENANT_A
            assert workflow_run_id == RUN_ID
            assert execution_rows == (execution,)
            assert limit == 500
            return WorkflowActionRead((action,), True, True)

    source = SourceWithActions(
        WorkflowRunInvocationRead((invocation,), True, True),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
    )
    result = await Workflow360Provider(source=source).project(_request(), _context())

    actions = _sections(result)["actions"]
    assert actions.state == "available"
    assert actions.content["actionProducerCoverage"] == "unknown"
    assert actions.content["authorizationState"] == "not_established_by_tool_call_edge"
    assert actions.content["externalEffectState"] == "unknown"
    assert actions.content["actions"][0]["operationState"] == (
        "call_observed_external_effect_unknown"
    )
    assert actions.content["actions"][0]["toolIdentityState"] == "resolved"
    assert actions.content["actions"][0]["executionResult"] == {"state": "unknown"}
    assert actions.content["actions"][0]["approvedResource"] == {"state": "unknown"}
    assert actions.content["actions"][0]["executionReceipt"] == {
        "state": "unknown",
        "reasonCode": "canonical_action_execution_receipt_source_unavailable",
    }
    assert "tool_result" not in actions.content["actions"][0]
    assert "policy_decision" not in actions.content["actions"][0]
    assert "external_effect" not in actions.content["actions"][0]
    assert actions.content["actions"][0]["authorityDecision"] == "not_established_by_tool_call_edge"
    assert actions.content["actions"][0]["approvedResource"].get("resourceOperation", "unknown") == "unknown"
    assert actions.canonicalAuthorityRefs == ["agent_executions", "graph_edges", "tools"]
    claim = next(claim for claim in result.claims if "actions" in claim.domainSlotIds)
    assert claim.claimState == EpistemicStatus.OBSERVED
    assert {ref.source for ref in claim.evidenceRefs} == {
        "graph_edges",
        "agent_executions",
        "graph_vertices",
    }
    assert "does not establish" in claim.claims[0]
    assert _sections(result)["workflow_summary"].state == "unknown"


@pytest.mark.asyncio
async def test_registered_workflow_definition_projects_latest_revision_without_run_inference() -> None:
    fact_store = FakeWorkflowDefinitionFactStore()
    repository = WorkflowDefinitionRepository(fact_store)
    first = WorkflowDefinitionRevision(
        workflow_id="workflow-definition-1",
        tenant_id=TENANT_A,
        revision=1,
        name="Onboarding",
        status="active",
        triggers=[
            WorkflowTriggerDefinition(
                trigger_id="signup-trigger",
                kind="event",
                event_type="user.signup",
            )
        ],
        steps=[
            WorkflowStepDefinition(
                step_id="welcome-step",
                kind="agent",
                label="Prepare welcome message",
                agent_ref="agent-welcome",
            )
        ],
        actor_ref="tenant-user-1",
        created_at="2026-10-20T10:00:00Z",
    )
    second = WorkflowDefinitionRevision.model_validate(
        first.model_dump(mode="json")
        | {"revision": 2, "name": "Onboarding v2", "created_at": "2026-10-21T10:00:00Z"}
    )
    await repository.register(first)
    await repository.register(second)
    replay = WorkflowDefinitionRevision.model_validate(
        second.model_dump(mode="json") | {"created_at": "2026-10-22T10:00:00Z"}
    )
    stored_replay = await repository.register(replay)
    assert stored_replay.created_at == second.created_at
    assert stored_replay.definition_digest == second.definition_digest
    with pytest.raises(ValueError, match="workflow_definition_revision_is_append_only"):
        await repository.register(second.model_copy(update={"name": "Mutated definition"}))

    latest = await repository.read_latest(TENANT_A, first.workflow_id)
    assert latest.available is True
    assert latest.complete is True
    assert latest.rows[0]["revision"] == 2

    request = _request(subject_kind="workflow", subject_id=first.workflow_id)
    # The shared registry currently declares run subjects only; root integration
    # will add the workflow-definition subject kinds after this provider lands.
    request = request.model_copy(
        update={
            "subject": ProjectionSubject.model_construct(kind="workflow", id=first.workflow_id)
        }
    )
    result = await Workflow360Provider(
        source=RepositoryWorkflow360Source(workflow_definition_repository=repository)
    ).project(request, _context())

    sections = _sections(result)
    summary = sections["workflow_summary"]
    assert summary.state == "available"
    assert summary.content["revision"] == 2
    assert summary.content["name"] == "Onboarding v2"
    assert summary.content["registeredByActorRef"] == "tenant-user-1"
    assert summary.content["declaredTriggers"][0]["event_type"] == "user.signup"
    assert summary.content["triggerExecutionState"] == "unknown"
    assert summary.content["externalEffectState"] == "unknown"
    assert summary.canonicalAuthorityRefs == ["workflow_definition_revisions"]
    claim = next(claim for claim in result.claims if claim.kind == "registered_workflow_definition_revision")
    assert claim.claimState == EpistemicStatus.OBSERVED
    assert claim.evidenceRefs[0].id == second.record_id
    assert sections["runs"].state == "unknown"


@pytest.mark.asyncio
async def test_workflow_definition_registrar_identity_requires_exact_current_human_proof() -> None:
    definition = WorkflowDefinitionRevision(
        workflow_id="workflow-registrar",
        tenant_id=TENANT_A,
        revision=1,
        name="Registered workflow",
        actor_ref="tenant-user-1",
        created_at="2026-10-20T10:00:00Z",
    )
    repository = WorkflowDefinitionRepository(FakeWorkflowDefinitionFactStore())
    await repository.register(definition)
    definition_read = await repository.read_latest(TENANT_A, definition.workflow_id)

    class DefinitionSource(FakeWorkflowSource):
        def __init__(self, identities: WorkflowPrincipalIdentityRead) -> None:
            super().__init__(
                WorkflowRunInvocationRead((), True, True),
                principal_identities=identities,
            )

        async def workflow_definition(self, *, tenant_id: str, workflow_id: str):
            assert (tenant_id, workflow_id) == (TENANT_A, definition.workflow_id)
            return definition_read

        async def workflow_definition_as_of(
            self, *, tenant_id: str, workflow_id: str, as_of: datetime
        ):
            assert (tenant_id, workflow_id) == (TENANT_A, definition.workflow_id)
            return definition_read

    request = _request(subject_kind="workflow", subject_id=definition.workflow_id)
    request = request.model_copy(
        update={
            "subject": ProjectionSubject.model_construct(
                kind="workflow", id=definition.workflow_id
            )
        }
    )
    source = DefinitionSource(
        WorkflowPrincipalIdentityRead(
            (_principal_identity("tenant-user-1"),), True, True
        )
    )
    result = await Workflow360Provider(source=source).project(request, _context())
    summary = _sections(result)["workflow_summary"]
    assert source.principal_identity_calls == [
        (TENANT_A, {"tenant-user-1"}, 1)
    ]
    assert summary.state == "available"
    assert summary.content["registrarIdentityState"] == "resolved"
    assert summary.canonicalAuthorityRefs == ["workflow_definition_revisions", "identity"]
    assert summary.content["registeredByCanonicalHumanEntityId"] == "canonical-human-a"
    assert {ref["source"] for ref in summary.content["registrarIdentityEvidenceRefs"]} == {
        "identity_aliases",
        "identity_subjects",
    }
    claim = next(
        item
        for item in result.claims
        if item.kind == "registered_workflow_definition_registrar_identity"
    )
    assert {ref.source for ref in claim.evidenceRefs} == {
        "workflow.workflow_definition_revisions",
        "identity_aliases",
        "identity_subjects",
    }
    assert "run initiator or approver" in claim.claims[0]

    foreign_source = DefinitionSource(
        WorkflowPrincipalIdentityRead(
            (_principal_identity("tenant-user-1", tenant_id="tenant-other"),),
            True,
            True,
        )
    )
    foreign = await Workflow360Provider(source=foreign_source).project(
        request, _context()
    )
    foreign_summary = _sections(foreign)["workflow_summary"]
    assert foreign_summary.state == "available"
    assert foreign_summary.content["registrarIdentityState"] == "unknown"
    assert foreign_summary.content["registeredByCanonicalHumanEntityId"] is None
    assert foreign_summary.content["registrarIdentityEvidenceRefs"] == []
    assert not any(
        item.kind == "registered_workflow_definition_registrar_identity"
        for item in foreign.claims
    )

    ambiguous_source = DefinitionSource(
        WorkflowPrincipalIdentityRead(
            (
                _principal_identity("tenant-user-1"),
                _principal_identity(
                    "tenant-user-1", canonical_human_entity_id="another-human"
                ),
            ),
            True,
            True,
        )
    )
    ambiguous = await Workflow360Provider(source=ambiguous_source).project(
        request, _context()
    )
    assert (
        _sections(ambiguous)["workflow_summary"].content["registrarIdentityState"]
        == "ambiguous"
    )
    assert not any(
        item.kind == "registered_workflow_definition_registrar_identity"
        for item in ambiguous.claims
    )

    historical_source = DefinitionSource(
        WorkflowPrincipalIdentityRead(
            (_principal_identity("tenant-user-1"),), True, True
        )
    )
    historical_request = request.model_copy(
        update={"asOf": "2026-10-21T00:00:00+00:00"}
    )
    historical = await Workflow360Provider(source=historical_source).project(
        historical_request, _context()
    )
    historical_summary = _sections(historical)["workflow_summary"]
    assert historical_source.principal_identity_calls == []
    assert historical_summary.content["registrarIdentityState"] == "unknown"
    assert historical_summary.content["registrarIdentityReason"] == (
        "historical_identity_replay_unavailable"
    )


@pytest.mark.asyncio
async def test_registered_workflow_definition_as_of_uses_known_effective_revision_only() -> None:
    fact_store = FakeWorkflowDefinitionFactStore()
    repository = WorkflowDefinitionRepository(fact_store)
    first = WorkflowDefinitionRevision(
        workflow_id="workflow-historical",
        tenant_id=TENANT_A,
        revision=1,
        name="Initial",
        actor_ref="tenant-user-1",
        created_at="2026-10-20T10:00:00Z",
        effective_at="2026-10-20T11:00:00Z",
    )
    second = WorkflowDefinitionRevision.model_validate(
        first.model_dump(mode="json")
        | {
            "revision": 2,
            "name": "Later revision",
            "created_at": "2026-10-21T10:00:00Z",
            "effective_at": "2026-10-23T10:00:00Z",
        }
    )
    await repository.register(first)
    await repository.register(second)
    provider = Workflow360Provider(
        source=RepositoryWorkflow360Source(workflow_definition_repository=repository)
    )

    before_registration = await provider.project(
        _request(
            subject_kind="workflow",
            subject_id=first.workflow_id,
            as_of="2026-10-19T12:00:00Z",
        ),
        _context(),
    )
    empty = _sections(before_registration)["workflow_summary"]
    assert before_registration.asOf == "2026-10-19T12:00:00Z", empty.content
    assert empty.state == "empty"
    assert empty.content["reason"] == "no_registered_workflow_definition_at_as_of"

    before_effective = await provider.project(
        _request(
            subject_kind="workflow",
            subject_id=first.workflow_id,
            as_of="2026-10-22T12:00:00Z",
        ),
        _context(),
    )
    summary = _sections(before_effective)["workflow_summary"]
    assert before_effective.asOf == "2026-10-22T12:00:00Z"
    assert summary.state == "available"
    assert summary.content["revision"] == 1
    assert summary.content["definitionHistoryCoverage"] == "bounded_as_of_revision_selection"
    assert summary.content["runLinkState"] == "unknown"
    assert _sections(before_effective)["runs"].state == "unknown"
    definition_claim = next(
        claim
        for claim in before_effective.claims
        if claim.kind == "registered_workflow_definition_revision"
    )
    assert definition_claim.evidenceRefs[0].id == first.record_id

    after_effective = await provider.project(
        _request(
            subject_kind="workflow",
            subject_id=first.workflow_id,
            as_of="2026-10-24T12:00:00Z",
        ),
        _context(),
    )
    assert _sections(after_effective)["workflow_summary"].content["revision"] == 2


@pytest.mark.asyncio
async def test_workflow_definition_historical_read_fails_closed_on_scope_and_anchor_errors() -> None:
    fact_store = FakeWorkflowDefinitionFactStore()
    repository = WorkflowDefinitionRepository(fact_store)
    definition = WorkflowDefinitionRevision(
        workflow_id="workflow-history-scope",
        tenant_id=TENANT_A,
        revision=1,
        name="Scoped",
        actor_ref="tenant-user-1",
        created_at="2026-10-20T10:00:00Z",
    )
    await repository.register(definition)
    provider = Workflow360Provider(
        source=RepositoryWorkflow360Source(workflow_definition_repository=repository)
    )
    request = _request(
        subject_kind="workflow",
        subject_id=definition.workflow_id,
        as_of="2026-10-21T12:00:00Z",
    )
    mismatch = await provider.project(
        request,
        _context().model_copy(update={"asOf": "2026-10-22T12:00:00Z"}),
    )
    assert _sections(mismatch)["workflow_summary"].state == "unknown"
    assert _sections(mismatch)["workflow_summary"].content["reasonCode"] == (
        "workflow_definition_as_of_anchor_mismatch"
    )
    assert mismatch.asOf is None

    fact_store.rows[definition.record_id]["data"]["tenant_id"] = "other-tenant"
    contaminated = await provider.project(request, _context())
    assert _sections(contaminated)["workflow_summary"].state == "unknown"
    assert _sections(contaminated)["workflow_summary"].content["reasonCode"] == (
        "workflow_definition_history_evidence_invalid"
    )
    assert contaminated.asOf is None

    fact_store.rows[definition.record_id]["data"]["tenant_id"] = TENANT_A
    fact_store.rows[definition.record_id]["data"]["created_at"] = "2026-10-19T10:00:00Z"
    timestamp_conflict = await provider.project(request, _context())
    assert _sections(timestamp_conflict)["workflow_summary"].state == "unknown"
    assert _sections(timestamp_conflict)["workflow_summary"].content["reasonCode"] == (
        "workflow_definition_history_evidence_invalid"
    )


@pytest.mark.asyncio
async def test_workflow_definition_historical_read_rejects_truncated_history() -> None:
    class TruncatedFactStore(FakeWorkflowDefinitionFactStore):
        async def revisions_for_subject(
            self, tenant_id: str, workflow_id: str, *, limit: int
        ) -> list[dict[str, Any]]:
            assert tenant_id == TENANT_A
            assert workflow_id == "workflow-many-revisions"
            assert limit == 201
            return [{} for _ in range(limit)]

    repository = WorkflowDefinitionRepository(TruncatedFactStore())
    result = await repository.read_as_of(
        TENANT_A,
        "workflow-many-revisions",
        datetime.fromisoformat("2026-10-24T12:00:00+00:00"),
    )
    assert result.available is True
    assert result.complete is False
    assert result.reason == "workflow_definition_history_truncated_or_invalid"


def _reported_run_definition_source():
    definition = WorkflowDefinitionRevision(
        workflow_id="registered-run-workflow",
        tenant_id=TENANT_A,
        revision=2,
        name="Registered run workflow",
        actor_ref="tenant-registrar",
        created_at="2026-10-17T10:00:00Z",
        steps=[
            WorkflowStepDefinition(
                step_id="agent-step", kind="agent", label="Agent step",
                agent_ref="canonical-agent-a",
            )
        ],
    )
    definition_row = definition.model_dump(mode="json") | {
        "record_id": definition.record_id,
        "subject_ref": definition.workflow_id,
        "definition_digest": definition.definition_digest,
    }
    definition_evidence = workflow_definition_evidence(definition)
    assert definition_evidence is not None
    execution = _agent_execution_row("execution-definition")
    execution["workflow_definition_link"] = {
        "association_kind": "caller_reported_exact_definition_reference",
        "workflow_run_id": RUN_ID,
        "workflow_id": definition.workflow_id,
        "revision": definition.revision,
        "definition_record_id": definition.record_id,
        "definition_digest": definition.definition_digest,
        "definition_evidence_ref": definition_evidence.model_dump(mode="json"),
        "reference_checked_at": "2026-10-18T09:59:59Z",
    }

    class DefinitionSource(FakeWorkflowSource):
        def __init__(self) -> None:
            super().__init__(
                WorkflowRunInvocationRead(
                    (_row("invocation-a", action_id="execution-definition", agent_id="canonical-agent-a"),),
                    True,
                    True,
                ),
                agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
            )
            self.definition_read = WorkflowDefinitionRead(
                rows=(definition_row,), available=True, complete=True
            )
            self.definition_calls: list[tuple[str, str, datetime]] = []

        async def workflow_definition_as_of(
            self, *, tenant_id: str, workflow_id: str, as_of: datetime
        ) -> WorkflowDefinitionRead:
            self.definition_calls.append((tenant_id, workflow_id, as_of))
            return self.definition_read

    return DefinitionSource(), definition, execution, definition_row


@pytest.mark.asyncio
async def test_workflow_run_projects_only_exact_reported_definition_association() -> None:
    source, definition, _execution, _definition_row = _reported_run_definition_source()
    result = await Workflow360Provider(source=source).project(_request(), _context())

    summary = _sections(result)["workflow_summary"]
    assert summary.state == "degraded"
    assert summary.content["associationKind"] == "caller_reported_exact_definition_reference"
    assert summary.content["workflowId"] == definition.workflow_id
    assert summary.content["revision"] == definition.revision
    assert summary.content["associatedExecutionIds"] == ["execution-definition"]
    assert summary.content["triggerExecutionState"] == "unknown"
    assert summary.content["stepExecutionState"] == "unknown"
    assert summary.content["externalEffectState"] == "unknown"
    assert {ref["source"] for ref in summary.content["evidenceRefs"]} == {
        "workflow.workflow_definition_revisions",
        "agent_executions",
        "ai_execution_facts",
    }
    claim = next(
        item for item in result.claims
        if item.kind == "workflow_run_reported_definition_association"
    )
    assert claim.claimState == EpistemicStatus.OBSERVED
    assert "does not prove" in claim.claims[0]
    assert source.definition_calls == [
        (TENANT_A, definition.workflow_id, datetime.fromisoformat("2026-10-18T09:59:59+00:00"))
    ]


@pytest.mark.asyncio
async def test_workflow_run_definition_link_fails_closed_on_conflicts_and_incomplete_history() -> None:
    source, definition, execution, definition_row = _reported_run_definition_source()
    provider = Workflow360Provider(source=source)

    execution["workflow_definition_link"]["definition_digest"] = "a" * 64
    mismatch = await provider.project(_request(), _context())
    assert _sections(mismatch)["workflow_summary"].state == "unknown"
    assert not any(
        item.kind == "workflow_run_reported_definition_association"
        for item in mismatch.claims
    )
    execution["workflow_definition_link"]["definition_digest"] = definition.definition_digest

    source.definition_read = WorkflowDefinitionRead(
        rows=(definition_row,), available=True, complete=False,
        reason="workflow_definition_history_truncated_or_invalid",
    )
    incomplete = await provider.project(_request(), _context())
    assert _sections(incomplete)["workflow_summary"].content["reasonCode"] == (
        "workflow_run_definition_history_incomplete"
    )

    source.definition_read = WorkflowDefinitionRead(
        rows=(definition_row | {"tenant_id": "other-tenant"},),
        available=True, complete=True,
    )
    foreign = await provider.project(_request(), _context())
    assert _sections(foreign)["workflow_summary"].content["reasonCode"] == (
        "workflow_run_definition_reference_mismatch"
    )

    source.definition_read = WorkflowDefinitionRead(
        rows=(definition_row,), available=True, complete=True
    )
    execution["workflow_definition_link"]["reference_checked_at"] = "2026-10-18T10:00:01Z"
    late = await provider.project(_request(), _context())
    assert _sections(late)["workflow_summary"].content["reasonCode"] == (
        "workflow_run_definition_link_invalid_or_missing"
    )
    execution["workflow_definition_link"]["reference_checked_at"] = "2026-10-18T09:59:59Z"

    historical = await provider.project(
        _request(as_of="2026-10-18T10:00:00Z"), _context()
    )
    assert _sections(historical)["workflow_summary"].content["reasonCode"] == (
        "workflow_run_definition_historical_replay_unavailable"
    )

    execution["workflow_run_invocation_ids"] = []
    missing_run_link = await provider.project(_request(), _context())
    assert _sections(missing_run_link)["workflow_summary"].state == "unknown"
    assert not any(
        item.kind == "workflow_run_reported_definition_association"
        for item in missing_run_link.claims
    )


@pytest.mark.asyncio
async def test_workflow_approval_agent_access_requires_exact_slot_and_joins_grant(monkeypatch):
    from shared.intelligence_projections.contracts import ProjectionReadAuthorization
    from repositories import repos

    execution = _agent_execution_row()
    scope = {"actions": ["pay"], "resources": ["order:1"], "max_amount": "10"}
    execution.update({"approval_id": "approval-a", "approval_decision_id": "decision-a",
                      "created_at": "2026-10-18T10:00:03Z",
                      "input_snapshot": {"action": "pay", "resource": "order:1", "amount": "5"},
                      "policy_log": {"delegation_check_tenant_id": TENANT_A, "delegation_check": {
                          "allowed": True, "delegation_id": "delegation-a", "matched_scope": scope,
                          "evaluated_at": "2026-10-18T10:00:02Z"}}})
    approval = {"tenant_id": TENANT_A, "workflow_run_id": RUN_ID, "execution_id": "agent-execution-a",
                "approval_id": "approval-a", "decision_id": "decision-a", "action": "approve",
                "requester_id": "canonical-agent-a", "requester_type": "agent", "execution_action": "pay",
                "resource_id": "order:1", "approved_amount_usd": 5, "decided_by": "operator-a",
                "decided_at": "2026-10-18T10:00:01Z", "permission_receipt": {
                    "receipt_id": "receipt-a", "tenant_id": TENANT_A, "approval_id": "approval-a",
                    "execution_id": "agent-execution-a", "principal_id": "operator-a",
                    "permission": "commerce:approve", "checked_at": "2026-10-18T10:00:00Z"}}
    class Grants:
        calls = 0
        async def find_by_id(self, grant_id):
            type(self).calls += 1
            assert grant_id == "delegation-a"
            return {"tenant_id": TENANT_A, "delegation_id": grant_id, "grantee_entity_id": "canonical-agent-a", "grantor_entity_id": "owner-a",
                    "scope": scope, "created_at": "2026-10-18T09:00:00Z"}
    monkeypatch.setattr(repos, "DelegationRepository", Grants)
    source = FakeWorkflowSource(
        WorkflowRunInvocationRead((_row("invocation-a", agent_id="canonical-agent-a", action_id="agent-execution-a"),), True, True),
        agent_executions=WorkflowAgentExecutionRead((execution,), True, True),
        approvals=WorkflowApprovalRead((approval,), True, True))
    request = _request()
    denied = await Workflow360Provider(source=source).project(request, _context())
    assert Grants.calls == 0
    assert _sections(denied)["approvals"].content["approvals"][0]["agentAccess"]["state"] == "unknown"
    context = _context()
    context.experience360ReadAuthorizations = [ProjectionReadAuthorization(
        tenantId=TENANT_A, sourceSurfaceId="workflow360", sourceSubject=request.subject,
        sourceSlotId="approvals", consumerProjectionId="workflow360", targetProjectionId="agent360",
        capabilityKey="agent360.read", policyState="allowed", policyIds=["policy-1"],
        policyEvaluatedAt="2026-10-18T10:01:00Z")]
    result = await Workflow360Provider(source=source).project(request, context)
    access = _sections(result)["approvals"].content["approvals"][0]["agentAccess"]
    assert Grants.calls == 1 and access["state"] == "recorded_request_time_allow"
    assert access["delegationId"] == "delegation-a" and access["currentAuthorization"] == "unknown"
    assert "agent_access" in _sections(result)["approvals"].canonicalAuthorityRefs
    historical = request.model_copy(update={"asOf": "2026-10-18T10:01:00Z"})
    history = await Workflow360Provider(source=source).project(historical, context)
    assert Grants.calls == 1
    assert _sections(history)["approvals"].content["approvals"][0]["agentAccess"]["state"] == "unknown"


@pytest.mark.asyncio
async def test_workflow_action_authorities_require_slot_envelopes_and_keep_effect_unknown(monkeypatch):
    import uuid
    from intelligence.workflow import action_authorities, approval_agent_access
    from shared.intelligence_projections.contracts import ProjectionReadAuthorization

    execution = _agent_execution_row()
    execution.update({"created_at": "2026-10-18T10:00:00Z", "ended_at": "2026-10-18T10:00:03Z",
                      "id": "agent-execution-a",
                      "approval_id": "approval-a", "approval_decision_id": "decision-a",
                      "outcome_event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"aether:agent-execution:{TENANT_A}:agent-execution-a:completed")),
                      "outcome_event_published": True})
    action = {"tenant_id": TENANT_A, "workflow_run_id": RUN_ID, "execution_id": "agent-execution-a",
              "agent_id": "canonical-agent-a", "tool_id": "tool-a", "called_at": "2026-10-18T10:00:01Z",
              "evidence_ref": {"id": "call-a", "type": "event", "source": "graph_edges", "observedAt": "2026-10-18T10:00:01Z"},
              "tool_evidence_ref": {"id": f"{TENANT_A}:tool:tool-a", "type": "entity", "source": "graph_vertices"}}
    approval = {"tenant_id": TENANT_A, "workflow_run_id": RUN_ID, "execution_id": "agent-execution-a",
                "approval_id": "approval-a", "decision_id": "decision-a", "action": "approve",
                "decided_by": "operator-a", "decided_at": "2026-10-18T10:00:00Z"}
    class Source(FakeWorkflowSource):
        async def run_execution_actions(self, **kwargs): return WorkflowActionRead((action,), True, True)
    source = Source(WorkflowRunInvocationRead((_row("invocation-a", agent_id="canonical-agent-a", action_id="agent-execution-a"),), True, True),
                    agent_executions=WorkflowAgentExecutionRead((execution,), True, True), approvals=WorkflowApprovalRead((approval,), True, True))
    calls = []
    async def access(**kwargs):
        calls.append("access")
        return approval_agent_access.ApprovalAgentAccessRead(({"tenant_id": TENANT_A, "workflow_run_id": RUN_ID,
            "execution_id": "agent-execution-a", "approval_id": "approval-a", "decision_id": "decision-a",
            "delegation_id": "delegation-a", "requested_resource": "resource-a", "evaluated_at": "2026-10-18T10:00:00Z"},), True, True)
    async def resources(**kwargs):
        calls.append("resource")
        return [{"execution_id": "agent-execution-a", "resource_id": "resource-a", "approval_id": "approval-a",
                 "decision_id": "decision-a", "delegation_id": "delegation-a", "registered_at": "2026-10-18T09:00:00Z"}]
    monkeypatch.setattr(approval_agent_access, "read_approval_agent_access", access)
    monkeypatch.setattr(action_authorities, "approved_resources", resources)
    request = _request()
    denied = await Workflow360Provider(source=source).project(request, _context())
    assert calls == []
    assert _sections(denied)["actions"].content["actions"][0]["executionResult"]["state"] == "unknown"
    context = _context()
    context.experience360ReadAuthorizations = [ProjectionReadAuthorization(
        tenantId=TENANT_A, sourceSurfaceId="workflow360", sourceSubject=request.subject, sourceSlotId="actions",
        consumerProjectionId="workflow360", targetProjectionId=target, capabilityKey=capability,
        policyState="allowed", policyIds=["policy-1"], policyEvaluatedAt="2026-10-18T10:01:00Z")
        for target, capability in (("agent360", "agent360.read"), ("commerce360", "commerce360.read"))]
    result = await Workflow360Provider(source=source).project(request, context)
    projected = _sections(result)["actions"].content["actions"][0]
    assert calls == ["access", "resource"]
    assert projected["executionResult"]["state"] == "recorded_executor_completion"
    assert projected["executionResult"]["toolResult"] == "unknown"
    assert projected["approvedResource"]["resourceId"] == "resource-a"
    assert projected["approvedResource"]["resourceOperation"] == "unknown"
    assert {claim.kind for claim in result.claims} >= {"workflow_linked_executor_result", "workflow_linked_approved_resource"}
    assert _sections(result)["approvals"].content["approvals"][0]["agentAccess"]["state"] == "unknown"
