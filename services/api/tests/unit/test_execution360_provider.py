"""Focused contract tests for the Execution360 provider slice."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from actions.agent.execution360_provider import (  # noqa: E402
    ExecutionApprovalRead,
    ExecutionCostRead,
    ExecutionEpisodeContextRead,
    ExecutionPrincipalIdentityRead,
    ExecutionRiskAssessmentRead,
    ExecutionRiskEventRead,
    ExecutionToolCallRead,
    ExecutionWorkflowRunInvocationRead,
    OUTPUT_SECTIONS,
    Execution360Provider,
    ExecutionRead,
    RepositoryExecution360Source,
    _read_agent_episode_context,
    _read_execution_principal_identities,
    _resolve_server_delegation_reference,
    register_provider,
)
from actions.agent.identity_resolution import (  # noqa: E402
    resolve_agent_identities,
)
from graph.operational_intelligence.models import EntityRef, EvidenceRef, TimeRangeFilter  # noqa: E402
from shared.backend_interpretation.primitives import EpisodeRecord  # noqa: E402
from shared.backend_interpretation.stores import EpisodePageRead, EpisodeStore  # noqa: E402
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    ClaimEnvelope,
    Experience360ActorAttribution,
    Experience360ActorParty,
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    ProjectionSection,
)
from shared.intelligence_projections.composition import compose_experience360_frame  # noqa: E402
from shared.intelligence_projections.frame_runtime import (  # noqa: E402
    _derive_agent_actor_metadata,
)
from shared.intelligence_projections import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSubject,
    ProviderRegistry,
)
from shared.store import InMemoryStore  # noqa: E402


TENANT = "tenant-execution360"
AGENT = "agent-canonical-1"


def _request(**overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "execution360",
        "tenantId": TENANT,
        "subject": ProjectionSubject(kind="agent", id=AGENT),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


async def _context(request: ProjectionRequest) -> ProjectionContext:
    return await ProviderRegistry().build_context("execution360", request)


def _server_row(tenant_id: str = TENANT, agent_id: str = AGENT) -> dict:
    return {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "execution_id": "exec-1",
        "delegation_id": "deleg-1",
        "canonical_delegation_id": "deleg-1",
        "canonical_delegation_matched": True,
        "canonical_delegation_resolution_status": "matched_current_grant_reference_and_grantee",
        "canonical_delegation_evidence_observed_at": "2026-10-16T08:00:00+00:00",
        "canonical_agent_identity": True,
        "canonical_agent_entity_id": AGENT,
        "canonical_owner_entity_id": "owner-1",
        "status": "completed",
        "started_at": "2026-10-16T10:00:00+00:00",
        "ended_at": "2026-10-16T10:00:02+00:00",
        "triggered_by_event_id": "trigger-1",
        "input_snapshot": {
            "action": "transfer",
            "resource": "account:4",
            "payload": {"secret": "must-not-appear"},
        },
        "policy_log": {"delegation_check": {"allowed": True, "delegation_id": "deleg-1"}},
        "reasoning": "must-not-appear",
        "output": {"secret": "must-not-appear"},
    }


def _agent360_principal_result(
    *,
    identity_state: str,
    canonical_human_id: str | None,
    candidate_human_ids: list[str],
    principal_state: str = "available",
    raw_principal_ids: list[str] | None = None,
) -> ProjectionResult:
    raw_principal_ids = raw_principal_ids or ["human-principal-1"]
    execution_evidence_refs = [
        EvidenceRef(
            id=f"execution-{index}",
            type="event",
            source="agent_executions",
            observedAt="2026-10-16T10:00:00Z",
        )
        for index, _ in enumerate(raw_principal_ids, start=1)
    ]
    alias_evidence_refs = [
        EvidenceRef(
            id=f"user-id-alias-{index}",
            type="entity",
            source="identity_aliases",
            observedAt="2026-10-16T10:00:00Z",
        )
        for index, _ in enumerate(raw_principal_ids, start=1)
    ]
    subject_evidence = EvidenceRef(
        id="human-subject-1",
        type="entity",
        source="identity_subjects",
        observedAt="2026-10-16T10:00:00Z",
    )
    agent_identity_evidence = EvidenceRef(
        id="agent-binding-1",
        type="entity",
        source="agent_deployment_identity_bindings",
        observedAt="2026-10-16T10:00:00Z",
    )
    return ProjectionResult(
        projectionId="agent360",
        tenantId=TENANT,
        contractVersion="1.0.0",
        sections=[
            ProjectionSection(
                id="state",
                state="available",
                content={
                    "dimensions": [
                        {
                            "id": "actor_attribution",
                            "state": "matched",
                            "content": {
                                "resolvedCanonicalActor": AGENT,
                                "executionPrincipal": {
                                    "kind": "human",
                                    "id": raw_principal_ids[0],
                                }
                                if len(raw_principal_ids) == 1
                                else None,
                                "executionPrincipalState": principal_state,
                                "executionPrincipalCandidates": [
                                    {
                                        "principal": {"kind": "human", "id": principal_id},
                                        "executionIds": [f"execution-{index}"],
                                        "evidenceRefs": [
                                            execution_evidence_refs[index - 1].model_dump(
                                                mode="json"
                                            )
                                        ],
                                    }
                                    for index, principal_id in enumerate(raw_principal_ids, start=1)
                                ],
                                "executionPrincipalEvidenceRefs": [
                                    evidence.model_dump(mode="json")
                                    for evidence in execution_evidence_refs
                                ],
                                "executionPrincipalCanonicalIdentity": {
                                    "state": identity_state,
                                    "canonicalHumanEntityId": canonical_human_id,
                                    "candidateEntityIds": candidate_human_ids,
                                    "evidenceRefs": [
                                        evidence.model_dump(mode="json")
                                        for evidence in alias_evidence_refs
                                    ]
                                    + [
                                        subject_evidence.model_dump(mode="json"),
                                    ],
                                },
                            },
                        }
                    ]
                },
            )
        ],
        claims=[
            ClaimEnvelope(
                id="agent_identity_binding.agent-1",
                kind="canonically_resolved_agent_identity",
                subject=ProjectionSubject(kind="agent", id=AGENT),
                evidenceRefs=[agent_identity_evidence],
                claims=["The tenant binding resolves the agent identity."],
                claimState=EpistemicStatus.RESOLVED,
                domainSlotIds=["identity", "actor_attribution"],
            )
        ],
        dependencyState=[],
        generatedAt="2026-10-16T10:01:00Z",
        degradedReasons=[],
    )


def _execution_result_with_principal(principal_user_id: str) -> ProjectionResult:
    return _execution_result_with_principals([principal_user_id])


def _execution_result_with_principals(principal_user_ids: list[str]) -> ProjectionResult:
    evidence_by_execution_id = {
        f"execution-{index}": EvidenceRef(
            id=f"execution-{index}",
            type="event",
            source="agent_executions",
            observedAt="2026-10-16T10:00:00Z",
        )
        for index, _ in enumerate(principal_user_ids, start=1)
    }
    return ProjectionResult(
        projectionId="execution360",
        tenantId=TENANT,
        contractVersion="1.0.0",
        sections=[
            ProjectionSection(
                id="state",
                state="available",
                content={
                    "sourceStates": {"serverRecordedLifecycle": "available"},
                    "serverRecordedExecutions": [
                        {
                            "executionId": f"execution-{index}",
                            "initiatingPrincipalUserId": principal_user_id,
                        }
                        for index, principal_user_id in enumerate(principal_user_ids, start=1)
                    ],
                },
            )
        ],
        claims=[
            ClaimEnvelope(
                id=f"execution.principal-{index}",
                kind="authenticated_execution_principal",
                subject=ProjectionSubject(kind="agent", id=AGENT),
                evidenceRefs=[evidence_by_execution_id[f"execution-{index}"]],
                claims=["AETHER recorded the authenticated initiating principal."],
                claimState=EpistemicStatus.OBSERVED,
            )
            for index, _ in enumerate(principal_user_ids, start=1)
        ],
        dependencyState=[],
        generatedAt="2026-10-16T10:01:00Z",
        degradedReasons=[],
    )


def _observed_row(tenant_id: str = TENANT, actor_id: str = AGENT) -> dict:
    return {
        "tenantId": tenant_id,
        "sourceEventId": "silver-event-1",
        "occurredAt": "2026-10-16T10:00:01+00:00",
        "eventName": "agent_tool_call_observed",
        "runId": "source-run-1",
        "actorAgentId": actor_id,
        "actorIdentityStatus": "matched",
        "delegationId": "deleg-1",
        "delegationResolutionStatus": "matched_reference",
        "delegationPartyBindingStatus": "matched",
        "delegatorAgentId": AGENT,
        "delegateeAgentId": "agent-delegatee-1",
        "delegationScope": ["action:transfer", "resource:account:4"],
        "delegationValidFrom": "2026-10-16T09:00:00+00:00",
        "delegationValidUntil": "2026-10-17T09:00:00+00:00",
        "delegationStatus": "granted",
        "delegationEvidenceId": "deleg-1",
        "delegationEvidenceObservedAt": "2026-10-16T08:00:00+00:00",
        "authorizationStatus": "within_scope",
        "actionType": "transfer",
        "resourceRef": "account:4",
        "toolName": "payments.send",
        "reportedStatus": "completed",
        # Reader additions cannot upgrade external occurrence evidence.
        "executionOccurrence": "verified",
        "executionVerified": True,
    }


def _task_decomposition_row(
    *, execution_id: str = "exec-1", tenant_id: str = TENANT
) -> dict:
    return {
        "tenant_id": tenant_id,
        "agent_id": AGENT,
        "execution_id": execution_id,
        "record_id": f"{execution_id}:decomposition",
        "event_type": "task_decomposed",
        "root_task_id": "task-root-1",
        "subtask_ids": ["task-child-1", "task-child-2"],
        "occurred_at": "2026-10-16T10:00:01+00:00",
        "canonical_agent_identity": True,
        "canonical_agent_entity_id": AGENT,
        "canonical_owner_entity_id": "owner-1",
        "metadata": {"secret": "private-plan-body"},
    }


def _execution_risk_signal_row(
    *,
    signal_id: str = "risk-exec-1",
    tenant_id: str = TENANT,
    subject_kind: str = "execution",
    subject_id: str = "exec-1",
    observed_at: str | None = "2026-10-16T10:00:01+00:00",
) -> dict:
    return {
        "signal_id": signal_id,
        "tenant_id": tenant_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "risk_dimension": "agentic",
        "claim_state": "inferred",
        "confidence": 0.82,
        "evidence_refs": [
            {
                "id": f"evidence-{signal_id}",
                "type": "model_output",
                "source": "aether.fraud.detector.agentic",
                "observedAt": observed_at,
            }
        ],
        "source": "aether.fraud.detector.agentic",
        "detector_version": "agentic-risk-v2",
        "observed_at": observed_at,
        "score": 0.64,
    }


def _execution_risk_assessment_row(
    *,
    assessment_id: str = "assessment-exec-1",
    tenant_id: str = TENANT,
    subject_kind: str = "execution",
    subject_id: str = "exec-1",
    assessed_at: str | None = "2026-10-16T10:00:02+00:00",
) -> dict:
    return {
        "assessment_id": assessment_id,
        "tenant_id": tenant_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "policy_id": "risk-policy-v2",
        "policy_version": "2",
        "dimensions": ["agentic"],
        "vector": {
            "components": [
                {
                    "dimension": "agentic",
                    "state": "observed",
                    "score": 0.61,
                    "claim_state": "inferred",
                    "confidence": 0.84,
                    "evidence_refs": [
                        {
                            "id": f"evidence-{assessment_id}",
                            "type": "model_output",
                            "source": "aether.risk.assessment.agentic",
                            "observedAt": assessed_at,
                        }
                    ],
                }
            ]
        },
        "claim_state": "inferred",
        "confidence": 0.81,
        "evidence_refs": [],
        "run_id": "risk-run-1",
        "assessed_at": assessed_at,
    }


class FakeSource:
    def __init__(
        self,
        server: ExecutionRead | None = None,
        observed: ExecutionRead | None = None,
        *,
        error: Exception | None = None,
        cost_facts: ExecutionCostRead | None = None,
        risk_events: ExecutionRiskEventRead | None = None,
        approval_decisions: ExecutionApprovalRead | None = None,
    ) -> None:
        self.server = server or ExecutionRead(
            rows=[_server_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        )
        self.observed = observed or ExecutionRead(
            rows=[_observed_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        )
        self.error = error
        self.cost_fact_read = cost_facts or ExecutionCostRead(
            rows=[], available=True, scope_known=True
        )
        self.risk_event_read = risk_events or ExecutionRiskEventRead(
            rows=[], available=True, scope_known=True
        )
        self.approval_decision_read = approval_decisions or ExecutionApprovalRead(
            rows=[], available=True, scope_known=True
        )
        self.risk_event_calls: list[tuple[str, tuple[str, ...], int]] = []
        self.approval_decision_calls: list[tuple[str, tuple[str, ...], int]] = []
        self.cost_fact_calls: list[tuple[str, tuple[tuple[str, str], ...], int]] = []

    async def server_executions(
        self, *, tenant_id: str, subject: ProjectionSubject, limit: int
    ) -> ExecutionRead:
        if self.error:
            raise self.error
        return self.server

    async def observed_facts(
        self, *, tenant_id: str, subject: ProjectionSubject, limit: int
    ) -> ExecutionRead:
        if self.error:
            raise self.error
        return self.observed

    async def execution_risk_events(
        self, *, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionRiskEventRead:
        if self.error:
            raise self.error
        self.risk_event_calls.append((tenant_id, execution_ids, limit))
        return self.risk_event_read

    async def execution_approval_decisions(
        self, *, tenant_id: str, execution_ids: tuple[str, ...], limit: int
    ) -> ExecutionApprovalRead:
        if self.error:
            raise self.error
        self.approval_decision_calls.append((tenant_id, execution_ids, limit))
        return self.approval_decision_read

    async def execution_cost_facts(
        self,
        *,
        tenant_id: str,
        executions: tuple[tuple[str, str], ...],
        limit: int,
    ) -> ExecutionCostRead:
        if self.error:
            raise self.error
        self.cost_fact_calls.append((tenant_id, executions, limit))
        return self.cost_fact_read


async def test_provider_emits_registry_sections_evidence_and_catalog_bound_claims() -> None:
    request = _request()
    context = await _context(request)
    result = await Execution360Provider(FakeSource()).project(request, context)

    assert isinstance(result, ProjectionResult)
    assert [section.id for section in result.sections] == list(OUTPUT_SECTIONS)
    assert OUTPUT_SECTIONS == (
        "evidence",
        "interactions",
        "outcomes",
        "state",
        "summary",
        "timeline",
        "episode_context",
    )
    assert result.dependencyState == context.dependencyState
    assert result.claims
    for claim in result.claims:
        assert claim.evidenceRefs
        assert all(isinstance(ref, EvidenceRef) and ref.id for ref in claim.evidenceRefs)
        assert claim.domainSlotIds
        assert set(claim.domainSlotIds) <= {
            "tool_calls",
            "actor_attribution",
            "authority_check",
            "approval_chain",
            "authority_envelope",
            "evidence_trace",
            "execution_history",
            "execution_summary",
            "inputs_outputs",
            "failures",
            "latency_cost",
            "plan_steps",
            "tool_usage",
        }

    lifecycle_claim = next(
        claim for claim in result.claims if claim.kind == "server_recorded_execution_lifecycle"
    )
    assert lifecycle_claim.domainSlotIds == [
        "execution_summary",
        "execution_history",
        "evidence_trace",
    ]
    duration_claim = next(
        claim
        for claim in result.claims
        if claim.kind == "server_recorded_lifecycle_elapsed_time"
    )
    assert duration_claim.domainSlotIds == ["latency_cost", "evidence_trace"]
    assert duration_claim.evidenceRefs[0].id == "exec-1"
    assert "2000 milliseconds" in duration_claim.claims[0]
    decision_claim = next(
        claim for claim in result.claims if claim.kind == "server_recorded_delegation_decision"
    )
    assert decision_claim.domainSlotIds == [
        "authority_check",
        "authority_envelope",
        "evidence_trace",
    ]
    joined_grant_claim = next(
        claim
        for claim in result.claims
        if claim.kind == "canonically_joined_server_delegation_reference"
    )
    assert joined_grant_claim.claimState == EpistemicStatus.RESOLVED
    assert joined_grant_claim.domainSlotIds == ["authority_check", "evidence_trace"]
    assert {ref.source for ref in joined_grant_claim.evidenceRefs} == {
        "agent_executions",
        "delegations",
    }
    observed_claim = next(
        claim for claim in result.claims if claim.kind == "source_reported_agent_telemetry_fact"
    )
    assert observed_claim.domainSlotIds == ["evidence_trace"]
    tool_claim = next(
        claim for claim in result.claims if claim.kind == "source_reported_tool_invocation"
    )
    assert tool_claim.domainSlotIds == ["tool_usage", "evidence_trace"]

    state = next(section for section in result.sections if section.id == "state")
    server_record = state.content["serverRecordedExecutions"][0]
    assert server_record["status"] == "completed"
    assert server_record["externalExecutionReceipt"] == "unknown"
    assert server_record["delegationId"] == "deleg-1"
    external = state.content["sourceReportedRuns"][0]
    assert external["occurrence"] == "source_reported"
    assert external["verified"] is False

    summary = next(section for section in result.sections if section.id == "summary")
    latency_cost = summary.content["latencyCost"]
    assert latency_cost["latency"]["state"] == "available"
    assert latency_cost["latency"]["sampleCount"] == 1
    assert latency_cost["latency"]["samples"][0]["elapsedMs"] == 2000.0
    assert latency_cost["latency"]["samples"][0]["evidenceRefs"][0]["id"] == "exec-1"
    assert latency_cost["cost"]["state"] == "unknown"
    assert latency_cost["cost"]["reason"] == (
        "no_ai_execution_invocation_linked_to_admitted_execution"
    )
    assert latency_cost["cost"]["byCurrency"] == []
    assert latency_cost["cost"]["unknownCostInvocationCount"] is None
    assert latency_cost["latency"]["aiInvocationTelemetry"]["state"] == "unknown"

    outcomes = next(section for section in result.sections if section.id == "outcomes")
    assert outcomes.state == "unknown"
    assert outcomes.content["businessOutcome"]["state"] == "unknown"
    assert outcomes.content["executorCallbacks"][0]["businessEffect"] == "not_established"

    serialized = result.model_dump_json()
    assert "must-not-appear" not in serialized
    assert "workerRunLinkage" in serialized


async def test_workflow_run_subject_admits_only_exact_lifecycle_rows() -> None:
    matching = _server_row()
    matching["workflow_run_id"] = "workflow-run-1"
    matching["workflow_run_invocation_evidence_refs"] = [
        EvidenceRef(
            id="invocation-workflow-1",
            type="event",
            source="ai_execution_facts",
            observedAt="2026-10-16T10:00:00Z",
        ).model_dump(mode="json", by_alias=True)
    ]
    other_run = _server_row()
    other_run["execution_id"] = "exec-other-run"
    other_run["workflow_run_id"] = "workflow-run-2"
    source = FakeSource(
        server=ExecutionRead(
            rows=[matching, other_run],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead(
            rows=[],
            available=True,
            scope_known=False,
            reason="source_reported_run_id_not_canonically_linked_to_workflow_run",
        ),
    )
    request = _request(
        subject=ProjectionSubject(kind="workflow_run", id="workflow-run-1")
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    executions = state.content["serverRecordedExecutions"]
    assert [row["executionId"] for row in executions] == ["exec-1"]
    assert executions[0]["workflowRunId"] == "workflow-run-1"
    linkage_claims = [
        claim
        for claim in result.claims
        if claim.kind == "server_recorded_workflow_run_execution_reference"
    ]
    assert [claim.evidenceRefs[0].id for claim in linkage_claims] == ["exec-1"]
    assert {ref.source for ref in linkage_claims[0].evidenceRefs} == {
        "agent_executions",
        "ai_execution_facts",
    }
    assert "workflow_run_execution_scope_mismatch" in result.degradedReasons
    assert "exec-other-run" not in result.model_dump_json()


async def test_latency_cost_joins_exact_canonical_ai_invocation_facts() -> None:
    source = FakeSource(
        cost_facts=ExecutionCostRead(
            rows=[
                {
                    "tenant_id": TENANT,
                    "execution_id": "exec-1",
                    "action_id": "exec-1",
                    "agent_id": AGENT,
                    "invocation_id": "invocation-1",
                    "observed_at": "2026-10-16T10:00:01+00:00",
                    "latency_ms": 340,
                    "selected_cost": "0.125",
                    "cost_basis": "billed",
                    "currency": "usd",
                }
            ],
            available=True,
            scope_known=True,
        )
    )
    request = _request()

    result = await Execution360Provider(source).project(request, await _context(request))

    summary = next(section for section in result.sections if section.id == "summary")
    latency_cost = summary.content["latencyCost"]
    assert source.cost_fact_calls == [(TENANT, (("exec-1", AGENT),), 50)]
    assert latency_cost["cost"]["state"] == "available"
    assert latency_cost["cost"]["linkage"] == (
        "exact_tenant_execution_action_id_and_agent_id"
    )
    assert latency_cost["cost"]["knownCostInvocationCount"] == 1
    assert latency_cost["cost"]["byCurrency"] == [
        {
            "currency": "USD",
            "total": 0.125,
            "factCount": 1,
            "evidenceRefs": [
                {
                    "id": "invocation-1",
                    "type": "event",
                    "source": "ai_execution_facts",
                    "observedAt": "2026-10-16T10:00:01+00:00",
                    "uri": "store://ai_execution_facts/tenant-execution360%3Ainvocation-1",
                }
            ],
        }
    ]
    invocation_latency = latency_cost["latency"]["aiInvocationTelemetry"]
    assert invocation_latency["state"] == "available"
    assert invocation_latency["samples"][0]["latencyMs"] == 340.0
    assert invocation_latency["freshness"]["state"] == "unknown"
    cost_claim = next(
        claim
        for claim in result.claims
        if claim.kind == "source_reported_execution_invocation_cost_total"
    )
    assert cost_claim.claimState == EpistemicStatus.OBSERVED
    assert cost_claim.domainSlotIds == ["latency_cost", "evidence_trace"]
    assert cost_claim.evidenceRefs[0].source == "ai_execution_facts"
    evidence_section = next(section for section in result.sections if section.id == "evidence")
    assert any(
        ref["source"] == "ai_execution_facts" and ref["id"] == "invocation-1"
        for ref in evidence_section.content["evidence"]
    )


async def test_execution_cost_source_queries_exact_tenant_action_and_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    import config.settings

    monkeypatch.setattr(
        config.settings,
        "settings",
        SimpleNamespace(ai_economics=SimpleNamespace(execution_facts_enabled=True)),
    )
    observed_calls: list[tuple[str, dict[str, object]]] = []

    async def list_exact_facts(tenant_id: str, **filters: object) -> list[dict[str, object]]:
        observed_calls.append((tenant_id, filters))
        return [
            {
                "tenant_id": tenant_id,
                "action_id": filters["action_id"],
                "agent_id": AGENT,
                "invocation_id": "invocation-1",
                "observed_at": "2026-10-16T10:00:01+00:00",
                "latency_ms": 340,
                "selected_cost": 0.125,
                "cost_basis": "billed",
                "currency": "USD",
            }
        ]

    source = RepositoryExecution360Source(ai_execution_facts_reader=list_exact_facts)
    read = await source.execution_cost_facts(
        tenant_id=TENANT,
        executions=(("exec-1", AGENT),),
        limit=50,
    )

    assert observed_calls == [(TENANT, {"action_id": "exec-1", "limit": 201})]
    assert read.available is True
    assert read.scope_known is True
    assert read.rows[0]["execution_id"] == "exec-1"
    assert read.rows[0]["action_id"] == "exec-1"
    assert read.rows[0]["agent_id"] == AGENT


async def test_execution_cost_keeps_unknown_cost_unknown_and_drops_mismatched_fact() -> None:
    source = FakeSource(
        cost_facts=ExecutionCostRead(
            rows=[
                {
                    "tenant_id": TENANT,
                    "execution_id": "exec-1",
                    "action_id": "exec-1",
                    "agent_id": AGENT,
                    "invocation_id": "unknown-cost-invocation",
                    "observed_at": "2026-10-16T10:00:01+00:00",
                    "latency_ms": None,
                    # A malformed/corrupt source row may carry an amount while
                    # declaring its basis unknown; do not expose it as a cost.
                    "selected_cost": "9.99",
                    "cost_basis": "unknown",
                    "currency": "USD",
                },
                {
                    "tenant_id": "foreign-tenant",
                    "execution_id": "exec-1",
                    "action_id": "exec-1",
                    "agent_id": AGENT,
                    "invocation_id": "foreign-invocation",
                    "observed_at": "2026-10-16T10:00:01+00:00",
                    "latency_ms": 12,
                    "selected_cost": 1000,
                    "cost_basis": "billed",
                    "currency": "USD",
                },
            ],
            available=True,
            scope_known=True,
        )
    )
    request = _request()

    result = await Execution360Provider(source).project(request, await _context(request))

    summary = next(section for section in result.sections if section.id == "summary")
    cost = summary.content["latencyCost"]["cost"]
    assert cost["state"] == "degraded"
    assert cost["byCurrency"] == []
    assert cost["knownCostInvocationCount"] == 0
    assert cost["unknownCostInvocationCount"] == 1
    assert [item["invocationId"] for item in cost["invocations"]] == [
        "unknown-cost-invocation"
    ]
    assert cost["invocations"][0]["selectedCost"] is None


async def test_latency_cost_read_is_skipped_when_bound_sections_are_not_requested() -> None:
    request = _request(includeSections=["timeline"])
    source = FakeSource()

    await Execution360Provider(source).project(request, await _context(request))

    assert source.cost_fact_calls == []


async def test_exact_execution_subject_reads_only_tenant_execution_record() -> None:
    request = _request(subject=ProjectionSubject(kind="execution", id="exec-1"))
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row(), _server_row(tenant_id="tenant-other")],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead(
            rows=[],
            available=True,
            scope_known=False,
            reason="execution_source_telemetry_join_unavailable",
        ),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    assert state.content["scope"] == {"kind": "execution", "id": "exec-1"}
    assert [row["executionId"] for row in state.content["serverRecordedExecutions"]] == [
        "exec-1"
    ]
    assert any(
        claim.kind == "server_recorded_execution_lifecycle"
        and claim.evidenceRefs[0].id == "exec-1"
        for claim in result.claims
    )
    assert not any(
        claim.kind == "source_reported_tool_invocation" for claim in result.claims
    )


async def test_inputs_outputs_exposes_only_recorded_metadata_and_event_reference() -> None:
    server_row = {
        **_server_row(),
        "status": "failed",
        "outcome_event_id": "outcome-ref-1",
        "outcome_event_published": False,
        "input_snapshot": {
            "action": "transfer",
            "resource": "account:4",
            "payload": {"secret": "raw-input-secret"},
        },
        "output": {"secret": "raw-output-secret"},
        "error": {"message": "raw-error-secret"},
    }
    source = FakeSource(
        server=ExecutionRead(
            rows=[server_row], available=True, scope_known=True, agent_ids=(AGENT,)
        ),
        observed=ExecutionRead(
            rows=[], available=True, scope_known=True, agent_ids=(AGENT,)
        ),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))
    state = next(section for section in result.sections if section.id == "state")
    inputs_outputs = state.content["inputsOutputs"]
    assert inputs_outputs["state"] == "available"
    assert inputs_outputs["count"] == 1
    record = inputs_outputs["records"][0]
    assert record["request"] == {
        "state": "available",
        "action": "transfer",
        "resourceRef": "account:4",
        "triggerEventRef": "trigger-1",
        "payloadRead": False,
    }
    assert record["result"]["state"] == "unknown"
    assert record["result"]["outcomeEventRef"] == "outcome-ref-1"
    assert record["result"]["eventPublicationState"] == "not_published"
    assert record["result"]["externalEffect"] == "not_established"
    assert record["evidenceRefs"][0]["id"] == "exec-1"
    assert {
        claim.kind for claim in result.claims if "inputs_outputs" in claim.domainSlotIds
    } == {
        "server_recorded_execution_request_metadata",
        "server_recorded_result_event_reference",
    }
    serialized = result.model_dump_json()
    for secret in ("raw-input-secret", "raw-output-secret", "raw-error-secret"):
        assert secret not in serialized


async def test_failures_keep_server_and_source_reported_boundaries_distinct() -> None:
    server_row = {**_server_row(), "status": "revoked", "error": {"secret": "failure-body"}}
    observed_row = {**_observed_row(), "reportedStatus": "failed"}
    source = FakeSource(
        server=ExecutionRead(
            rows=[server_row], available=True, scope_known=True, agent_ids=(AGENT,)
        ),
        observed=ExecutionRead(
            rows=[observed_row], available=True, scope_known=True, agent_ids=(AGENT,)
        ),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))
    state = next(section for section in result.sections if section.id == "state")
    failures = state.content["failures"]
    assert failures["state"] == "available"
    assert failures["count"] == 1
    assert failures["records"][0]["classification"] == "server_recorded_lifecycle_failure"
    assert failures["records"][0]["executionId"] == "exec-1"
    assert failures["unlinkedSourceReportedCount"] == 1
    unlinked = failures["unlinkedSourceReportedFailures"][0]
    assert unlinked["classification"] == "source_reported_unlinked_failure_telemetry"
    assert unlinked["sourceEventId"] == "silver-event-1"
    assert "executionId" not in unlinked
    assert all(record["externalEffect"] == "unknown" for record in failures["records"])
    assert {
        claim.kind for claim in result.claims if "failures" in claim.domainSlotIds
    } == {"server_recorded_execution_failure"}
    assert any(
        claim.kind == "source_reported_agent_failure_telemetry"
        and claim.domainSlotIds == ["evidence_trace"]
        for claim in result.claims
    )
    assert "failure-body" not in result.model_dump_json()


async def test_failure_slot_is_empty_only_with_complete_source_scope() -> None:
    request = _request()
    complete = await Execution360Provider(FakeSource()).project(
        request, await _context(request)
    )
    complete_state = next(section for section in complete.sections if section.id == "state")
    assert complete_state.content["failures"]["state"] == "empty"
    assert complete_state.content["failures"]["count"] == 0
    assert not [claim for claim in complete.claims if "failures" in claim.domainSlotIds]

    partial_source = FakeSource(
        server=ExecutionRead(
            rows=[], available=True, scope_known=False, agent_ids=(AGENT,)
        )
    )
    partial = await Execution360Provider(partial_source).project(
        request, await _context(request)
    )
    partial_state = next(section for section in partial.sections if section.id == "state")
    assert partial_state.content["failures"]["state"] == "unknown"
    assert partial_state.content["failures"]["count"] is None


async def test_source_failure_without_execution_id_is_unlinked_context_only() -> None:
    observed = {**_observed_row(), "reportedStatus": "failed", "riskLevel": "high"}
    source = FakeSource(
        server=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        observed=ExecutionRead([observed], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    failures = state.content["failures"]
    assert failures["state"] == "empty"
    assert failures["records"] == []
    assert failures["count"] == 0
    assert failures["unlinkedSourceReportedCount"] == 1
    assert failures["reason"] == "source_reported_failure_unlinked_to_execution"
    assert not any("failures" in claim.domainSlotIds for claim in result.claims)


async def test_plan_steps_join_exact_task_decomposition_without_lifecycle_pollution() -> None:
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row(), _task_decomposition_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))
    state = next(section for section in result.sections if section.id == "state")
    summary = next(section for section in result.sections if section.id == "summary")
    timeline = next(section for section in result.sections if section.id == "timeline")

    assert len(state.content["serverRecordedExecutions"]) == 1
    assert summary.content["serverRecordedExecutionCount"] == 1
    assert state.content["planSteps"]["state"] == "degraded"
    assert state.content["planSteps"]["fullPlanKnown"] is False
    assert state.content["planSteps"]["observedCount"] == 1
    plan = state.content["planSteps"]["records"][0]
    assert plan["rootTaskId"] == "task-root-1"
    assert plan["subtaskIds"] == ["task-child-1", "task-child-2"]
    assert {ref["id"] for ref in plan["evidenceRefs"]} == {
        "exec-1",
        "exec-1:decomposition",
    }
    assert any(entry.get("eventName") == "task_decomposed" for entry in timeline.content["entries"])
    plan_claims = [claim for claim in result.claims if "plan_steps" in claim.domainSlotIds]
    assert len(plan_claims) == 1
    assert plan_claims[0].kind == "observed_execution_task_decomposition"
    assert {ref.id for ref in plan_claims[0].evidenceRefs} == {
        "exec-1",
        "exec-1:decomposition",
    }
    assert "private-plan-body" not in result.model_dump_json()


async def test_plan_steps_reject_unjoined_cross_tenant_and_malformed_records() -> None:
    malformed = {**_task_decomposition_row(), "record_id": "forged-record"}
    source = FakeSource(
        server=ExecutionRead(
            rows=[
                _server_row(),
                _task_decomposition_row(execution_id="other-execution"),
                _task_decomposition_row(tenant_id="other-tenant"),
                malformed,
            ],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))
    state = next(section for section in result.sections if section.id == "state")

    assert state.content["planSteps"]["state"] == "unknown"
    assert state.content["planSteps"]["records"] == []
    assert state.content["planSteps"]["observedCount"] == 0
    assert "task_decomposition_record_invalid" in result.degradedReasons
    assert not [claim for claim in result.claims if "plan_steps" in claim.domainSlotIds]
    serialized = result.model_dump_json()
    assert "other-execution:decomposition" not in serialized
    assert "forged-record" not in serialized


async def test_execution_slots_route_exact_claims_and_obey_frame_policy() -> None:
    server_row = {**_server_row(), "status": "failed"}
    source = FakeSource(
        server=ExecutionRead(
            rows=[server_row, _task_decomposition_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))
    frame_request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
        requestedSlotIds=["inputs_outputs", "failures", "plan_steps", "authority_check"],
        includeEvidence=True,
    )

    allowed = compose_experience360_frame(
        frame_request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        actor_attribution_by_slot=_derive_agent_actor_metadata(frame_request, [result]),
    )
    slots = {slot.id: slot for slot in allowed.slots}
    assert slots["inputs_outputs"].content is not None
    assert slots["failures"].content is not None
    assert slots["plan_steps"].content is not None
    assert {claim.kind for claim in slots["inputs_outputs"].claims} >= {
        "server_recorded_execution_request_metadata"
    }
    assert {claim.kind for claim in slots["failures"].claims} >= {
        "server_recorded_execution_failure"
    }
    assert {claim.kind for claim in slots["plan_steps"].claims} >= {
        "observed_execution_task_decomposition"
    }
    assert {claim.kind for claim in slots["authority_check"].claims} >= {
        "server_recorded_delegation_decision",
        "canonically_joined_server_delegation_reference",
    }
    assert all(slot.evidenceRefs and slot.provenance for slot in slots.values())

    denied = compose_experience360_frame(
        frame_request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="denied"),
    )
    assert all(
        slot.state == "suppressed"
        and slot.content is None
        and slot.claims == []
        and slot.evidenceRefs == []
        for slot in denied.slots
    )


def test_execution_slots_do_not_promote_content_without_evidence() -> None:
    result = ProjectionResult(
        projectionId="execution360",
        tenantId=TENANT,
        contractVersion=Execution360Provider.contract_version,
        sections=[
            ProjectionSection(id=section_id, state="available", content={"state": "available"})
            for section_id in OUTPUT_SECTIONS
        ],
        claims=[],
        dependencyState=[],
        generatedAt="2026-10-16T10:01:00Z",
        degradedReasons=[],
    )
    request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
        requestedSlotIds=["inputs_outputs", "failures", "plan_steps"],
        includeEvidence=True,
    )
    frame = compose_experience360_frame(
        request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
    )
    assert {slot.id for slot in frame.slots} == {
        "inputs_outputs",
        "failures",
        "plan_steps",
    }
    assert all(
        slot.state != "available"
        and slot.content is None
        and slot.evidenceRefs == []
        and slot.claims == []
        for slot in frame.slots
    )


async def test_non_tool_execution_fact_does_not_claim_tool_call_or_usage() -> None:
    observed = {**_observed_row(), "toolName": None, "eventName": "agent_run_observed"}
    source = FakeSource(
        server=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        observed=ExecutionRead(
            rows=[observed], available=True, scope_known=True, agent_ids=(AGENT,)
        ),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    assert any(claim.kind == "source_reported_agent_telemetry_fact" for claim in result.claims)
    assert not [
        claim
        for claim in result.claims
        if "tool_calls" in claim.domainSlotIds or "tool_usage" in claim.domainSlotIds
    ]
    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.content["toolInvocationLinkage"]["sourceReportedToolRelatedFactCount"] == 0


async def test_tool_telemetry_remains_unlinked_from_server_execution_without_exact_id() -> None:
    request = _request()
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead(
            rows=[_observed_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.content["toolInvocationLinkage"] == {
        "state": "unknown",
        "reason": "execution_tool_call_exact_join_not_available",
        "sourceReadState": "unavailable",
        "completeness": "unknown",
        "sourceReportedToolRelatedFactCount": 1,
        "joinedExecutionToolCalls": [],
        "evidenceRefs": [],
        "sourceReportedEvidenceRefs": [
            {
                "id": "silver-event-1",
                "type": "event",
                "source": "silver_agent_execution_facts",
                "observedAt": "2026-10-16T10:00:01+00:00",
                "uri": "store://silver_agent_execution_facts/silver-event-1",
            }
        ],
    }
    assert interactions.content["riskEventLinkage"] == {
        "state": "empty",
        "reason": "no_recorded_canonical_risk_signals_or_assessments_for_execution_subjects",
        "sourceReadState": "available",
        "completeness": "bounded_recorded_execution_subject_signals_and_assessments",
        "scopeKnown": True,
        "producerCoverage": {
            "state": "unknown",
            "reason": "execution_risk_signal_producer_inventory_not_connected",
        },
        "riskAssessmentCoverage": {
            "state": "not_read",
            "sourceReadState": "not_read",
            "authority": "risk_assessments",
            "reason": None,
            "scopeKnown": False,
            "completeness": "exact_execution_subject_snapshots_only_history_and_producer_coverage_unknown",
            "assessmentCount": None,
            "joinedExecutionRiskAssessments": [],
            "evidenceRefs": [],
            "truncated": False,
        },
        "joinedExecutionRiskEvents": [],
        "evidenceRefs": [],
        "freshness": {
            "state": "unknown",
            "latestObservedAt": None,
            "reason": "no_execution_risk_freshness_threshold_is_configured",
        },
        "truncated": False,
    }
    assert interactions.content["approvalChainLinkage"] == {
        "state": "unknown",
        "reason": "no_linked_commerce_approval_non_commerce_authority_coverage_unknown",
        "sourceReadState": "available",
        "completeness": "x402_commerce_approval_requests_and_decisions_only",
        "scopeKnown": True,
        "truncated": False,
        "effectiveAuthorization": {
            "state": "unknown",
            "reason": "commerce_approval_evidence_does_not_evaluate_effective_agent_action_authority",
        },
        "freshness": {
            "state": "unknown",
            "latestObservedAt": None,
            "reason": "no_execution_approval_freshness_threshold_is_configured",
        },
        "otherApprovalAuthorityCoverage": {
            "state": "unknown",
            "reason": "non_commerce_approval_authorities_are_not_joined",
        },
        "joinedExecutionApprovalRequests": [],
        "joinedExecutionApprovals": [],
        "evidenceRefs": [],
    }
    source_reported = next(
        item
        for item in interactions.content["interactions"]
        if item["source"] == "silver_agent_execution_facts"
    )
    assert source_reported["toolName"] == "payments.send"
    assert source_reported["runId"] == "source-run-1"
    assert "executionId" not in source_reported


async def test_commerce_approval_decision_joins_exact_tenant_execution_and_lifecycle_ref() -> None:
    server = _server_row()
    server.update(
        {
            "approval_id": "approval-1",
            "approval_decision_id": "decision-1",
        }
    )
    source = FakeSource(
        server=ExecutionRead(
            rows=[server],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        approval_decisions=ExecutionApprovalRead(
            rows=[
                {
                    "tenant_id": TENANT,
                    "execution_id": "exec-1",
                    "approval_id": "approval-1",
                    "decision_id": "decision-1",
                    "action": "approve",
                    "decided_by": "human-1",
                    "decided_at": "2026-10-16T09:59:00+00:00",
                    "is_override": False,
                }
            ],
            available=True,
            scope_known=True,
            approval_requests=(
                {
                    "tenant_id": TENANT,
                    "execution_id": "exec-1",
                    "approval_id": "approval-1",
                    "execution_action": "transfer",
                    "resource_id": "account:4",
                    "created_at": "2026-10-16T09:58:00+00:00",
                },
            ),
        ),
    )

    result = await Execution360Provider(source).project(_request(), await _context(_request()))

    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["approvalChainLinkage"]
    assert linkage["state"] == "partial"
    assert linkage["sourceReadState"] == "available"
    assert linkage["scopeKnown"] is True
    request_record = linkage["joinedExecutionApprovalRequests"][0]
    assert request_record["executionId"] == "exec-1"
    assert request_record["approvalId"] == "approval-1"
    assert request_record["action"] == "transfer"
    assert request_record["resourceId"] == "account:4"
    assert request_record["lifecycleRequestMatch"] == "matched"
    assert request_record["evidenceRef"]["source"] == "commerce_approvals"
    assert linkage["effectiveAuthorization"]["state"] == "unknown"
    assert linkage["freshness"] == {
        "state": "unknown",
        "latestObservedAt": "2026-10-16T09:59:00+00:00",
        "reason": "no_execution_approval_freshness_threshold_is_configured",
    }
    assert linkage["otherApprovalAuthorityCoverage"]["state"] == "unknown"
    assert linkage["joinedExecutionApprovals"][0]["executionId"] == "exec-1"
    assert linkage["joinedExecutionApprovals"][0]["decisionId"] == "decision-1"
    assert linkage["joinedExecutionApprovals"][0]["authorizedExecutionDecision"] is True
    assert linkage["evidenceRefs"][0]["source"] == "commerce_approval_decisions"
    claim = next(
        claim for claim in result.claims if claim.kind == "canonically_linked_commerce_approval_decision"
    )
    assert claim.domainSlotIds == ["approval_chain", "evidence_trace"]
    request_claim = next(
        claim
        for claim in result.claims
        if claim.kind == "canonically_linked_commerce_approval_request"
    )
    assert request_claim.evidenceRefs[0].source == "commerce_approvals"
    assert request_claim.domainSlotIds == ["approval_chain", "evidence_trace"]


@pytest.mark.parametrize(
    "approval_request",
    [
        {
            "tenant_id": TENANT,
            "execution_id": "exec-1",
            "approval_id": "approval-1",
            "execution_action": "transfer",
            "resource_id": "account:other",
            "created_at": "2026-10-16T09:58:00+00:00",
        },
        {
            "tenant_id": "tenant-other",
            "execution_id": "exec-1",
            "approval_id": "approval-1",
            "execution_action": "transfer",
            "resource_id": "account:4",
            "created_at": "2026-10-16T09:58:00+00:00",
        },
        {
            "tenant_id": TENANT,
            "execution_id": "exec-1",
            "approval_id": "approval-other",
            "execution_action": "transfer",
            "resource_id": "account:4",
            "created_at": "2026-10-16T09:58:00+00:00",
        },
        {
            "tenant_id": TENANT,
            "execution_id": "exec-other",
            "approval_id": "approval-1",
            "execution_action": "transfer",
            "resource_id": "account:4",
            "created_at": "2026-10-16T09:58:00+00:00",
        },
    ],
    ids=[
        "lifecycle_resource_conflict",
        "foreign_tenant_request",
        "approval_id_conflict",
        "execution_id_conflict",
    ],
)
async def test_execution_approval_request_conflict_is_degraded_and_not_joined(
    approval_request: dict[str, str],
) -> None:
    server = _server_row()
    server.update({"approval_id": "approval-1", "approval_decision_id": "decision-1"})
    source = FakeSource(
        server=ExecutionRead(
            rows=[server],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        approval_decisions=ExecutionApprovalRead(
            rows=[
                {
                    "tenant_id": TENANT,
                    "execution_id": "exec-1",
                    "approval_id": "approval-1",
                    "decision_id": "decision-1",
                    "action": "approve",
                    "decided_by": "human-1",
                    "decided_at": "2026-10-16T09:59:00+00:00",
                    "is_override": False,
                }
            ],
            available=True,
            scope_known=True,
            approval_requests=(approval_request,),
        ),
    )

    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["approvalChainLinkage"]
    assert linkage["state"] == "degraded"
    assert linkage["scopeKnown"] is False
    assert linkage["joinedExecutionApprovalRequests"] == []
    assert not [
        claim
        for claim in result.claims
        if claim.kind == "canonically_linked_commerce_approval_request"
    ]
    if approval_request["resource_id"] == "account:other":
        assert linkage["joinedExecutionApprovals"] == []
        assert not [
            claim
            for claim in result.claims
            if claim.kind == "canonically_linked_commerce_approval_decision"
        ]


async def test_repository_approval_request_read_is_bounded_and_exactly_scoped() -> None:
    from types import SimpleNamespace

    approval = {
        "tenant_id": TENANT,
        "execution_id": "exec-1",
        "approval_id": "approval-1",
        "execution_action": "transfer",
        "resource_id": "account:4",
        "created_at": "2026-10-16T09:58:00+00:00",
    }

    class Commerce:
        async def list_approval_decisions_for_executions(
            self, tenant_id: str, execution_ids: list[str], limit: int
        ) -> list[object]:
            assert tenant_id == TENANT
            assert execution_ids == ["exec-1"]
            assert 0 < limit <= 5000
            return []

        async def list_approvals_for_execution(
            self, tenant_id: str, execution_id: str, limit: int
        ) -> list[object]:
            assert tenant_id == TENANT
            assert execution_id == "exec-1"
            assert 0 < limit <= 500
            return [SimpleNamespace(model_dump=lambda **_: approval)]

    read = await RepositoryExecution360Source(commerce_store=Commerce()).execution_approval_decisions(
        tenant_id=TENANT,
        execution_ids=("exec-1",),
        limit=10,
    )

    assert read.available is True
    assert read.scope_known is True
    assert read.truncated is False
    assert read.approval_requests == (approval,)


async def test_repository_approval_request_sentinel_marks_bounded_read_truncated() -> None:
    from types import SimpleNamespace

    approvals = [
        {
            "tenant_id": TENANT,
            "execution_id": "exec-1",
            "approval_id": f"approval-{index}",
            "execution_action": "transfer",
            "resource_id": "account:4",
            "created_at": "2026-10-16T09:58:00+00:00",
        }
        for index in range(5)
    ]

    class Commerce:
        async def list_approval_decisions_for_executions(
            self, tenant_id: str, execution_ids: list[str], limit: int
        ) -> list[object]:
            assert tenant_id == TENANT
            assert execution_ids == ["exec-1"]
            return []

        async def list_approvals_for_execution(
            self, tenant_id: str, execution_id: str, limit: int
        ) -> list[object]:
            assert tenant_id == TENANT
            assert execution_id == "exec-1"
            assert limit == 5
            return [SimpleNamespace(model_dump=lambda row=row, **_: row) for row in approvals]

    read = await RepositoryExecution360Source(commerce_store=Commerce()).execution_approval_decisions(
        tenant_id=TENANT,
        execution_ids=("exec-1",),
        limit=1,
    )

    assert read.available is True
    assert read.scope_known is True
    assert read.truncated is True
    assert len(read.approval_requests) == 4
    assert read.reason == "execution_approval_decision_read_truncated"


async def test_execution_approval_scope_or_lifecycle_reference_conflict_is_degraded() -> None:
    server = _server_row()
    server.update(
        {
            "approval_id": "approval-1",
            "approval_decision_id": "decision-1",
        }
    )
    source = FakeSource(
        server=ExecutionRead(
            rows=[server],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        approval_decisions=ExecutionApprovalRead(
            rows=[
                {
                    "tenant_id": "other-tenant",
                    "execution_id": "exec-1",
                    "approval_id": "approval-1",
                    "decision_id": "decision-1",
                    "action": "approve",
                    "decided_by": "human-1",
                    "decided_at": "2026-10-16T09:59:00+00:00",
                    "is_override": False,
                }
            ],
            available=True,
            scope_known=True,
        ),
    )

    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["approvalChainLinkage"]
    assert linkage["state"] == "degraded"
    assert linkage["joinedExecutionApprovals"] == []
    assert linkage["scopeKnown"] is False


async def test_canonical_tool_call_edge_joins_exact_execution_and_remains_partial() -> None:
    from types import SimpleNamespace

    class Graph:
        async def get_edges_for_tenant(self, tenant_id, *, limit, edge_types):
            assert tenant_id == TENANT
            assert limit == 10_000
            assert edge_types == ["CALLED_TOOL"]
            return (
                [
                    SimpleNamespace(
                        edge_type="CALLED_TOOL",
                        from_vertex_id=f"{TENANT}:agent:runtime-agent-1",
                        to_vertex_id=f"{TENANT}:tool:payments.send",
                        properties={
                            "tenant_id": TENANT,
                            "execution_id": "exec-1",
                            "called_at": "2026-10-16T10:00:01+00:00",
                            "idempotency_key": "lifecycle-edge-idempotency-1",
                        },
                    )
                ],
                False,
            )

        async def get_vertex_for_tenant(self, tenant_id, vertex_id):
            assert tenant_id == TENANT
            assert vertex_id == f"{TENANT}:tool:payments.send"
            return SimpleNamespace(
                vertex_type="Tool",
                vertex_id=vertex_id,
                properties={"tenant_id": TENANT, "tool_id": "payments.send"},
            )

    source_read = await RepositoryExecution360Source(graph_client=Graph())._read_execution_tool_calls(
        TENANT,
        [
            {
                "tenant_id": TENANT,
                "agent_id": "runtime-agent-1",
                "execution_id": "exec-1",
                "event_type": None,
                "canonical_agent_identity": True,
                "canonical_agent_entity_id": AGENT,
            }
        ],
    )
    assert source_read.available is True
    assert source_read.scope_known is True
    assert source_read.truncated is False
    assert source_read.rows[0]["executionId"] == "exec-1"
    assert source_read.rows[0]["toolId"] == "payments.send"
    assert source_read.rows[0]["externalExecutionReceipt"] == "unknown"

    server_row = {
        **_server_row(agent_id="runtime-agent-1"),
        "canonical_agent_identity": True,
        "canonical_agent_entity_id": AGENT,
    }
    request = _request()
    result = await Execution360Provider(
        FakeSource(
            server=ExecutionRead(
                rows=[server_row],
                available=True,
                scope_known=True,
                agent_ids=(AGENT,),
                tool_calls=source_read,
            ),
            observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        )
    ).project(request, await _context(request))
    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["toolInvocationLinkage"]
    assert linkage["state"] == "partial"
    assert linkage["completeness"] == "unknown"
    assert linkage["joinedExecutionToolCalls"][0]["executionId"] == "exec-1"
    assert linkage["joinedExecutionToolCalls"][0]["toolId"] == "payments.send"
    assert linkage["joinedExecutionToolCalls"][0]["authorityDecision"] == (
        "not_established_by_tool_call_edge"
    )
    claim = next(
        claim
        for claim in result.claims
        if claim.kind == "server_recorded_execution_tool_call_observation"
    )
    assert claim.domainSlotIds == ["tool_calls", "evidence_trace"]
    assert claim.evidenceRefs[0].id == "lifecycle-edge-idempotency-1"
    assert not [claim for claim in result.claims if "approval_chain" in claim.domainSlotIds]
    assert not [claim for claim in result.claims if "risk_events" in claim.domainSlotIds]


async def test_ambiguous_execution_actor_binding_does_not_join_tool_edges() -> None:
    read = await RepositoryExecution360Source()._read_execution_tool_calls(
        TENANT,
        [
            {
                "tenant_id": TENANT,
                "agent_id": "runtime-agent-1",
                "execution_id": "exec-ambiguous",
                "event_type": None,
                "canonical_agent_identity": True,
                "canonical_agent_entity_id": AGENT,
            },
            {
                "tenant_id": TENANT,
                "agent_id": "runtime-agent-2",
                "execution_id": "exec-ambiguous",
                "event_type": None,
                "canonical_agent_identity": True,
                "canonical_agent_entity_id": "agent-entity-2",
            },
        ],
    )

    assert read.available is True
    assert read.scope_known is False
    assert read.rows == []
    assert read.reason == "execution_identity_ambiguous_for_tool_join"


async def test_untrusted_tool_and_risk_ids_do_not_complete_execution_slots() -> None:
    reported = {
        **_observed_row(),
        "executionId": "spoofed-execution-join",
        "execution_id": "spoofed-execution-join",
        "riskEventId": "spoofed-risk-join",
        "riskLevel": "high",
    }
    source = FakeSource(
        server=ExecutionRead([_server_row()], available=True, scope_known=True, agent_ids=(AGENT,)),
        observed=ExecutionRead([reported], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    assert not any(
        "tool_calls" in claim.domainSlotIds or "risk_events" in claim.domainSlotIds
        for claim in result.claims
    )
    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.content["toolInvocationLinkage"]["state"] == "unknown"
    assert interactions.content["toolInvocationLinkage"]["joinedExecutionToolCalls"] == []
    assert interactions.content["riskEventLinkage"]["state"] == "empty"
    assert interactions.content["riskEventLinkage"]["joinedExecutionRiskEvents"] == []
    serialized = str(result.model_dump(mode="json"))
    assert "spoofed-execution-join" not in serialized
    assert "spoofed-risk-join" not in serialized

    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="execution360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="agent", id=AGENT),
            requestedSlotIds=["tool_calls", "risk_events"],
            includeEvidence=True,
        ),
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
    )
    assert {slot.id for slot in frame.slots} == {"tool_calls", "risk_events"}
    assert all(
        slot.state != "available"
        and slot.content is None
        and slot.claims == []
        and slot.evidenceRefs == []
        for slot in frame.slots
    )


async def test_executor_callback_outcome_has_run_evidence_without_business_effect_claim() -> None:
    server_row = {
        **_server_row(),
        "outcome_event_id": "run-outcome-event-1",
        "outcome_event_published": True,
    }
    source = FakeSource(
        server=ExecutionRead(
            rows=[server_row],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        )
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    outcomes = next(section for section in result.sections if section.id == "outcomes")
    assert outcomes.state == "unknown"
    assert outcomes.content["executionOutcomeAuthority"] == {
        "source": "agent_executions",
        "readState": "available",
        "recordMeaning": "server_recorded_run_lifecycle_callback",
        "eventPayloadRead": False,
    }
    callback = outcomes.content["executorCallbacks"][0]
    assert callback["executionId"] == "exec-1"
    assert callback["recordedStatus"] == "completed"
    assert callback["recordedAt"] == "2026-10-16T10:00:02+00:00"
    assert callback["outcomeEventId"] == "run-outcome-event-1"
    assert callback["outcomeEventReferenceKind"] == "event_id_recorded_on_agent_execution"
    assert callback["eventPublicationState"] == "published"
    assert callback["outcomeKind"] == "server_recorded_executor_run_terminal_status"
    assert callback["businessEffect"] == "not_established"
    assert callback["evidenceRefs"] == [
        {
            "id": "exec-1",
            "type": "event",
            "source": "agent_executions",
            "observedAt": "2026-10-16T10:00:02+00:00",
            "uri": "store://agent_executions/exec-1",
        }
    ]
    assert outcomes.content["businessOutcome"] == {
        "state": "unknown",
        "reason": "business_outcome_requires_independent_outcome_or_economic_authority",
    }
    assert outcomes.content["businessOutcomeAuthorityRead"] is False


@pytest.mark.parametrize(
    ("published", "expected_state"),
    [(False, "not_published"), (None, "unknown")],
)
async def test_executor_callback_event_publication_state_fails_closed(
    published: bool | None, expected_state: str
) -> None:
    server_row = {
        **_server_row(),
        "outcome_event_id": "run-outcome-event-1",
        "outcome_event_published": published,
    }
    source = FakeSource(
        server=ExecutionRead(
            rows=[server_row],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        )
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))
    outcomes = next(section for section in result.sections if section.id == "outcomes")

    callback = outcomes.content["executorCallbacks"][0]
    assert callback["eventPublicationState"] == expected_state
    assert callback["businessEffect"] == "not_established"


async def test_run_outcome_event_id_does_not_stand_in_for_action_delivery_receipt() -> None:
    # Deliberately reuse a telemetry event identifier as the lifecycle event
    # reference. Equal opaque IDs across stores do not create a receipt join.
    server_row = {
        **_server_row(),
        "outcome_event_id": "silver-event-1",
        "outcome_event_published": True,
    }
    request = _request()
    result = await Execution360Provider(
        FakeSource(
            server=ExecutionRead(
                rows=[server_row],
                available=True,
                scope_known=True,
                agent_ids=(AGENT,),
            ),
            observed=ExecutionRead(
                rows=[_observed_row()],
                available=True,
                scope_known=True,
                agent_ids=(AGENT,),
            ),
        )
    ).project(request, await _context(request))

    outcomes = next(section for section in result.sections if section.id == "outcomes")
    assert outcomes.content["externalExecutionReceipt"] == {
        "state": "unknown",
        "reason": "no_server_authoritative_external_execution_receipt_is_joined_by_this_provider",
    }
    callback = outcomes.content["executorCallbacks"][0]
    assert callback["outcomeEventId"] == "silver-event-1"
    assert callback["outcomeEventReferenceKind"] == "event_id_recorded_on_agent_execution"
    assert callback["businessEffect"] == "not_established"

    interactions = next(section for section in result.sections if section.id == "interactions")
    source_fact = next(
        item
        for item in interactions.content["interactions"]
        if item["source"] == "silver_agent_execution_facts"
    )
    assert source_fact["sourceEventId"] == callback["outcomeEventId"]
    assert source_fact["executionOccurrence"] == "source_reported"
    assert source_fact["executionVerified"] is False


async def test_source_agent_subject_uses_canonical_identity_for_execution_facts() -> None:
    source_agent_id = "runtime-agent-7"
    canonical_agent_id = "canonical-agent-7"
    request = _request(subject=ProjectionSubject(kind="agent", id=source_agent_id))
    source = FakeSource(
        server=ExecutionRead(
            rows=[
                {
                    **_server_row(agent_id=source_agent_id),
                    "canonical_agent_entity_id": canonical_agent_id,
                }
            ],
            available=True,
            scope_known=True,
            agent_ids=(canonical_agent_id,),
        ),
        observed=ExecutionRead(
            rows=[_observed_row(actor_id=canonical_agent_id)],
            available=True,
            scope_known=True,
            agent_ids=(canonical_agent_id,),
        ),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    assert state.content["serverRecordedExecutions"][0]["agentId"] == canonical_agent_id
    assert state.content["sourceReportedRuns"][0]["sourceEventId"] == "silver-event-1"
    interactions = next(section for section in result.sections if section.id == "interactions")
    observed_interaction = next(
        row
        for row in interactions.content["interactions"]
        if row["source"] == "silver_agent_execution_facts"
    )
    assert observed_interaction["actorAgentId"] == canonical_agent_id
    assert "execution_subject_binding_incomplete" not in result.degradedReasons


async def test_shared_agent_identity_resolution_requires_explicit_canonical_binding() -> None:
    source_agent_id = "runtime-agent-8"
    canonical_agent_id = "canonical-agent-8"

    class Deployments:
        async def list_page(self, tenant_id, *, limit, cursor=None):
            assert tenant_id == TENANT
            return (
                [
                    {
                        "tenant_id": TENANT,
                        "id": "deployment-8",
                        "agent_id": source_agent_id,
                        "agent_source_namespace": "provider-eight",
                    }
                ],
                None,
                False,
            )

    class Bindings:
        async def find_for_source(self, tenant_id, source_namespace, source_agent_ref):
            assert (tenant_id, source_namespace, source_agent_ref) == (
                TENANT,
                "provider-eight",
                source_agent_id,
            )
            return [
                {
                    "id": "binding-8",
                    "tenant_id": TENANT,
                    "source_namespace": source_namespace,
                    "source_agent_ref": source_agent_ref,
                    "canonical_agent_entity_id": canonical_agent_id,
                    "binding_authority": "tenant_admin_explicit",
                    "status": "active",
                }
            ]

    class Entities:
        async def find_by_id(self, entity_id):
            if entity_id == canonical_agent_id:
                return {
                    "tenant_id": TENANT,
                    "entity_type": "agent",
                    "entity_id": canonical_agent_id,
                }
            return None

    result = await resolve_agent_identities(
        TENANT,
        {source_agent_id},
        deployments=Deployments(),
        identity_bindings=Bindings(),
        entities=Entities(),
        limit=20,
    )

    assert result.scope_mismatch is False
    assert result.truncated is False
    assert result.rows[0]["agent_id"] == source_agent_id
    assert result.rows[0]["canonical_agent_entity_id"] == canonical_agent_id


async def test_missing_source_agent_binding_does_not_create_a_canonical_identity() -> None:
    class Deployments:
        async def list_page(self, tenant_id, *, limit, cursor=None):
            return (
                [
                    {
                        "tenant_id": tenant_id,
                        "id": "deployment-unbound",
                        "agent_id": "unbound-agent",
                        "agent_source_namespace": "provider-unbound",
                    }
                ],
                None,
                False,
            )

    class Bindings:
        async def find_for_source(self, tenant_id, source_namespace, source_agent_ref):
            return []

    class Entities:
        async def find_by_id(self, entity_id):
            return None

    result = await resolve_agent_identities(
        TENANT,
        {"unbound-agent"},
        deployments=Deployments(),
        identity_bindings=Bindings(),
        entities=Entities(),
        limit=20,
    )

    assert result.rows == []
    assert result.scope_mismatch is False
    assert result.truncated is False


async def test_repository_execution_adapter_joins_source_ids_to_canonical_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import actions.agent.deployments as deployment_module
    import actions.agent_marketplace.authority as authority_module
    import actions.agent_marketplace.identity_binding as binding_module
    import dependencies.providers as providers_module
    import repositories.repos as repos_module

    source_agent_id = "runtime-agent-9"
    canonical_agent_id = "canonical-agent-9"
    observed_row = {
        "tenant_id": TENANT,
        "source_event_id": "silver-event-9",
        "delegation_id": "deleg-9",
        "occurred_at": "2026-10-16T10:00:01+00:00",
        "event_name": "agent_tool_call_observed",
        "run_id": "source-run-9",
        "action_type": "transfer",
        "resource_ref": "account:9",
        "tool_name": "payments.send",
        "status": "completed",
    }
    execution_row = _server_row(agent_id=source_agent_id)
    execution_row["execution_id"] = "exec-9"
    execution_row["delegation_id"] = "deleg-9"
    execution_row["policy_log"]["delegation_check"]["delegation_id"] = "deleg-9"

    class Deployments:
        async def list_page(self, tenant_id, *, limit, cursor=None):
            return (
                [
                    {
                        "tenant_id": tenant_id,
                        "id": "deployment-9",
                        "agent_id": source_agent_id,
                        "agent_source_namespace": "provider-nine",
                    }
                ],
                None,
                False,
            )

    class Bindings:
        async def find_for_source(self, tenant_id, source_namespace, source_agent_ref):
            return [
                {
                    "id": "binding-9",
                    "tenant_id": tenant_id,
                    "source_namespace": source_namespace,
                    "source_agent_ref": source_agent_ref,
                    "canonical_agent_entity_id": canonical_agent_id,
                    "binding_authority": "tenant_admin_explicit",
                    "status": "active",
                }
            ]

    class Entities:
        async def find_by_id(self, entity_id):
            if entity_id == canonical_agent_id:
                return {
                    "tenant_id": TENANT,
                    "entity_type": "agent",
                    "entity_id": canonical_agent_id,
                }
            return None

    class AgentConfigs:
        async def find_by_id(self, agent_id):
            return {
                "tenant_id": TENANT,
                "agent_id": source_agent_id,
                "owner_entity_id": "owner-9",
            }

        async def list_for_owner(self, owner_entity_id):
            return []

        async def find_many(self, *, filters, limit):
            return []

    class AgentExecutions:
        async def find_by_id(self, execution_id):
            assert execution_id == "exec-9"
            return execution_row

        async def list_for_agent(self, agent_id, tenant_id, *, limit):
            assert agent_id == source_agent_id
            return [execution_row]

    class Delegations:
        async def find_by_id(self, delegation_id):
            return {
                "tenant_id": TENANT,
                "delegation_id": delegation_id,
                "grantor_entity_id": "owner-9",
                "grantee_entity_id": canonical_agent_id,
                "scope": {"actions": ["transfer"], "resources": ["account:9"]},
                "created_at": "2026-10-16T08:00:00+00:00",
            }

    class Analytics:
        def __init__(self, cache):
            pass

        async def query_silver(self, table, filters, *, limit):
            assert table == "silver_agent_execution_facts"
            assert filters == {"tenant_id": TENANT}
            return [observed_row]

    class AuthorityResolver:
        async def resolve(self, row):
            return {
                "delegation_resolution": {
                    "actor_identity_status": "matched",
                    "party_identity_status": "matched",
                    "status": "matched_reference",
                    "grantor_entity_id": canonical_agent_id,
                    "grantee_entity_id": "canonical-delegatee-9",
                    "state_at_event": "active",
                },
                "delegation_record": {
                    "tenant_id": TENANT,
                    "delegation_id": "deleg-9",
                    "grantor_entity_id": canonical_agent_id,
                    "grantee_entity_id": "canonical-delegatee-9",
                    "scope": {"actions": ["transfer"], "resources": ["account:9"]},
                    "starts_at": "2026-10-16T09:00:00+00:00",
                    "created_at": "2026-10-16T08:00:00+00:00",
                },
                "delegation_authorization": {
                    "actor_entity_id": canonical_agent_id,
                    "target_entity_id": "canonical-delegatee-9",
                    "binding_authority": "tenant_admin_explicit",
                    "status": "within_scope",
                },
            }

    monkeypatch.setattr(deployment_module, "get_deployment_repository", lambda: Deployments())
    monkeypatch.setattr(binding_module, "AgentDeploymentIdentityBindingRepository", Bindings)
    monkeypatch.setattr(repos_module, "EntityRepository", Entities)
    monkeypatch.setattr(repos_module, "AgentConfigRepository", AgentConfigs)
    monkeypatch.setattr(repos_module, "AgentExecutionRepository", AgentExecutions)
    monkeypatch.setattr(repos_module, "DelegationRepository", Delegations)
    monkeypatch.setattr(repos_module, "AnalyticsRepository", Analytics)
    monkeypatch.setattr(authority_module, "AgentRunAuthorityResolver", AuthorityResolver)
    monkeypatch.setattr(providers_module, "get_cache", lambda: object())

    source = RepositoryExecution360Source()
    subject = ProjectionSubject(kind="agent", id=source_agent_id)
    server = await source.server_executions(tenant_id=TENANT, subject=subject, limit=10)
    observed = await source.observed_facts(tenant_id=TENANT, subject=subject, limit=10)

    assert server.available is True
    assert server.scope_known is True
    assert server.agent_ids == (canonical_agent_id,)
    assert server.rows[0]["canonical_agent_identity"] is True
    assert server.rows[0]["canonical_agent_entity_id"] == canonical_agent_id
    assert server.rows[0]["canonical_delegation_id"] == "deleg-9"
    assert (
        server.rows[0]["canonical_delegation_resolution_status"]
        == "matched_current_grant_reference_and_grantee"
    )
    assert observed.available is True
    assert observed.scope_known is True
    assert observed.agent_ids == (canonical_agent_id,)
    assert observed.rows[0]["actorAgentId"] == canonical_agent_id

    exact_execution = await source.server_executions(
        tenant_id=TENANT,
        subject=ProjectionSubject(kind="execution", id="exec-9"),
        limit=10,
    )
    assert exact_execution.available is True
    assert exact_execution.scope_known is True
    assert [row["execution_id"] for row in exact_execution.rows] == ["exec-9"]
    assert exact_execution.rows[0]["canonical_agent_entity_id"] == canonical_agent_id

    execution_row["tenant_id"] = "tenant-other"
    foreign_execution = await source.server_executions(
        tenant_id=TENANT,
        subject=ProjectionSubject(kind="execution", id="exec-9"),
        limit=10,
    )
    assert foreign_execution.rows == []
    assert foreign_execution.scope_known is False
    assert foreign_execution.reason == "execution_subject_scope_unresolved"


async def test_repository_execution_adapter_reads_exact_workflow_run_execution_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import actions.agent.execution360_provider as provider_module
    import repositories.repos as repos_module

    source_agent_id = "runtime-agent-workflow"
    canonical_agent_id = "canonical-agent-workflow"
    workflow_run_id = "workflow-run-exact"
    execution_row = _server_row(agent_id=source_agent_id)
    execution_row.update(
        execution_id="execution-workflow-exact",
        workflow_run_id=workflow_run_id,
        workflow_run_invocation_ids=["invocation-workflow-exact"],
        delegation_id=None,
    )
    invocation_fact = {
        "tenant_id": TENANT,
        "workflow_run_id": workflow_run_id,
        "invocation_id": "invocation-workflow-exact",
        "action_id": "execution-workflow-exact",
        "agent_id": source_agent_id,
        "observed_at": "2026-10-16T10:00:00+00:00",
    }

    class AgentConfigs:
        async def find_by_id(self, agent_id):
            assert agent_id == source_agent_id
            return {
                "tenant_id": TENANT,
                "agent_id": source_agent_id,
                "owner_entity_id": "owner-workflow",
            }

    class AgentExecutions:
        async def find_many(self, *, filters, limit):
            assert filters == {
                "tenant_id": TENANT,
                "workflow_run_id": workflow_run_id,
            }
            assert limit == 11
            return [execution_row]

    class Delegations:
        async def find_by_id(self, delegation_id):
            raise AssertionError("row has no delegation reference")

    class Graph:
        async def get_edges_for_tenant(self, tenant_id, *, limit, edge_types):
            assert tenant_id == TENANT
            return [], False

    async def resolve_identity_map(tenant_id, source_agent_ids):
        assert tenant_id == TENANT
        if not source_agent_ids:
            return {}, False, False
        assert source_agent_ids == {source_agent_id}
        return (
            {
                source_agent_id: {
                    "agent_id": source_agent_id,
                    "canonical_agent_entity_id": canonical_agent_id,
                }
            },
            False,
            False,
        )

    async def read_invocation_facts(tenant_id, requested_run_id, limit):
        assert tenant_id == TENANT
        assert requested_run_id == workflow_run_id
        assert limit == 200
        return ExecutionWorkflowRunInvocationRead(
            rows=[invocation_fact], available=True, scope_known=True
        )

    monkeypatch.setattr(repos_module, "AgentConfigRepository", AgentConfigs)
    monkeypatch.setattr(repos_module, "AgentExecutionRepository", AgentExecutions)
    monkeypatch.setattr(repos_module, "DelegationRepository", Delegations)
    monkeypatch.setattr(provider_module, "_resolve_agent_identity_map", resolve_identity_map)
    monkeypatch.setattr(
        provider_module,
        "_read_workflow_run_invocation_facts",
        read_invocation_facts,
    )

    source = RepositoryExecution360Source(graph_client=Graph())
    read = await source.server_executions(
        tenant_id=TENANT,
        subject=ProjectionSubject(kind="workflow_run", id=workflow_run_id),
        limit=10,
    )

    assert read.available is True
    assert read.scope_known is True
    assert read.agent_ids == (canonical_agent_id,)
    assert [row["execution_id"] for row in read.rows] == ["execution-workflow-exact"]
    assert read.rows[0]["workflow_run_id"] == workflow_run_id
    assert read.rows[0]["canonical_agent_entity_id"] == canonical_agent_id
    assert read.rows[0]["workflow_run_invocation_evidence_refs"][0]["id"] == (
        "invocation-workflow-exact"
    )

    invocation_fact["action_id"] = "execution-from-another-action"
    mismatched_link = await source.server_executions(
        tenant_id=TENANT,
        subject=ProjectionSubject(kind="workflow_run", id=workflow_run_id),
        limit=10,
    )
    assert mismatched_link.rows == []
    assert mismatched_link.scope_known is False
    assert mismatched_link.reason == "workflow_run_execution_scope_mismatch"


async def test_server_delegation_reference_joins_policy_log_to_tenant_grantee() -> None:
    row = _server_row()
    grant = {
        "tenant_id": TENANT,
        "delegation_id": "deleg-1",
        "grantor_entity_id": "owner-1",
        "grantee_entity_id": AGENT,
        "scope": {"actions": ["transfer"], "resources": ["account:4"]},
        "created_at": "2026-10-16T08:00:00+00:00",
        "revoked_at": "2026-10-17T00:00:00+00:00",
    }

    class Grants:
        async def find_by_id(self, delegation_id):
            assert delegation_id == "deleg-1"
            return grant

    resolution = await _resolve_server_delegation_reference(
        row, tenant_id=TENANT, repository=Grants()
    )

    assert resolution == {
        "canonical_delegation_matched": True,
        "canonical_delegation_id": "deleg-1",
        "canonical_delegation_resolution_status": "matched_current_grant_reference_and_grantee",
        "canonical_delegation_evidence_observed_at": "2026-10-16T08:00:00+00:00",
    }


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("foreign_execution", "execution_scope_mismatch"),
        ("missing_recorded_reference", "not_recorded"),
        ("missing_policy_decision", "policy_decision_missing"),
        ("missing_policy_reference", "policy_reference_missing"),
        ("conflicting_policy_reference", "conflicted_policy_reference"),
        ("unresolved_agent", "canonical_agent_unresolved"),
        ("missing_grant", "grant_not_found"),
        ("foreign_grant", "grant_scope_mismatch"),
        ("incomplete_grant", "grant_record_incomplete"),
        ("wrong_grantee", "grant_party_mismatch"),
    ],
)
async def test_server_delegation_reference_rejects_unverified_joins(
    case: str, expected: str
) -> None:
    row = _server_row()
    grant = {
        "tenant_id": TENANT,
        "delegation_id": "deleg-1",
        "grantor_entity_id": "owner-1",
        "grantee_entity_id": AGENT,
        "scope": {"actions": ["transfer"], "resources": ["account:4"]},
    }
    if case == "foreign_execution":
        row["tenant_id"] = "foreign-tenant"
    elif case == "missing_recorded_reference":
        row["delegation_id"] = None
    elif case == "missing_policy_decision":
        row["policy_log"]["delegation_check"].pop("allowed")
    elif case == "missing_policy_reference":
        row["policy_log"]["delegation_check"].pop("delegation_id")
    elif case == "conflicting_policy_reference":
        row["policy_log"]["delegation_check"]["delegation_id"] = "other-grant"
    elif case == "unresolved_agent":
        row["canonical_agent_identity"] = False
    elif case == "missing_grant":
        grant = None
    elif case == "foreign_grant":
        grant["tenant_id"] = "foreign-tenant"
    elif case == "incomplete_grant":
        grant.pop("scope")
    elif case == "wrong_grantee":
        grant["grantee_entity_id"] = "another-agent"

    class Grants:
        async def find_by_id(self, delegation_id):
            assert delegation_id == "deleg-1"
            return grant

    resolution = await _resolve_server_delegation_reference(
        row, tenant_id=TENANT, repository=Grants()
    )

    assert resolution == {"canonical_delegation_resolution_status": expected}


async def test_execution_provider_rejects_unverified_server_delegation_metadata() -> None:
    row = _server_row()
    row["policy_log"]["delegation_check"]["delegation_id"] = "other-grant"
    source = FakeSource(
        server=ExecutionRead([row], available=True, scope_known=True, agent_ids=(AGENT,)),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    recorded = state.content["serverRecordedExecutions"][0]
    assert recorded["delegationId"] is None
    assert recorded["delegationResolutionStatus"] == "unverified_join_metadata"
    assert not any(
        claim.kind == "canonically_joined_server_delegation_reference"
        for claim in result.claims
    )
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert not any(ref["source"] == "delegations" for ref in evidence.content["evidence"])


async def test_authenticated_execution_principal_is_carried_into_frame_metadata() -> None:
    row = {**_server_row(), "initiating_principal_user_id": "human-principal-1"}
    source = FakeSource(
        server=ExecutionRead(rows=[row], available=True, scope_known=True, agent_ids=(AGENT,)),
        observed=ExecutionRead(rows=[], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    projection_request = _request()
    result = await Execution360Provider(source).project(
        projection_request,
        await _context(projection_request),
    )

    claim = next(
        claim for claim in result.claims if claim.kind == "authenticated_execution_principal"
    )
    assert claim.claimState == EpistemicStatus.OBSERVED
    assert claim.evidenceRefs[0].source == "agent_executions"
    state = next(section for section in result.sections if section.id == "state")
    assert state.content["serverRecordedExecutions"][0]["initiatingPrincipalUserId"] == (
        "human-principal-1"
    )

    frame_request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )
    metadata = _derive_agent_actor_metadata(frame_request, [result])
    actor = metadata["actor_attribution"]
    assert actor.executionPrincipal is not None
    assert actor.executionPrincipal.kind == "human"
    assert actor.executionPrincipal.id == "human-principal-1"
    assert any(ref.source == "agent_executions" for ref in actor.evidenceRefs)


async def test_execution_principal_resolves_only_through_active_tenant_human_identity() -> None:
    from identity.identity.hashing import hash_value

    principal_id = "human-principal-1"
    canonical_human_id = "human-entity-1"
    expected_hash = hash_value(principal_id, scope=f"user:{TENANT}")

    class IdentityRepository:
        async def find_aliases_by_signal(self, tenant_id, alias_type, alias_value_hash, *, limit):
            assert tenant_id == TENANT
            assert alias_value_hash == expected_hash
            assert limit == 51
            return [
                {
                    "id": "user-alias-1",
                    "tenant_id": TENANT,
                    "alias_type": "user_id",
                    "alias_value_hash": expected_hash,
                    "canonical_entity_id": "pre-merge-human-1",
                    "confidence_tier": "deterministic",
                    "last_seen_at": "2026-10-16T09:00:00+00:00",
                }
            ]

        async def resolve_surviving_canonical_entity_id(
            self, tenant_id, canonical_entity_id
        ):
            assert tenant_id == TENANT
            assert canonical_entity_id == "pre-merge-human-1"
            return canonical_human_id

        async def get_subject_by_canonical_entity_id(self, tenant_id, canonical_entity_id):
            assert tenant_id == TENANT
            assert canonical_entity_id == canonical_human_id
            return {
                "id": "human-subject-1",
                "tenant_id": TENANT,
                "canonical_entity_id": canonical_human_id,
                "entity_type": "human",
                "status": "active",
                "last_seen_at": "2026-10-16T09:01:00+00:00",
            }

    read = await _read_execution_principal_identities(
        TENANT,
        {principal_id},
        repository=IdentityRepository(),
    )
    assert read.available is True
    assert read.scope_known is True
    assert read.truncated is False
    assert read.rows[0]["canonical_human_entity_id"] == canonical_human_id
    assert {ref["source"] for ref in read.rows[0]["identity_evidence_refs"]} == {
        "identity_aliases",
        "identity_subjects",
    }

    server = ExecutionRead(
        rows=[{**_server_row(), "initiating_principal_user_id": principal_id}],
        available=True,
        scope_known=True,
        agent_ids=(AGENT,),
        principal_identity_read=read,
    )
    source = FakeSource(
        server=server,
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    claim = next(
        claim
        for claim in result.claims
        if claim.kind == "canonically_resolved_execution_principal_identity"
    )
    assert claim.claimState == EpistemicStatus.RESOLVED
    assert claim.domainSlotIds == ["actor_attribution", "evidence_trace"]
    assert {ref.source for ref in claim.evidenceRefs} == {
        "agent_executions",
        "identity_aliases",
        "identity_subjects",
    }
    state = next(section for section in result.sections if section.id == "state")
    record = state.content["serverRecordedExecutions"][0]
    assert record["canonicalInitiatingPrincipalHumanEntityId"] == canonical_human_id
    assert record["initiatingPrincipalIdentityState"] == "resolved"


@pytest.mark.parametrize("case", ["foreign_alias", "wrong_alias_hash", "inactive_subject", "non_human_subject"])
async def test_principal_identity_reader_rejects_scope_and_subject_mismatches(case: str) -> None:
    from identity.identity.hashing import hash_value

    principal_id = "human-principal-1"
    alias_hash = hash_value(principal_id, scope=f"user:{TENANT}")

    class IdentityRepository:
        async def find_aliases_by_signal(self, tenant_id, alias_type, alias_value_hash, *, limit):
            alias_tenant = "foreign-tenant" if case == "foreign_alias" else TENANT
            stored_hash = "different-hash" if case == "wrong_alias_hash" else alias_hash
            return [
                {
                    "id": "user-alias-1",
                    "tenant_id": alias_tenant,
                    "alias_type": "user_id",
                    "alias_value_hash": stored_hash,
                    "canonical_entity_id": "human-entity-1",
                    "confidence_tier": "deterministic",
                }
            ]

        async def resolve_surviving_canonical_entity_id(self, tenant_id, canonical_entity_id):
            return canonical_entity_id

        async def get_subject_by_canonical_entity_id(self, tenant_id, canonical_entity_id):
            return {
                "id": "human-subject-1",
                "tenant_id": TENANT,
                "canonical_entity_id": canonical_entity_id,
                "entity_type": "agent" if case == "non_human_subject" else "human",
                "status": "inactive" if case == "inactive_subject" else "active",
            }

    read = await _read_execution_principal_identities(
        TENANT,
        {principal_id},
        repository=IdentityRepository(),
    )

    assert read.available is True
    assert read.scope_known is False
    assert read.rows == []
    assert read.reason == "principal_identity_scope_or_subject_mismatch"


@pytest.mark.parametrize(
    ("identity_read", "expected_state", "expected_reason"),
    [
        (
            ExecutionPrincipalIdentityRead(rows=[], available=True, scope_known=True),
            "unresolved",
            None,
        ),
        (
            ExecutionPrincipalIdentityRead(
                rows=[
                    {
                        "tenant_id": "foreign-tenant",
                        "principal_user_id": "human-principal-1",
                        "canonical_human_entity_id": "foreign-human",
                        "identity_evidence_refs": [
                            EvidenceRef(
                                id="foreign-alias",
                                type="entity",
                                source="identity_aliases",
                            ).model_dump(mode="json"),
                            EvidenceRef(
                                id="foreign-subject",
                                type="entity",
                                source="identity_subjects",
                            ).model_dump(mode="json"),
                        ],
                    }
                ],
                available=True,
                scope_known=True,
            ),
            "unknown",
            "principal_identity_scope_or_evidence_mismatch",
        ),
        (
            ExecutionPrincipalIdentityRead(
                rows=[], available=False, scope_known=False, reason="identity_store_unavailable"
            ),
            "unknown",
            "identity_store_unavailable",
        ),
    ],
)
async def test_execution_principal_identity_absence_mismatch_or_outage_fails_closed(
    identity_read: ExecutionPrincipalIdentityRead,
    expected_state: str,
    expected_reason: str | None,
) -> None:
    principal_id = "human-principal-1"
    server = ExecutionRead(
        rows=[{**_server_row(), "initiating_principal_user_id": principal_id}],
        available=True,
        scope_known=True,
        agent_ids=(AGENT,),
        principal_identity_read=identity_read,
    )
    request = _request()
    result = await Execution360Provider(
        FakeSource(
            server=server,
            observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        )
    ).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    record = state.content["serverRecordedExecutions"][0]
    assert record["initiatingPrincipalIdentityState"] == expected_state
    assert record["canonicalInitiatingPrincipalHumanEntityId"] is None
    assert not any(
        claim.kind == "canonically_resolved_execution_principal_identity"
        for claim in result.claims
    )
    if expected_reason:
        assert expected_reason in result.degradedReasons


async def test_execution_principal_identity_ambiguity_does_not_select_a_human() -> None:
    def _identity_row(alias_id: str, canonical_human_id: str) -> dict:
        return {
            "tenant_id": TENANT,
            "principal_user_id": "human-principal-1",
            "canonical_human_entity_id": canonical_human_id,
            "identity_evidence_refs": [
                EvidenceRef(
                    id=alias_id,
                    type="entity",
                    source="identity_aliases",
                ).model_dump(mode="json"),
                EvidenceRef(
                    id=f"subject-{canonical_human_id}",
                    type="entity",
                    source="identity_subjects",
                ).model_dump(mode="json"),
            ],
        }

    server = ExecutionRead(
        rows=[{**_server_row(), "initiating_principal_user_id": "human-principal-1"}],
        available=True,
        scope_known=True,
        agent_ids=(AGENT,),
        principal_identity_read=ExecutionPrincipalIdentityRead(
            rows=[
                _identity_row("alias-human-1", "human-entity-1"),
                _identity_row("alias-human-2", "human-entity-2"),
            ],
            available=True,
            scope_known=True,
        ),
    )
    request = _request()
    result = await Execution360Provider(
        FakeSource(
            server=server,
            observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        )
    ).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    record = state.content["serverRecordedExecutions"][0]
    assert record["initiatingPrincipalIdentityState"] == "ambiguous"
    assert record["canonicalInitiatingPrincipalHumanEntityId"] is None
    assert "principal_identity_ambiguous" in result.degradedReasons
    assert not any(
        claim.kind == "canonically_resolved_execution_principal_identity"
        for claim in result.claims
    )


async def test_principal_stays_unknown_when_any_complete_execution_lacks_attribution() -> None:
    rows = [
        {**_server_row(), "initiating_principal_user_id": "human-principal-1"},
        {**_server_row(), "execution_id": "exec-2"},
    ]
    source = FakeSource(
        server=ExecutionRead(
            rows=rows,
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead(rows=[], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    projection_request = _request()
    result = await Execution360Provider(source).project(
        projection_request,
        await _context(projection_request),
    )
    frame_request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    metadata = _derive_agent_actor_metadata(frame_request, [result])

    assert metadata["actor_attribution"].executionPrincipal is None


async def test_truncated_server_execution_read_does_not_resolve_principal_or_decision() -> None:
    row = {
        **_server_row(),
        "initiating_principal_user_id": "human-principal-1",
    }
    source = FakeSource(
        server=ExecutionRead(
            rows=[row],
            available=True,
            scope_known=True,
            truncated=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead(rows=[], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    projection_request = _request()
    result = await Execution360Provider(source).project(
        projection_request,
        await _context(projection_request),
    )
    frame_request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    metadata = _derive_agent_actor_metadata(frame_request, [result])
    actor = metadata["actor_attribution"]

    assert actor.executionPrincipal is None
    assert actor.resolvedCanonicalActor is None
    assert actor.authorityDecision is not None
    assert actor.authorityDecision.outcome == "unknown"
    assert actor.authorityDecision.reasonCodes == ["no_action_scoped_decision_available"]


async def test_truncated_source_telemetry_does_not_resolve_actor_or_delegation_chain() -> None:
    source = FakeSource(
        server=ExecutionRead(rows=[], available=True, scope_known=True, agent_ids=(AGENT,)),
        observed=ExecutionRead(
            rows=[_observed_row()],
            available=True,
            scope_known=True,
            truncated=True,
            agent_ids=(AGENT,),
        ),
    )
    projection_request = _request()
    result = await Execution360Provider(source).project(
        projection_request,
        await _context(projection_request),
    )
    frame_request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    metadata = _derive_agent_actor_metadata(frame_request, [result])
    actor = metadata["actor_attribution"]

    assert actor.resolutionState == "unknown"
    assert actor.resolvedCanonicalActor is None
    assert actor.delegator is None
    assert actor.delegatee is None
    assert actor.delegationChain == []


async def test_frame_does_not_collapse_multiple_execution_principals() -> None:
    rows = [
        {
            **_server_row(),
            "execution_id": f"exec-{index}",
            "initiating_principal_user_id": principal,
        }
        for index, principal in enumerate(("human-principal-1", "human-principal-2"), start=1)
    ]
    source = FakeSource(
        server=ExecutionRead(rows=rows, available=True, scope_known=True, agent_ids=(AGENT,)),
        observed=ExecutionRead(rows=[], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    projection_request = _request()
    result = await Execution360Provider(source).project(
        projection_request,
        await _context(projection_request),
    )
    frame_request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    metadata = _derive_agent_actor_metadata(frame_request, [result])

    assert metadata["actor_attribution"].executionPrincipal is None


async def test_provider_drops_cross_tenant_rows_and_unresolved_authority() -> None:
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row(tenant_id="tenant-other")],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead(
            rows=[
                _observed_row(tenant_id="tenant-other"),
                {**_observed_row(), "delegationResolutionStatus": "unresolved"},
            ],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    assert result.claims == []
    assert (
        next(section for section in result.sections if section.id == "summary").content[
            "serverRecordedExecutionCount"
        ]
        == 0
    )
    assert (
        next(section for section in result.sections if section.id == "summary").content[
            "sourceReportedFactCount"
        ]
        == 0
    )
    assert "server_execution_scope_mismatch" in result.degradedReasons
    assert "observed_execution_scope_mismatch" in result.degradedReasons
    frame_request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
        requestedSlotIds=["inputs_outputs", "failures", "plan_steps"],
        includeEvidence=True,
    )
    frame = compose_experience360_frame(
        frame_request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
    )
    assert all(
        slot.state != "available"
        and slot.content is None
        and slot.evidenceRefs == []
        and slot.claims == []
        for slot in frame.slots
    )


async def test_execution_subject_joins_canonical_risk_signal_with_evidence() -> None:
    request = _request(subject=ProjectionSubject(kind="execution", id="exec-1"))
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        risk_events=ExecutionRiskEventRead(
            rows=[_execution_risk_signal_row()],
            available=True,
            scope_known=True,
        ),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    assert source.risk_event_calls == [(TENANT, ("exec-1",), 50)]
    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["riskEventLinkage"]
    assert linkage["state"] == "partial"
    assert linkage["completeness"] == "bounded_recorded_execution_subject_signals_and_assessments"
    assert linkage["producerCoverage"] == {
        "state": "unknown",
        "reason": "execution_risk_signal_producer_inventory_not_connected",
    }
    assert linkage["riskAssessmentCoverage"] == {
        "state": "not_read",
        "sourceReadState": "not_read",
        "authority": "risk_assessments",
        "reason": None,
        "scopeKnown": False,
        "completeness": "exact_execution_subject_snapshots_only_history_and_producer_coverage_unknown",
        "assessmentCount": None,
        "joinedExecutionRiskAssessments": [],
        "evidenceRefs": [],
        "truncated": False,
    }
    assert linkage["joinedExecutionRiskEvents"] == [
        {
            "executionId": "exec-1",
            "signalId": "risk-exec-1",
            "riskDimension": "agentic",
            "source": "aether.fraud.detector.agentic",
            "detectorVersion": "agentic-risk-v2",
            "claimState": "inferred",
            "confidence": 0.82,
            "score": 0.64,
            "value": None,
            "observedAt": "2026-10-16T10:00:01+00:00",
            "evidenceRefs": [
                {
                    "id": "evidence-risk-exec-1",
                    "type": "model_output",
                    "source": "aether.fraud.detector.agentic",
                    "observedAt": "2026-10-16T10:00:01+00:00",
                }
            ],
        }
    ]
    assert linkage["freshness"] == {
        "state": "unknown",
        "latestObservedAt": "2026-10-16T10:00:01+00:00",
        "reason": "no_execution_risk_freshness_threshold_is_configured",
    }
    assert linkage["evidenceRefs"][0]["id"] == "evidence-risk-exec-1"
    assert any(
        ref["id"] == "evidence-risk-exec-1"
        for ref in result.sections[0].content["evidence"]
    )
    claim = next(
        claim
        for claim in result.claims
        if claim.kind == "execution_subject_risk_signal_context"
    )
    assert claim.subject == request.subject
    assert claim.claimState == EpistemicStatus.INFERRED
    assert claim.domainSlotIds == ["risk_events", "evidence_trace"]
    assert claim.evidenceRefs[0].id == "evidence-risk-exec-1"


async def test_execution_risk_assessment_snapshot_join_has_record_evidence() -> None:
    request = _request(subject=ProjectionSubject(kind="execution", id="exec-1"))
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        risk_events=ExecutionRiskEventRead(
            rows=[],
            available=True,
            scope_known=True,
            assessment_read=ExecutionRiskAssessmentRead(
                rows=[_execution_risk_assessment_row()],
                available=True,
                scope_known=True,
            ),
        ),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["riskEventLinkage"]
    assessment_coverage = linkage["riskAssessmentCoverage"]
    assert linkage["state"] == "partial"
    assert assessment_coverage["state"] == "partial"
    assert assessment_coverage["sourceReadState"] == "available"
    assert assessment_coverage["scopeKnown"] is True
    assert assessment_coverage["assessmentCount"] == 1
    assessment = assessment_coverage["joinedExecutionRiskAssessments"][0]
    assert assessment["executionId"] == "exec-1"
    assert assessment["assessmentId"] == "assessment-exec-1"
    assert assessment["policyId"] == "risk-policy-v2"
    assert assessment["claimState"] == "inferred"
    assert assessment["components"] == [
        {
            "dimension": "agentic",
            "state": "observed",
            "score": 0.61,
            "claimState": "inferred",
            "confidence": 0.84,
            "evidenceRefs": [
                {
                    "id": "evidence-assessment-exec-1",
                    "type": "model_output",
                    "source": "aether.risk.assessment.agentic",
                    "observedAt": "2026-10-16T10:00:02+00:00",
                }
            ],
        }
    ]
    assert assessment["evidenceRefs"][0] == {
        "id": "assessment-exec-1",
        "type": "model_output",
        "source": "risk_assessments",
        "observedAt": "2026-10-16T10:00:02+00:00",
        "uri": "store://risk_assessments/tenant-execution360%3Aassessment-exec-1",
    }
    claim = next(
        claim
        for claim in result.claims
        if claim.kind == "execution_subject_risk_assessment_snapshot"
    )
    assert claim.subject == request.subject
    assert claim.claimState == EpistemicStatus.INFERRED
    assert claim.domainSlotIds == ["risk_events", "evidence_trace"]
    assert {ref.source for ref in claim.evidenceRefs} == {
        "risk_assessments",
        "aether.risk.assessment.agentic",
    }
    evidence_section = next(section for section in result.sections if section.id == "evidence")
    assert any(
        ref["source"] == "risk_assessments" and ref["id"] == "assessment-exec-1"
        for ref in evidence_section.content["evidence"]
    )


async def test_execution_risk_assessment_is_retained_when_signal_read_fails() -> None:
    request = _request(subject=ProjectionSubject(kind="execution", id="exec-1"))
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        risk_events=ExecutionRiskEventRead(
            rows=[],
            available=False,
            scope_known=False,
            reason="execution_risk_signal_source_unavailable",
            assessment_read=ExecutionRiskAssessmentRead(
                rows=[_execution_risk_assessment_row()],
                available=True,
                scope_known=True,
            ),
        ),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["riskEventLinkage"]
    assert linkage["state"] == "degraded"
    assert linkage["sourceReadState"] == "unavailable"
    assessment_coverage = linkage["riskAssessmentCoverage"]
    assert assessment_coverage["state"] == "partial"
    assert assessment_coverage["assessmentCount"] == 1
    assert assessment_coverage["joinedExecutionRiskAssessments"][0]["assessmentId"] == (
        "assessment-exec-1"
    )


async def test_agent_subject_joins_risk_signals_only_to_admitted_execution_ids() -> None:
    request = _request()
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row(), {**_server_row(), "execution_id": "exec-2"}],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        risk_events=ExecutionRiskEventRead(
            rows=[
                _execution_risk_signal_row(),
                _execution_risk_signal_row(signal_id="risk-exec-2", subject_id="exec-2"),
            ],
            available=True,
            scope_known=True,
        ),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    assert source.risk_event_calls == [(TENANT, ("exec-1", "exec-2"), 50)]
    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["riskEventLinkage"]
    assert linkage["state"] == "partial"
    assert [row["executionId"] for row in linkage["joinedExecutionRiskEvents"]] == [
        "exec-1",
        "exec-2",
    ]
    risk_claims = [
        claim
        for claim in result.claims
        if claim.kind == "execution_subject_risk_signal_context"
    ]
    assert all(claim.subject == request.subject for claim in risk_claims)
    assert all(
        "exec-1" in claim.claims[0] or "exec-2" in claim.claims[0]
        for claim in risk_claims
    )


async def test_execution_risk_event_reader_drops_wrong_tenant_or_subject_and_degrades() -> None:
    request = _request(subject=ProjectionSubject(kind="execution", id="exec-1"))
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        risk_events=ExecutionRiskEventRead(
            rows=[
                _execution_risk_signal_row(),
                _execution_risk_signal_row(signal_id="wrong-subject", subject_id="exec-other"),
                _execution_risk_signal_row(signal_id="wrong-tenant", tenant_id="tenant-other"),
            ],
            available=True,
            scope_known=True,
        ),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["riskEventLinkage"]
    assert linkage["state"] == "degraded"
    assert linkage["joinedExecutionRiskEvents"][0]["signalId"] == "risk-exec-1"
    serialized = result.model_dump_json()
    assert "wrong-subject" not in serialized
    assert "wrong-tenant" not in serialized
    assert not any(
        "risk_events" in claim.domainSlotIds
        for claim in result.claims
        if claim.kind != "execution_subject_risk_signal_context"
    )


async def test_execution_risk_signal_requires_evidence_and_aware_time_for_window() -> None:
    request = _request(
        subject=ProjectionSubject(kind="execution", id="exec-1"),
        timeRange=TimeRangeFilter(
            from_="2026-10-16T10:00:00+00:00",
            to="2026-10-16T10:00:03+00:00",
        ),
    )
    no_evidence = _execution_risk_signal_row(signal_id="no-evidence")
    no_evidence["evidence_refs"] = []
    naive_time = _execution_risk_signal_row(signal_id="naive-time", observed_at="2026-10-16T10:00:01")
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        risk_events=ExecutionRiskEventRead(
            rows=[no_evidence, naive_time],
            available=True,
            scope_known=True,
        ),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["riskEventLinkage"]
    assert linkage["state"] == "degraded"
    assert linkage["joinedExecutionRiskEvents"] == []
    assert linkage["evidenceRefs"] == []
    serialized = result.model_dump_json()
    assert "no-evidence" not in serialized
    assert "naive-time" not in serialized


async def test_as_of_execution_projection_does_not_read_current_risk_signals() -> None:
    request = _request(
        subject=ProjectionSubject(kind="execution", id="exec-1"),
        asOf="2026-10-16T10:00:00+00:00",
    )
    source = FakeSource()

    result = await Execution360Provider(source).project(request, await _context(request))

    assert source.risk_event_calls == []
    interactions = next(section for section in result.sections if section.id == "interactions")
    linkage = interactions.content["riskEventLinkage"]
    assert linkage["state"] == "unknown"
    assert linkage["sourceReadState"] == "not_read"
    assert linkage["joinedExecutionRiskEvents"] == []
    assert linkage["reason"] == "temporal_anchor_not_reconstructable_from_current_sources"


async def test_repository_risk_reader_uses_canonical_exact_tenant_execution_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intelligence.risk360 import store as risk_store

    calls: list[tuple[str, str, str, int]] = []

    class RiskSignalRepo:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            calls.append((tenant_id, subject_kind, subject_id, limit))
            return [
                _execution_risk_signal_row(),
                _execution_risk_signal_row(signal_id="other-subject", subject_id="exec-2"),
            ]

    class RiskAssessmentRepo:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            return []

    monkeypatch.setattr(risk_store, "RiskSignalRepository", RiskSignalRepo)
    monkeypatch.setattr(risk_store, "RiskAssessmentRepository", RiskAssessmentRepo)
    result = await RepositoryExecution360Source().execution_risk_events(
        tenant_id=TENANT,
        execution_ids=("exec-1",),
        limit=10,
    )

    assert calls == [(TENANT, "execution", "exec-1", 11)]
    assert result.available is True
    assert result.scope_known is False
    assert [row["signal_id"] for row in result.rows] == ["risk-exec-1"]
    assert result.reason == "execution_risk_signal_scope_mismatch"


async def test_repository_risk_reader_uses_exact_tenant_execution_subjects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intelligence.risk360 import store as risk_store

    calls: list[tuple[str, str, str, int]] = []

    class RiskSignalRepo:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            calls.append((tenant_id, subject_kind, subject_id, limit))
            signal = (
                _execution_risk_signal_row()
                if subject_id == "exec-1"
                else _execution_risk_signal_row(signal_id="risk-exec-2", subject_id="exec-2")
            )
            return [
                {
                    **signal,
                    "id": f"{tenant_id}:{signal['signal_id']}",
                    "created_at": "2026-10-16T10:00:00+00:00",
                    "updated_at": "2026-10-16T10:00:00+00:00",
                }
            ]

    class RiskAssessmentRepo:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            return []

    monkeypatch.setattr(risk_store, "RiskSignalRepository", RiskSignalRepo)
    monkeypatch.setattr(risk_store, "RiskAssessmentRepository", RiskAssessmentRepo)
    result = await RepositoryExecution360Source().execution_risk_events(
        tenant_id=TENANT,
        execution_ids=("exec-1", "exec-2"),
        limit=10,
    )

    assert calls == [
        (TENANT, "execution", "exec-1", 11),
        (TENANT, "execution", "exec-2", 11),
    ]
    assert result.available is True
    assert result.scope_known is True
    assert [row["signal_id"] for row in result.rows] == ["risk-exec-1", "risk-exec-2"]
    assert all("id" not in row and "created_at" not in row for row in result.rows)
    assert result.truncated is False
    assert result.reason is None


async def test_repository_risk_assessment_reader_uses_exact_tenant_execution_subjects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intelligence.risk360 import store as risk_store

    calls: list[tuple[str, str, str, int]] = []

    class RiskSignalRepo:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            return []

    class RiskAssessmentRepo:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            calls.append((tenant_id, subject_kind, subject_id, limit))
            return [
                _execution_risk_assessment_row(),
                _execution_risk_assessment_row(
                    assessment_id="wrong-subject",
                    subject_id="exec-other",
                ),
                _execution_risk_assessment_row(
                    assessment_id="wrong-tenant",
                    tenant_id="tenant-other",
                ),
            ]

    monkeypatch.setattr(risk_store, "RiskSignalRepository", RiskSignalRepo)
    monkeypatch.setattr(risk_store, "RiskAssessmentRepository", RiskAssessmentRepo)
    result = await RepositoryExecution360Source().execution_risk_events(
        tenant_id=TENANT,
        execution_ids=("exec-1",),
        limit=10,
    )

    assert calls == [(TENANT, "execution", "exec-1", 11)]
    assert result.available is True
    assert result.assessment_read is not None
    assert result.assessment_read.available is True
    assert result.assessment_read.scope_known is False
    assert [row["assessment_id"] for row in result.assessment_read.rows] == ["assessment-exec-1"]
    assert result.assessment_read.reason == "execution_risk_assessment_scope_mismatch"


async def test_repository_risk_assessment_read_survives_signal_source_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intelligence.risk360 import store as risk_store

    class RiskSignalRepo:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            raise RuntimeError("signal table unavailable")

    class RiskAssessmentRepo:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            return [_execution_risk_assessment_row()]

    monkeypatch.setattr(risk_store, "RiskSignalRepository", RiskSignalRepo)
    monkeypatch.setattr(risk_store, "RiskAssessmentRepository", RiskAssessmentRepo)
    result = await RepositoryExecution360Source().execution_risk_events(
        tenant_id=TENANT,
        execution_ids=("exec-1",),
        limit=10,
    )

    assert result.available is False
    assert result.reason == "execution_risk_signal_source_unavailable"
    assert result.rows == []
    assert result.assessment_read is not None
    assert result.assessment_read.available is True
    assert result.assessment_read.scope_known is True
    assert [row["assessment_id"] for row in result.assessment_read.rows] == [
        "assessment-exec-1"
    ]


async def test_repository_risk_reader_bounds_execution_subject_fanout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intelligence.risk360 import store as risk_store

    calls: list[tuple[str, str, str, int]] = []
    assessment_calls: list[tuple[str, str, str, int]] = []

    class RiskSignalRepo:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            calls.append((tenant_id, subject_kind, subject_id, limit))
            return []

    class RiskAssessmentRepo:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            assessment_calls.append((tenant_id, subject_kind, subject_id, limit))
            return []

    monkeypatch.setattr(risk_store, "RiskSignalRepository", RiskSignalRepo)
    monkeypatch.setattr(risk_store, "RiskAssessmentRepository", RiskAssessmentRepo)
    execution_ids = tuple(f"exec-{index}" for index in range(501))

    result = await RepositoryExecution360Source().execution_risk_events(
        tenant_id=TENANT,
        execution_ids=execution_ids,
        limit=50,
    )

    assert len(calls) == 500
    assert [subject_id for _, _, subject_id, _ in calls] == sorted(execution_ids)[:500]
    assert all(limit == 2 for _, _, _, limit in calls)
    assert all(tenant_id == TENANT and kind == "execution" for tenant_id, kind, _, _ in calls)
    assert result.available is True
    assert result.scope_known is True
    assert result.truncated is True
    assert result.reason == "execution_risk_signal_read_truncated"
    assert result.rows == []
    assert len(assessment_calls) == 500
    assert [subject_id for _, _, subject_id, _ in assessment_calls] == sorted(execution_ids)[:500]
    assert all(limit == 2 for _, _, _, limit in assessment_calls)
    assert result.assessment_read is not None
    assert result.assessment_read.truncated is True


async def test_unavailable_sources_degrade_without_leaking_diagnostics() -> None:
    request = _request()
    result = await Execution360Provider(
        FakeSource(error=RuntimeError("sensitive tenant storage detail"))
    ).project(request, await _context(request))

    assert "sensitive tenant storage detail" not in result.model_dump_json()
    assert result.degradedReasons == [
        "observed_execution_source_unavailable",
        "server_execution_source_unavailable",
    ]
    assert all(
        section.state == "degraded" for section in result.sections if section.id != "outcomes"
    )
    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.content["toolInvocationLinkage"]["state"] == "unknown"
    assert interactions.content["toolInvocationLinkage"]["sourceReportedToolRelatedFactCount"] is None
    assert interactions.content["riskEventLinkage"]["state"] == "unknown"


async def test_latency_cost_keeps_invalid_lifecycle_durations_degraded_and_cost_unknown() -> None:
    invalid_rows = [
        {**_server_row(), "execution_id": "exec-no-end", "ended_at": None},
        {
            **_server_row(),
            "execution_id": "exec-invalid-timezone",
            "started_at": "2026-10-16T10:00:00",
        },
        {
            **_server_row(),
            "execution_id": "exec-negative-duration",
            "ended_at": "2026-10-16T09:59:59+00:00",
        },
    ]
    source = FakeSource(
        server=ExecutionRead(
            rows=invalid_rows,
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )

    result = await Execution360Provider(source).project(_request(), await _context(_request()))

    summary = next(section for section in result.sections if section.id == "summary")
    latency_cost = summary.content["latencyCost"]
    assert latency_cost["latency"]["state"] == "degraded"
    assert latency_cost["latency"]["samples"] == []
    assert (
        latency_cost["latency"]["reason"]
        == "some_server_lifecycle_records_lack_valid_start_or_end_timestamps"
    )
    assert latency_cost["cost"]["state"] == "unknown"
    assert not any(
        claim.kind == "server_recorded_lifecycle_elapsed_time" for claim in result.claims
    )


async def test_latency_cost_is_unknown_without_lifecycle_rows() -> None:
    request = _request()
    source = FakeSource(
        server=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    summary = next(section for section in result.sections if section.id == "summary")
    latency_cost = summary.content["latencyCost"]
    assert latency_cost["latency"]["state"] == "unknown"
    assert latency_cost["latency"]["sampleCount"] is None
    assert latency_cost["latency"]["samples"] == []
    assert latency_cost["cost"]["state"] == "unknown"
    assert (
        next(section for section in result.sections if section.id == "outcomes").state == "unknown"
    )


async def test_historical_anchor_is_not_claimed_when_lifecycle_is_mutable() -> None:
    request = _request(asOf="2026-10-16T10:00:00+00:00")
    result = await Execution360Provider(FakeSource()).project(request, await _context(request))

    assert result.asOf is None
    assert "temporal_anchor_not_reconstructable_from_current_sources" in result.degradedReasons
    assert next(section for section in result.sections if section.id == "state").state == "degraded"


async def test_window_mode_is_supported_and_applies_explicit_event_time_bounds() -> None:
    request = _request(
        temporalMode="window",
        timeRange=TimeRangeFilter(
            from_="2026-10-16T10:00:01+00:00",
            to="2026-10-16T10:00:01+00:00",
        ),
    )
    result = await Execution360Provider(FakeSource()).project(request, await _context(request))

    assert result.degradedReasons == []
    state = next(section for section in result.sections if section.id == "state")
    assert state.state == "available"
    assert state.content["serverRecordedExecutions"] == []
    assert len(state.content["sourceReportedRuns"]) == 1


async def test_frame_actor_metadata_uses_execution_evidence_and_keeps_decision_scoped() -> None:
    row = _server_row()
    row["created_at"] = "2026-10-16T10:00:00.500000+00:00"
    row["policy_log"]["delegation_check"]["evaluated_at"] = (
        "2026-10-16T10:00:00.250000+00:00"
    )
    projection_request = _request()
    result = await Execution360Provider(
        FakeSource(
            server=ExecutionRead(
                rows=[row],
                available=True,
                scope_known=True,
                agent_ids=(AGENT,),
            )
        )
    ).project(
        projection_request,
        await _context(projection_request),
    )
    frame_request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    metadata = _derive_agent_actor_metadata(frame_request, [result])

    actor = metadata["actor_attribution"]
    assert actor.resolutionState == "resolved"
    assert actor.resolvedCanonicalActor is not None
    assert actor.resolvedCanonicalActor.id == AGENT
    assert actor.evidenceRefs
    authority = metadata["authority_envelope"].authorityDecision
    assert authority is not None
    assert authority.outcome == "allow"
    assert authority.delegationRefs == ["deleg-1"]
    assert authority.decidedAt == "2026-10-16T10:00:00.250000+00:00"
    assert authority.reasonCodes == ["recorded_execution_scoped_decision_not_standing_authority"]
    assert authority.evidenceRefs
    assert metadata["actor_attribution"].delegator is not None
    assert metadata["actor_attribution"].delegator.id == AGENT
    assert metadata["actor_attribution"].delegatee is not None
    assert metadata["actor_attribution"].delegatee.id == "agent-delegatee-1"
    assert len(metadata["actor_attribution"].delegationChain) == 1
    delegation = metadata["actor_attribution"].delegationChain[0]
    assert delegation.id == "deleg-1"
    assert delegation.scope == ["action:transfer", "resource:account:4"]
    assert {ref.source for ref in delegation.evidenceRefs} == {
        "delegations",
        "silver_agent_execution_facts",
    }


async def test_recorded_denial_without_matching_grant_reaches_agent_frame() -> None:
    denied = {
        **_server_row(),
        "delegation_id": None,
        "canonical_delegation_id": None,
        "canonical_delegation_matched": False,
        "status": "revoked",
        "policy_log": {
            "delegation_check": {
                "allowed": False,
                "delegation_id": None,
                "reason": "no_active_delegation",
                "matched_scope": None,
            }
        },
    }
    projection_request = _request()
    result = await Execution360Provider(
        FakeSource(
            server=ExecutionRead(
                rows=[denied],
                available=True,
                scope_known=True,
                agent_ids=(AGENT,),
            )
        )
    ).project(projection_request, await _context(projection_request))

    state = next(section for section in result.sections if section.id == "state")
    recorded = state.content["serverRecordedExecutions"][0]
    assert recorded["recordedDelegationDecision"] is False
    assert recorded["delegationDecisionReason"] == "no_active_delegation"
    decision_claim = next(
        claim for claim in result.claims if claim.kind == "server_recorded_delegation_decision"
    )
    assert decision_claim.claimState == EpistemicStatus.OBSERVED
    assert "denied" in decision_claim.claims[0]
    assert "transfer" in decision_claim.claims[0]
    assert "account:4" in decision_claim.claims[0]

    frame_request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )
    metadata = _derive_agent_actor_metadata(frame_request, [result])
    authority = metadata["authority_envelope"].authorityDecision
    assert authority is not None
    assert authority.outcome == "deny"
    assert authority.authorityRef == "aether.agent_delegation_engine"
    assert authority.delegationRefs == []
    assert authority.actionRefs == ["transfer"]
    assert authority.resourceRefs == ["account:4"]
    assert authority.executionRefs == ["exec-1"]
    assert authority.evidenceRefs[0].id == "exec-1"
    assert authority.reasonCodes == ["recorded_delegation_denial_without_matching_grant"]


async def test_execution_authority_check_exposes_exact_recorded_decision_with_unknown_freshness() -> None:
    row = {
        **_server_row(),
        "created_at": "2026-10-16T10:00:00.500000+00:00",
    }
    source = FakeSource(
        server=ExecutionRead(
            rows=[row],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    authority = state.content["authorityCheck"]
    assert authority["state"] == "partial"
    assert authority["scopeKnown"] is True
    assert authority["coverage"] == "recorded_delegation_engine_decisions_only"
    assert len(authority["joinedActionScopedDecisions"]) == 1
    decision = authority["joinedActionScopedDecisions"][0]
    assert decision["tenantId"] == TENANT
    assert decision["executionId"] == "exec-1"
    assert decision["action"] == "transfer"
    assert decision["resource"] == "account:4"
    assert decision["decision"] == "allow"
    assert decision["delegationId"] == "deleg-1"
    assert decision["authority"] == "agent_executions.policy_log.delegation_check"
    assert decision["lifecycleTimestamps"]["recordCreatedAt"] == (
        "2026-10-16T10:00:00.500000+00:00"
    )
    assert decision["decisionTime"] == {
        "state": "unknown",
        "reason": "delegation_decision_timestamp_not_persisted",
    }
    assert decision["evidenceRef"]["source"] == "agent_executions"
    assert decision["evidenceRef"]["id"] == "exec-1"
    assert authority["effectiveAuthorization"]["state"] == "unknown"
    assert authority["freshness"]["state"] == "unknown"
    assert authority["temporalScope"]["decisionTimestamp"] == "not_persisted"

    claim = next(
        claim for claim in result.claims if claim.kind == "server_recorded_delegation_decision"
    )
    assert claim.domainSlotIds is not None
    assert {"authority_check", "authority_envelope"} <= set(claim.domainSlotIds)
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert any(
        ref["id"] == "exec-1" and ref["source"] == "agent_executions"
        for ref in evidence.content["evidence"]
    )


async def test_execution_authority_check_exposes_persisted_evaluation_timestamp() -> None:
    row = {
        **_server_row(),
        "created_at": "2026-10-16T10:00:03+00:00",
        "policy_log": {
            "delegation_check": {
                "allowed": True,
                "delegation_id": "deleg-1",
                "evaluated_at": "2026-10-16T09:59:59.750000Z",
            }
        },
    }
    source = FakeSource(
        server=ExecutionRead(
            rows=[row],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    authority = state.content["authorityCheck"]
    decision = authority["joinedActionScopedDecisions"][0]
    assert decision["decisionTime"] == {
        "state": "recorded",
        "evaluatedAt": "2026-10-16T09:59:59.750000+00:00",
        "source": "agent_executions.policy_log.delegation_check.evaluated_at",
    }
    assert authority["temporalScope"]["decisionTimestamp"] == "persisted"
    assert authority["freshness"]["state"] == "unknown"
    assert authority["effectiveAuthorization"]["state"] == "unknown"


async def test_execution_authority_check_rejects_decision_timestamp_after_record_creation() -> None:
    row = {
        **_server_row(),
        "created_at": "2026-10-16T10:00:03+00:00",
        "policy_log": {
            "delegation_check": {
                "allowed": True,
                "delegation_id": "deleg-1",
                "evaluated_at": "2026-10-16T10:00:04+00:00",
            }
        },
    }
    source = FakeSource(
        server=ExecutionRead(
            rows=[row],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    authority = state.content["authorityCheck"]
    decision = authority["joinedActionScopedDecisions"][0]
    assert authority["state"] == "degraded"
    assert decision["decisionTime"] == {
        "state": "unknown",
        "reason": "delegation_decision_timestamp_after_execution_record",
    }
    assert authority["temporalScope"]["decisionTimestamp"] == "not_persisted"


async def test_execution_authority_check_rejects_ambiguous_or_malformed_decision_rows() -> None:
    duplicate = {**_server_row(), "execution_id": "exec-1"}
    duplicate_source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row(), duplicate],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    request = _request()
    duplicate_result = await Execution360Provider(duplicate_source).project(
        request, await _context(request)
    )
    duplicate_state = next(
        section for section in duplicate_result.sections if section.id == "state"
    )
    duplicate_authority = duplicate_state.content["authorityCheck"]
    assert duplicate_authority["state"] == "degraded"
    assert duplicate_authority["ambiguousExecutionIds"] == ["exec-1"]
    assert duplicate_authority["joinedActionScopedDecisions"] == []

    malformed_rows = []
    malformed_decision = _server_row()
    malformed_decision["policy_log"]["delegation_check"]["allowed"] = "true"
    malformed_rows.append(malformed_decision)
    malformed_policy_log = _server_row()
    malformed_policy_log["policy_log"] = "must-not-be-treated-as-an-empty-decision"
    malformed_rows.append(malformed_policy_log)

    for malformed in malformed_rows:
        malformed_source = FakeSource(
            server=ExecutionRead(
                rows=[malformed],
                available=True,
                scope_known=True,
                agent_ids=(AGENT,),
            ),
            observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
        )
        malformed_result = await Execution360Provider(malformed_source).project(
            request, await _context(request)
        )
        malformed_state = next(
            section for section in malformed_result.sections if section.id == "state"
        )
        malformed_authority = malformed_state.content["authorityCheck"]
        assert malformed_authority["state"] == "degraded"
        assert malformed_authority["joinedActionScopedDecisions"] == []
        assert malformed_authority["reason"] == (
            "execution_authority_record_scope_or_evidence_ambiguous"
        )


async def test_execution_authority_window_uses_lifecycle_time_only() -> None:
    request = _request(
        timeRange=TimeRangeFilter(
            from_="2026-10-16T10:00:01+00:00",
            to="2026-10-16T10:00:03+00:00",
        )
    )
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
        ),
        observed=ExecutionRead([], available=True, scope_known=True, agent_ids=(AGENT,)),
    )
    result = await Execution360Provider(source).project(request, await _context(request))

    state = next(section for section in result.sections if section.id == "state")
    authority = state.content["authorityCheck"]
    assert authority["temporalScope"]["selection"] == "execution_lifecycle_time_window"
    assert authority["temporalScope"]["decisionTimestamp"] == "not_persisted"
    assert authority["joinedActionScopedDecisions"][0]["decisionTime"]["state"] == "unknown"


async def test_frame_keeps_same_outcome_decisions_separate_by_action_and_resource() -> None:
    rows = [
        {
            **_server_row(),
            "execution_id": "exec-transfer",
            "input_snapshot": {"action": "transfer", "resource": "account:4"},
        },
        {
            **_server_row(),
            "execution_id": "exec-refund",
            "input_snapshot": {"action": "refund", "resource": "invoice:9"},
        },
    ]
    projection_request = _request()
    result = await Execution360Provider(
        FakeSource(
            server=ExecutionRead(
                rows=rows,
                available=True,
                scope_known=True,
                agent_ids=(AGENT,),
            ),
            observed=ExecutionRead(
                rows=[],
                available=True,
                scope_known=True,
                agent_ids=(AGENT,),
            ),
        )
    ).project(projection_request, await _context(projection_request))
    frame_request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    metadata = _derive_agent_actor_metadata(frame_request, [result])
    authority = metadata["authority_envelope"].authorityDecision

    assert authority is not None
    assert authority.outcome == "unknown"
    assert authority.authorityRef is None
    assert authority.actionRefs == ["refund", "transfer"]
    assert authority.resourceRefs == ["account:4", "invoice:9"]
    assert authority.executionRefs == ["exec-refund", "exec-transfer"]
    assert authority.reasonCodes == ["multiple_action_scoped_decisions_not_collapsed"]


async def test_frame_does_not_emit_allow_when_recorded_action_scope_is_missing() -> None:
    row = {
        **_server_row(),
        "input_snapshot": {"resource": "account:4"},
    }
    projection_request = _request()
    result = await Execution360Provider(
        FakeSource(
            server=ExecutionRead(
                rows=[row],
                available=True,
                scope_known=True,
                agent_ids=(AGENT,),
            ),
            observed=ExecutionRead(
                rows=[],
                available=True,
                scope_known=True,
                agent_ids=(AGENT,),
            ),
        )
    ).project(projection_request, await _context(projection_request))
    frame_request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    metadata = _derive_agent_actor_metadata(frame_request, [result])
    authority = metadata["authority_envelope"].authorityDecision

    assert authority is not None
    assert authority.outcome == "unknown"
    assert authority.actionRefs == []
    assert authority.resourceRefs == []
    assert authority.executionRefs == []
    assert authority.reasonCodes == ["no_action_scoped_decision_available"]
    state = next(section for section in result.sections if section.id == "state")
    assert state.content["authorityCheck"]["state"] == "degraded"
    assert state.content["authorityCheck"]["joinedActionScopedDecisions"] == []


async def test_frame_delegation_chain_requires_aware_validity_and_nonempty_scope() -> None:
    projection_request = _request()
    row = {**_observed_row(), "delegationScope": None, "delegationValidFrom": "2026-10-16T09:00:00"}
    result = await Execution360Provider(
        FakeSource(
            observed=ExecutionRead(rows=[row], available=True, scope_known=True, agent_ids=(AGENT,))
        )
    ).project(projection_request, await _context(projection_request))
    frame_request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    metadata = _derive_agent_actor_metadata(frame_request, [result])

    actor = metadata["actor_attribution"]
    assert actor.delegator is not None and actor.delegator.id == AGENT
    assert actor.delegatee is not None and actor.delegatee.id == "agent-delegatee-1"
    assert actor.delegationChain == []


async def test_frame_does_not_collapse_multiple_delegations_into_one_chain() -> None:
    projection_request = _request()
    first = _observed_row()
    second = {
        **_observed_row(),
        "sourceEventId": "silver-event-2",
        "delegationId": "deleg-2",
        "delegationEvidenceId": "deleg-2",
        "delegateeAgentId": "agent-delegatee-2",
    }
    result = await Execution360Provider(
        FakeSource(
            observed=ExecutionRead(
                rows=[first, second], available=True, scope_known=True, agent_ids=(AGENT,)
            )
        )
    ).project(projection_request, await _context(projection_request))
    frame_request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    metadata = _derive_agent_actor_metadata(frame_request, [result])

    actor = metadata["actor_attribution"]
    assert actor.delegator is None
    assert actor.delegatee is None
    assert actor.delegationChain == []


async def test_frame_actor_metadata_accepts_agent360_identity_claim_but_keeps_authority_unknown() -> (
    None
):
    evidence = EvidenceRef(
        id="binding-agent-1",
        type="entity",
        source="agent_deployment_identity_bindings",
        observedAt="2026-10-16T10:00:00Z",
    )
    agent_result = ProjectionResult(
        projectionId="agent360",
        tenantId=TENANT,
        contractVersion="1.0.0",
        sections=[
            ProjectionSection(
                id="state",
                state="available",
                content={
                    "dimensions": [
                        {
                            "id": "actor_attribution",
                            "state": "matched",
                            "content": {"resolvedCanonicalActor": "canonical-agent-1"},
                        }
                    ]
                },
            )
        ],
        claims=[
            ClaimEnvelope(
                id="agent_identity_binding.binding-agent-1",
                kind="canonically_resolved_agent_identity",
                subject=ProjectionSubject(kind="agent", id=AGENT),
                evidenceRefs=[evidence],
                claims=["Explicit tenant binding resolves this agent identity."],
                claimState=EpistemicStatus.RESOLVED,
                domainSlotIds=["identity", "actor_attribution"],
            )
        ],
        dependencyState=[],
        generatedAt="2026-10-16T10:00:00Z",
        degradedReasons=[],
    )
    frame_request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    metadata = _derive_agent_actor_metadata(frame_request, [agent_result])

    actor = metadata["actor_attribution"]
    assert actor.resolutionState == "resolved"
    assert actor.resolvedCanonicalActor is not None
    assert actor.resolvedCanonicalActor.id == "canonical-agent-1"
    assert actor.evidenceRefs == [evidence]
    authority = metadata["authority_envelope"].authorityDecision
    assert authority is not None
    assert authority.outcome == "unknown"
    assert authority.reasonCodes == ["no_action_scoped_decision_available"]

    identity_only_request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
        requestedSlotIds=["identity"],
    )
    assert _derive_agent_actor_metadata(identity_only_request, [agent_result]) == {}

    actor_only_request = identity_only_request.model_copy(
        update={"requestedSlotIds": ["actor_attribution"]}
    )
    actor_only_metadata = _derive_agent_actor_metadata(actor_only_request, [agent_result])
    assert set(actor_only_metadata) == {"actor_attribution"}
    assert actor_only_metadata["actor_attribution"].resolvedCanonicalActor is not None


@pytest.mark.parametrize(
    (
        "identity_state",
        "canonical_human_id",
        "candidate_human_ids",
        "principal_state",
        "expected_canonical_human_id",
        "raw_principal_ids",
    ),
    [
        (
            "resolved",
            "canonical-human-1",
            ["canonical-human-1"],
            "available",
            "canonical-human-1",
            ["human-principal-1"],
        ),
        ("unresolved", None, [], "available", None, ["human-principal-1"]),
        (
            "ambiguous",
            None,
            ["canonical-human-1", "canonical-human-2"],
            "available",
            None,
            ["human-principal-1"],
        ),
        (
            "resolved",
            "canonical-human-1",
            ["canonical-human-1"],
            "partial",
            None,
            ["human-principal-1"],
        ),
        (
            "resolved",
            "canonical-human-1",
            ["canonical-human-1"],
            "ambiguous",
            "canonical-human-1",
            ["human-principal-1", "human-principal-2"],
        ),
    ],
)
async def test_agent_frame_propagates_only_complete_unambiguous_principal_identity(
    identity_state: str,
    canonical_human_id: str | None,
    candidate_human_ids: list[str],
    principal_state: str,
    expected_canonical_human_id: str | None,
    raw_principal_ids: list[str],
) -> None:
    agent_result = _agent360_principal_result(
        identity_state=identity_state,
        canonical_human_id=canonical_human_id,
        candidate_human_ids=candidate_human_ids,
        principal_state=principal_state,
        raw_principal_ids=raw_principal_ids,
    )
    execution_result = _execution_result_with_principals(raw_principal_ids)
    request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    actor = _derive_agent_actor_metadata(request, [agent_result, execution_result])["actor_attribution"]

    # The raw authenticated USER_ID claim remains distinct from its canonical Human link.
    if len(raw_principal_ids) == 1:
        assert actor.executionPrincipal is not None
        assert actor.executionPrincipal.kind == "human"
        assert actor.executionPrincipal.id == raw_principal_ids[0]
    else:
        assert actor.executionPrincipal is None
    if expected_canonical_human_id is None:
        assert actor.executionPrincipalCanonicalIdentity is None
    else:
        assert actor.executionPrincipalCanonicalIdentity is not None
        assert actor.executionPrincipalCanonicalIdentity.kind == "human"
        assert actor.executionPrincipalCanonicalIdentity.id == expected_canonical_human_id
        assert actor.executionPrincipalCanonicalIdentity.id not in raw_principal_ids
        assert {ref.source for ref in actor.evidenceRefs} >= {
            "agent_executions",
            "identity_aliases",
            "identity_subjects",
        }
    assert actor.authorityDecision is not None
    assert actor.authorityDecision.outcome == "unknown"


def test_agent_frame_rejects_principal_identity_when_execution_sources_disagree() -> None:
    agent_result = _agent360_principal_result(
        identity_state="resolved",
        canonical_human_id="canonical-human-1",
        candidate_human_ids=["canonical-human-1"],
        principal_state="ambiguous",
        raw_principal_ids=["human-principal-1", "human-principal-2"],
    )
    execution_result = _execution_result_with_principal("human-principal-1")
    request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    actor = _derive_agent_actor_metadata(request, [agent_result, execution_result])["actor_attribution"]

    assert actor.executionPrincipalCanonicalIdentity is None
    assert actor.executionPrincipal is not None
    assert actor.executionPrincipal.id == "human-principal-1"


def test_agent_frame_rejects_principal_identity_with_non_identity_provenance() -> None:
    agent_result = _agent360_principal_result(
        identity_state="resolved",
        canonical_human_id="canonical-human-1",
        candidate_human_ids=["canonical-human-1"],
    )
    actor_content = agent_result.sections[0].content["dimensions"][0]["content"]
    actor_content["executionPrincipalCanonicalIdentity"]["evidenceRefs"][0].update(
        {"type": "event", "source": "agent_executions"}
    )
    execution_result = _execution_result_with_principal("human-principal-1")
    request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
    )

    actor = _derive_agent_actor_metadata(request, [agent_result, execution_result])["actor_attribution"]

    assert actor.executionPrincipalCanonicalIdentity is None


@pytest.mark.parametrize(
    "evidence_sources",
    [
        ["agent_executions"],
        ["agent_executions", "identity_aliases"],
        ["identity_aliases", "identity_subjects"],
    ],
)
def test_typed_principal_identity_requires_execution_and_identity_evidence(
    evidence_sources: list[str],
) -> None:
    with pytest.raises(ValidationError, match="USER_ID alias and subject evidence"):
        Experience360ActorAttribution(
            tenantId=TENANT,
            executionPrincipalCanonicalIdentity=Experience360ActorParty(
                kind="human", id="canonical-human-1"
            ),
            evidenceRefs=[
                EvidenceRef(
                    id=f"evidence-{source}",
                    type="event" if source == "agent_executions" else "entity",
                    source=source,
                )
                for source in evidence_sources
            ],
        )


async def test_episode_scope_is_unknown_without_canonical_execution_binding() -> None:
    request = _request(subject=ProjectionSubject(kind="episode", id="episode-1"))
    source = FakeSource(
        server=ExecutionRead([], available=True, scope_known=False),
        observed=ExecutionRead([], available=True, scope_known=False),
    )
    result = await Execution360Provider(source).project(request, await _context(request))

    assert (
        next(section for section in result.sections if section.id == "summary").state == "unknown"
    )
    assert "execution_subject_binding_incomplete" in result.degradedReasons


async def test_episode_projection_keeps_only_rows_joined_by_the_same_canonical_event_ids() -> None:
    request = _request(subject=ProjectionSubject(kind="episode", id="episode-1"))
    server = _server_row()
    server["triggered_by_event_id"] = "episode-event-1"
    unrelated_server = _server_row()
    unrelated_server["execution_id"] = "exec-unrelated"
    unrelated_server["triggered_by_event_id"] = "not-linked-to-episode"
    observed = _observed_row()
    observed["sourceEventId"] = "episode-event-1"
    unrelated_observed = _observed_row()
    unrelated_observed["sourceEventId"] = "not-linked-to-episode"
    source = FakeSource(
        server=ExecutionRead(
            rows=[
                server,
                unrelated_server,
                _task_decomposition_row(),
                _task_decomposition_row(execution_id="exec-unrelated"),
            ],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
            subject_event_ids=("episode-event-1", "episode-event-2"),
        ),
        observed=ExecutionRead(
            rows=[observed, unrelated_observed],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
            subject_event_ids=("episode-event-1", "episode-event-2"),
        ),
    )

    result = await Execution360Provider(source).project(request, await _context(request))

    summary = next(section for section in result.sections if section.id == "summary")
    assert summary.content["serverRecordedExecutionCount"] == 1
    assert summary.content["sourceReportedFactCount"] == 1
    assert result.degradedReasons == []
    state = next(section for section in result.sections if section.id == "state")
    assert state.content["serverRecordedExecutions"][0]["executionId"] == "exec-1"
    assert state.content["sourceReportedRuns"][0]["sourceEventId"] == "episode-event-1"
    assert state.content["planSteps"]["observedCount"] == 1
    assert state.content["planSteps"]["records"][0]["executionId"] == "exec-1"


def test_registration_is_explicit() -> None:
    registry = ProviderRegistry()
    assert registry.get("execution360") is None
    register_provider(registry)
    assert registry.get("execution360") is not None


@pytest.mark.asyncio
async def test_agent_episode_context_uses_bounded_tenant_page_and_exact_agent_subject():
    episode = EpisodeRecord(
        episode_id="episode-agent-1",
        tenant_id=TENANT,
        subject=EntityRef(kind="agent", id=AGENT),
        kind="execution_run",
        status="closed",
        title="private title omitted",
        occurred_from="2026-10-16T10:00:00Z",
        occurred_to="2026-10-16T10:00:02Z",
        source_event_id="trigger-1",
        evidence_refs=[
            EvidenceRef(
                id="episode-evidence-1",
                type="event",
                source="episode_observations",
            )
        ],
    )
    other_agent_episode = episode.model_copy(
        update={
            "episode_id": "episode-other-agent",
            "subject": EntityRef(kind="agent", id="another-agent"),
        }
    )
    foreign_episode = episode.model_copy(
        update={"episode_id": "episode-foreign", "tenant_id": "tenant-other"}
    )

    class EpisodeStore:
        async def list_page_by_tenant(self, tenant_id, *, limit, cursor=None):
            assert tenant_id == TENANT
            assert limit == 201
            assert cursor is None
            return EpisodePageRead(
                records=(episode, other_agent_episode, foreign_episode),
                next_cursor=None,
                truncated=False,
            )

    context = await _read_agent_episode_context(
        TENANT,
        {AGENT},
        episode_store=EpisodeStore(),
        identity_rows=[
            {
                "tenant_id": TENANT,
                "agent_id": AGENT,
                "canonical_agent_entity_id": AGENT,
                "identity_evidence_id": AGENT,
                "identity_evidence_source": "entities",
                "identity_bound_at": "2026-10-16T09:00:00Z",
            }
        ],
        execution_rows=[
            {
                "tenant_id": TENANT,
                "canonical_agent_identity": True,
                "canonical_agent_entity_id": AGENT,
                "execution_id": "exec-linked",
                "triggered_by_event_id": "trigger-1",
            },
            {
                "tenant_id": TENANT,
                "canonical_agent_identity": True,
                "canonical_agent_entity_id": AGENT,
                "execution_id": "exec-unlinked",
                "triggered_by_event_id": "different-event",
            },
            {
                "tenant_id": TENANT,
                "canonical_agent_identity": True,
                "canonical_agent_entity_id": "another-agent",
                "execution_id": "exec-other-agent",
                "triggered_by_event_id": "trigger-1",
            },
        ],
    )

    assert context.state == "degraded"
    assert context.reason == "agent_episode_record_scope_conflict"
    assert [item["episodeId"] for item in context.items] == ["episode-agent-1"]
    assert context.items[0]["sourceEventIds"] == ["trigger-1"]
    assert context.items[0]["matchedExecutions"] == [
        {"executionId": "exec-linked", "triggeredByEventId": "trigger-1"}
    ]
    assert {ref.id for ref in context.evidence_refs} == {
        "episode-agent-1",
        "episode-evidence-1",
        "exec-linked",
    }
    assert [ref.source for ref in context.identity_evidence_refs] == ["entities"]
    assert context.identity_evidence_refs[0].id == AGENT
    assert "private title omitted" not in repr(context)


@pytest.mark.asyncio
async def test_agent_episode_context_retains_identity_scope_without_execution_rows():
    episode = EpisodeRecord(
        episode_id="episode-without-execution",
        tenant_id=TENANT,
        subject=EntityRef(kind="agent", id=AGENT),
        kind="agent_lifecycle",
        status="open",
        source_event_id="unmatched-event",
    )

    class EpisodeStore:
        async def list_page_by_tenant(self, tenant_id, *, limit, cursor=None):
            assert tenant_id == TENANT
            return EpisodePageRead(
                records=(episode,),
                next_cursor=None,
                truncated=False,
            )

    context = await _read_agent_episode_context(
        TENANT,
        {AGENT},
        episode_store=EpisodeStore(),
        identity_rows=[
            {
                "tenant_id": TENANT,
                "agent_id": AGENT,
                "canonical_agent_entity_id": AGENT,
                "identity_evidence_id": AGENT,
                "identity_evidence_source": "entities",
            }
        ],
        execution_rows=[],
    )

    assert context.state == "available"
    assert context.items[0]["episodeId"] == "episode-without-execution"
    assert context.items[0]["matchedExecutions"] == []
    assert [ref.id for ref in context.identity_evidence_refs] == [AGENT]


@pytest.mark.asyncio
async def test_repository_execution_read_keeps_agent_episode_context_without_executions(
    monkeypatch: pytest.MonkeyPatch,
):
    import actions.agent.deployments as deployment_module
    import actions.agent_marketplace.identity_binding as binding_module
    import repositories.repos as repos_module

    episode = EpisodeRecord(
        episode_id="episode-agent-no-execution",
        tenant_id=TENANT,
        subject=EntityRef(kind="agent", id=AGENT),
        kind="agent_lifecycle",
        status="open",
        source_event_id="agent-created-event",
    )

    class AgentConfigs:
        async def find_by_id(self, agent_id):
            assert agent_id == AGENT
            return {"tenant_id": TENANT, "agent_id": AGENT}

    class AgentExecutions:
        async def list_for_agent(self, agent_id, tenant_id, *, limit):
            assert agent_id == AGENT
            assert tenant_id == TENANT
            return []

    class Delegations:
        async def find_by_id(self, delegation_id):
            raise AssertionError("no execution rows should read delegation authority")

    class Entities:
        async def find_by_id(self, entity_id):
            assert entity_id == AGENT
            return {
                "tenant_id": TENANT,
                "entity_type": "agent",
                "entity_id": AGENT,
                "created_at": "2026-10-16T09:00:00Z",
            }

    class EpisodePages:
        async def list_page_by_tenant(self, tenant_id, *, limit, cursor=None):
            assert tenant_id == TENANT
            assert limit == 201
            return EpisodePageRead(
                records=(episode,),
                next_cursor=None,
                truncated=False,
            )

    monkeypatch.setattr(deployment_module, "get_deployment_repository", lambda: object())
    monkeypatch.setattr(binding_module, "AgentDeploymentIdentityBindingRepository", object)
    monkeypatch.setattr(repos_module, "EntityRepository", Entities)
    monkeypatch.setattr(repos_module, "AgentConfigRepository", AgentConfigs)
    monkeypatch.setattr(repos_module, "AgentExecutionRepository", AgentExecutions)
    monkeypatch.setattr(repos_module, "DelegationRepository", Delegations)

    result = await RepositoryExecution360Source(episode_store=EpisodePages()).server_executions(
        tenant_id=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT),
        limit=20,
    )

    assert result.available is True
    assert result.scope_known is True
    assert result.rows == []
    assert result.episode_context is not None
    assert result.episode_context.state == "available"
    assert result.episode_context.items[0]["episodeId"] == "episode-agent-no-execution"
    assert result.episode_context.identity_evidence_refs[0].source == "entities"


@pytest.mark.asyncio
async def test_episode_store_tenant_page_is_bounded_and_partitioned(monkeypatch):
    import shared.backend_interpretation.stores as truth_stores

    backing = InMemoryStore("execution360-episode-page-test")
    monkeypatch.setattr(truth_stores, "_kv", lambda _name: backing)
    store = EpisodeStore()
    for tenant_id, episode_id in (
        (TENANT, "episode-page-a"),
        (TENANT, "episode-page-b"),
        ("tenant-other", "episode-page-foreign"),
    ):
        await store.upsert(
            EpisodeRecord(
                episode_id=episode_id,
                tenant_id=tenant_id,
                subject=EntityRef(kind="agent", id=AGENT),
                kind="execution_run",
            )
        )

    page = await store.list_page_by_tenant(TENANT, limit=1)

    assert len(page.records) == 1
    assert page.records[0].tenant_id == TENANT
    assert page.truncated is True
    assert page.next_cursor is not None


@pytest.mark.asyncio
async def test_execution_provider_surfaces_agent_episode_context_and_historical_unknown():
    episode_evidence = EvidenceRef(
        id="episode-agent-1",
        type="event",
        source="episode_records",
        uri="store://episode_records/episode-agent-1",
    )
    episode_context = ExecutionEpisodeContextRead(
        "available",
        items=(
            {
                "episodeId": "episode-agent-1",
                "agentEntityId": AGENT,
                "kind": "execution_run",
                "status": "closed",
                "sourceEventIds": ["trigger-1"],
                "evidenceRefs": [episode_evidence.model_dump(mode="json", by_alias=True)],
            },
        ),
        evidence_refs=(episode_evidence,),
    )
    source = FakeSource(
        server=ExecutionRead(
            rows=[_server_row()],
            available=True,
            scope_known=True,
            agent_ids=(AGENT,),
            episode_context=episode_context,
        )
    )
    request = _request()
    result = await Execution360Provider(source).project(request, await _context(request))

    section = next(section for section in result.sections if section.id == "episode_context")
    assert section.state == "available"
    assert section.content["episodes"][0]["episodeId"] == "episode-agent-1"
    assert section.content["evidenceRefs"][0]["id"] == "episode-agent-1"

    historical_request = _request(asOf="2026-10-16T10:00:00Z", temporalMode="as_of")
    historical = await Execution360Provider(source).project(
        historical_request, await _context(historical_request)
    )
    historical_section = next(
        section for section in historical.sections if section.id == "episode_context"
    )
    assert historical_section.state == "unknown"
    assert historical_section.content["episodes"] == []
    assert historical_section.content["reason"] == (
        "temporal_anchor_not_reconstructable_from_current_sources"
    )


@pytest.mark.asyncio
async def test_entity_observed_execution_read_exposes_owner_roster_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import actions.agent.deployments as deployment_module
    import actions.agent.identity_resolution as identity_module
    import actions.agent_marketplace.authority as authority_module
    import actions.agent_marketplace.identity_binding as binding_module
    import dependencies.providers as providers_module
    import repositories.repos as repos_module

    owner_id = "owner-with-many-agents"
    agent_ids = [f"agent-{index}" for index in range(201)]

    class AgentConfigs:
        async def list_for_owner(self, owner_entity_id, *, limit, tenant_id):
            assert owner_entity_id == owner_id
            assert limit == 201
            assert tenant_id == TENANT
            return [
                {"tenant_id": TENANT, "owner_entity_id": owner_id, "agent_id": agent_id}
                for agent_id in agent_ids
            ]

    class Analytics:
        def __init__(self, cache):
            pass

        async def query_silver(self, table, filters, *, limit):
            assert filters == {"tenant_id": TENANT}
            return []

    async def resolve(tenant_id, source_agent_ids, **kwargs):
        assert tenant_id == TENANT
        assert len(source_agent_ids) == 200
        return SimpleNamespace(
            rows=[
                {"agent_id": agent_id, "canonical_agent_entity_id": agent_id}
                for agent_id in source_agent_ids
            ],
            scope_mismatch=False,
            truncated=False,
        )

    monkeypatch.setattr(repos_module, "AgentConfigRepository", AgentConfigs)
    monkeypatch.setattr(repos_module, "AnalyticsRepository", Analytics)
    monkeypatch.setattr(identity_module, "resolve_agent_identities", resolve)
    monkeypatch.setattr(deployment_module, "get_deployment_repository", lambda: object())
    monkeypatch.setattr(binding_module, "AgentDeploymentIdentityBindingRepository", object)
    monkeypatch.setattr(repos_module, "EntityRepository", object)
    monkeypatch.setattr(authority_module, "AgentRunAuthorityResolver", object)
    monkeypatch.setattr(providers_module, "get_cache", lambda: object())

    result = await RepositoryExecution360Source().observed_facts(
        tenant_id=TENANT,
        subject=ProjectionSubject(kind="entity", id=owner_id),
        limit=10,
    )

    assert result.available is True
    assert result.scope_known is False
    assert result.truncated is True
    assert result.reason == "owner_agent_roster_read_truncated"
