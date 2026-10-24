"""Backend orchestration for catalog-bound Experience 360 frames.

The frame runtime evaluates policy before it starts projection reads, executes
only providers needed by requested and permitted slots, and delegates final
slot assembly to the strict composer. It does not implement a policy authority,
actor resolver, or canonical provider; those are injected authorities.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from shared.intelligence_projections.composition import (
    INTELLIGENCE_PROJECTION_DEFINITIONS,
    PRODUCT_360_SURFACE_DEFINITIONS,
    _aggregate_frame_state,
    _aggregate_freshness,
    _aggregate_quality,
    compose_experience360_frame,
)
from shared.intelligence_projections.contracts import (
    Experience360ActorAttribution,
    Experience360ActorParty,
    Experience360AuthorityDecision,
    Experience360Delegation,
    Experience360DriverScore,
    Experience360Frame,
    Experience360FrameRequest,
    Experience360Freshness,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
    Experience360ProjectionProvenance,
    Experience360Quality,
    EvidenceRef,
    ProjectionDegradation,
    ProjectionReadAuthorization,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import ProjectionError, ProjectionNotFound
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.projection_engine.runtime import ProjectionRuntime, runtime as default_runtime
from shared.projection_engine.temporal_modes import TemporalMode
from shared.temporal.instant import try_parse_instant


class Experience360PolicyEvaluator(Protocol):
    """Policy authority adapter evaluated before any provider is queried."""

    async def evaluate(self, request: Experience360FrameRequest) -> Experience360PolicyEvaluation:
        """Return decisions bound to the exact tenant and product surface."""
        ...


async def build_experience360_frame(
    request: Experience360FrameRequest,
    *,
    policy_evaluator: Experience360PolicyEvaluator,
    projection_runtime: Optional[ProjectionRuntime] = None,
    account360_provider: Optional[Any] = None,
    identity360_provider: Optional[Any] = None,
    actor_attribution: Optional[Experience360ActorAttribution] = None,
    actor_attribution_by_slot: Optional[Mapping[str, Experience360ActorAttribution]] = None,
    freshness_by_slot: Optional[Mapping[str, Experience360Freshness]] = None,
    quality_by_slot: Optional[Mapping[str, Experience360Quality]] = None,
    generated_at: Optional[str] = None,
    max_concurrency: int = 4,
) -> Experience360Frame:
    """Build one read-only frame from existing, governed projection providers.

    ``policy_evaluator`` is mandatory. Its result is checked for the requested
    tenant and surface before any provider call. Unknown, denied, and
    unscoped-redacted slots are suppressed without reading projection data.
    Provider exceptions become content-free degraded results; their messages
    are never copied to the response.
    """

    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least one")

    surface = PRODUCT_360_SURFACE_DEFINITIONS.get(request.surfaceId)
    if not isinstance(surface, dict):
        raise ProjectionNotFound(
            "unknown product 360 surface", context={"surfaceId": request.surfaceId}
        )
    supported_subject_kinds = surface.get("subjectKinds", [])
    if supported_subject_kinds and request.subject.kind not in supported_subject_kinds:
        raise ProjectionError(
            "360 surface does not support the requested subject kind",
            context={
                "surfaceId": request.surfaceId,
                "subjectKind": request.subject.kind,
            },
        )

    domain_slots = surface.get("domainSlots")
    if not isinstance(domain_slots, list):
        raise ProjectionError(
            "360 surface catalog has invalid domain slots",
            context={"surfaceId": request.surfaceId},
        )
    slot_definitions = {
        item.get("id"): item
        for item in domain_slots
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    if len(slot_definitions) != len(domain_slots):
        raise ProjectionError(
            "360 surface catalog has invalid or duplicate domain slots",
            context={"surfaceId": request.surfaceId},
        )
    requested_slot_ids = (
        list(slot_definitions)
        if request.requestedSlotIds is None
        else list(request.requestedSlotIds)
    )
    unknown_slots = sorted(set(requested_slot_ids) - set(slot_definitions))
    if unknown_slots:
        raise ProjectionError(
            "360 frame request names an unknown slot",
            context={"surfaceId": request.surfaceId, "slotIds": unknown_slots},
        )

    evaluator = policy_evaluator
    try:
        evaluation = await evaluator.evaluate(request)
        if not isinstance(evaluation, Experience360PolicyEvaluation):
            evaluation = Experience360PolicyEvaluation.model_validate(evaluation)
    except Exception:  # noqa: BLE001 - policy failure is a closed gate
        evaluated_at = datetime.now(timezone.utc).isoformat()
        evaluation = Experience360PolicyEvaluation(
            surfaceId=request.surfaceId,
            tenantId=request.tenantId,
            evaluatedAt=evaluated_at,
            frameDisposition=Experience360PolicyDisposition(
                state="unknown",
                evaluatedAt=evaluated_at,
                reasonCodes=["policy_evaluation_unavailable"],
            ),
        )

    if evaluation.surfaceId != request.surfaceId or evaluation.tenantId != request.tenantId:
        raise ProjectionError(
            "policy evaluation scope does not match the 360 frame request",
            context={"surfaceId": request.surfaceId},
        )
    invalid_policy_slots = sorted(set(evaluation.slotDispositions) - set(slot_definitions))
    if invalid_policy_slots:
        raise ProjectionError(
            "policy evaluation names slots outside the 360 surface catalog",
            context={"surfaceId": request.surfaceId, "slotIds": invalid_policy_slots},
        )

    selected_policy = {
        slot_id: evaluation.slotDispositions[slot_id]
        for slot_id in requested_slot_ids
        if slot_id in evaluation.slotDispositions
    }
    frame_gate = evaluation.frameDisposition
    if frame_gate.state in {"allowed", "not_applicable"}:
        readable_slot_ids = {
            slot_id
            for slot_id in requested_slot_ids
            if _is_readable(selected_policy.get(slot_id, frame_gate))
        }
    else:
        readable_slot_ids = set()

    account_policy: Optional[dict[str, Experience360PolicyDisposition]] = None
    account_identity_read: Optional[Any] = None
    if request.surfaceId == "account360" and readable_slot_ids:
        from identity.account360_provider import Account360Provider

        account_provider = account360_provider or Account360Provider()
        account_policy = {
            slot_id: selected_policy.get(slot_id, frame_gate) for slot_id in requested_slot_ids
        }
        try:
            account_identity_read = await account_provider.resolve_identity(request)
        except Exception:  # noqa: BLE001 - fail closed before sibling projection reads
            account_identity_read = None
        if account_identity_read is None or account_identity_read.state != "resolved":
            if account_identity_read is None:
                from identity.account360_provider import AccountIdentityRead

                account_identity_read = AccountIdentityRead(
                    "unavailable", "account_entity_authority_unavailable"
                )
            return await account_provider.compose(
                request,
                [],
                identity_read=account_identity_read,
                frame_policy=frame_gate,
                policy_by_slot=account_policy,
                freshness_by_slot=freshness_by_slot,
                quality_by_slot=quality_by_slot,
                generated_at=generated_at,
            )

    identity_provider = None
    identity_result: Optional[Any] = None
    identity_direct_slot_ids = {
        slot_id
        for binding in surface.get("directProviderBindings", [])
        if isinstance(binding, Mapping)
        and binding.get("providerClass") == "Identity360Provider"
        and isinstance(binding.get("domainSlotIds"), (list, tuple))
        for slot_id in binding["domainSlotIds"]
        if isinstance(slot_id, str)
    }
    identity_readable_slot_ids = (
        readable_slot_ids & identity_direct_slot_ids
        if request.surfaceId == "identity360"
        else set()
    )
    if identity_readable_slot_ids:
        from identity.identity.identity360_provider import Identity360Provider

        identity_provider = identity360_provider or Identity360Provider()
        try:
            identity_result = await identity_provider.read(
                request.tenantId,
                request.subject.kind,
                request.subject.id,
                requested_slot_ids=identity_readable_slot_ids,
            )
        except Exception:  # noqa: BLE001 - direct identity reads fail closed
            identity_result = None

    requested_sections_by_projection: dict[str, set[str]] = {}
    for slot_id in requested_slot_ids:
        if slot_id not in readable_slot_ids:
            continue
        slot_definition = slot_definitions[slot_id]
        bindings = slot_definition.get("projectionBindings", [])
        if not isinstance(bindings, list):
            continue
        for binding in bindings:
            if not isinstance(binding, Mapping):
                continue
            supported_binding_subjects = binding.get("subjectKinds")
            if (
                not isinstance(supported_binding_subjects, (list, tuple))
                or not all(isinstance(kind, str) for kind in supported_binding_subjects)
                or request.subject.kind not in supported_binding_subjects
            ):
                continue
            projection_id = binding.get("projectionId")
            section_ids = binding.get("sectionIds", [])
            if not isinstance(projection_id, str) or not isinstance(section_ids, (list, tuple)):
                continue
            bucket = requested_sections_by_projection.setdefault(projection_id, set())
            bucket.update(item for item in section_ids if isinstance(item, str))

    runner = projection_runtime or default_runtime
    semaphore = asyncio.Semaphore(max_concurrency)
    generated_timestamp = generated_at or datetime.now(timezone.utc).isoformat()

    async def run_projection(
        projection_id: str, section_ids: set[str]
    ) -> tuple[str, ProjectionResult]:
        definition = INTELLIGENCE_PROJECTION_DEFINITIONS.get(projection_id)
        if definition is None:
            return projection_id, _unavailable_result(
                projection_id,
                request,
                section_ids,
                generated_timestamp,
                "projection_definition_unavailable",
            )

        temporal_surface_mode = "as_of" if request.asOf is not None else "window"
        supported_modes = definition.get("supportedTemporalModes", [])
        if supported_modes and temporal_surface_mode not in supported_modes:
            return projection_id, _unavailable_result(
                projection_id,
                request,
                section_ids,
                generated_timestamp,
                "projection_temporal_mode_unsupported",
            )

        projection_request = ProjectionRequest(
            projectionId=projection_id,
            tenantId=request.tenantId,
            subject=request.subject,
            page=request.page,
            timeRange=request.timeRange,
            asOf=request.asOf,
            includeSections=sorted(section_ids) or None,
            includeClaims=True,
            lensIds=request.lensIds,
            temporalMode=temporal_surface_mode,
        )
        read_authorizations: list[ProjectionReadAuthorization] = []
        if request.surfaceId == "agent360" and projection_id == "agent360":
            # Agent360 can make a nested current Risk360 read while assembling
            # its broader state section. Carry the exact outer slot decision
            # only when that slot was requested, allowed by policy, and bound
            # to a projection that declares the required read capability.
            # The public frame body cannot provide this server-derived envelope.
            risk_slot_id = "risk_summary"
            risk_slot = surface.get("domainSlots", [])
            risk_slot_definition = next(
                (
                    item
                    for item in risk_slot
                    if isinstance(item, Mapping) and item.get("id") == risk_slot_id
                ),
                None,
            )
            risk_disposition = selected_policy.get(risk_slot_id)
            risk_bindings = (
                risk_slot_definition.get("projectionBindings", [])
                if isinstance(risk_slot_definition, Mapping)
                else []
            )
            risk_binding = next(
                (
                    binding
                    for binding in risk_bindings
                    if isinstance(binding, Mapping)
                    and binding.get("projectionId") == "risk360"
                    and request.subject.kind in binding.get("subjectKinds", [])
                ),
                None,
            )
            risk_definition = INTELLIGENCE_PROJECTION_DEFINITIONS.get("risk360", {})
            capability_keys = risk_definition.get("capabilityKeys", [])
            if (
                risk_slot_id in requested_slot_ids
                and risk_disposition is not None
                and risk_disposition.state == "allowed"
                and isinstance(risk_binding, Mapping)
                and isinstance(capability_keys, (list, tuple))
                and "risk360.read" in capability_keys
            ):
                read_authorizations.append(
                    ProjectionReadAuthorization(
                        tenantId=request.tenantId,
                        sourceSurfaceId=request.surfaceId,
                        sourceSubject=request.subject,
                        sourceSlotId=risk_slot_id,
                        consumerProjectionId="agent360",
                        targetProjectionId="risk360",
                        capabilityKey="risk360.read",
                        policyState=risk_disposition.state,
                        policyIds=list(risk_disposition.policyIds),
                        policyEvaluatedAt=risk_disposition.evaluatedAt,
                    )
                )
        async with semaphore:
            try:
                execution_kwargs = {
                    "lens_ids": request.lensIds,
                    "temporal_mode": (
                        TemporalMode.AS_OF if request.asOf is not None else TemporalMode.LIVE
                    ),
                }
                if read_authorizations:
                    execution_kwargs["experience360_read_authorizations"] = read_authorizations
                result = await runner.execute_projection(projection_request, **execution_kwargs)
            except Exception:  # noqa: BLE001 - fail-isolated projection boundary
                result = _unavailable_result(
                    projection_id,
                    request,
                    section_ids,
                    generated_timestamp,
                    "projection_execution_unavailable",
                )

        return projection_id, result

    pairs = await asyncio.gather(
        *(
            run_projection(projection_id, section_ids)
            for projection_id, section_ids in sorted(requested_sections_by_projection.items())
        )
    )
    results = [result for _, result in pairs]
    resolved_actor_metadata = _derive_agent_actor_metadata(request, results)
    if actor_attribution_by_slot:
        resolved_actor_metadata.update(actor_attribution_by_slot)
    if request.surfaceId == "account360" and account_identity_read is not None:
        async def read_account_member_profile(
            member: Any, account_request: Experience360FrameRequest
        ) -> Experience360Frame:
            """Build each member's profile through the governed Profile360 runtime."""

            profile_surface = PRODUCT_360_SURFACE_DEFINITIONS.get("profile360", {})
            profile_lens_contract = profile_surface.get("lensContract", {})
            profile_lens_ids = profile_lens_contract.get("lensIds", [])
            if account_request.lensIds is None:
                profile_lens_ids_for_request = None
            else:
                allowed_profile_lenses = {
                    lens_id for lens_id in profile_lens_ids if isinstance(lens_id, str)
                }
                profile_lens_ids_for_request = [
                    lens_id
                    for lens_id in account_request.lensIds
                    if lens_id in allowed_profile_lenses
                ] or None

            profile_request = Experience360FrameRequest(
                surfaceId="profile360",
                tenantId=account_request.tenantId,
                subject=ProjectionSubject(
                    kind="agent" if member.entity_type == "agent" else "entity",
                    id=member.entity_id,
                ),
                asOf=account_request.asOf,
                timeRange=account_request.timeRange,
                includeEvidence=account_request.includeEvidence,
                lensIds=profile_lens_ids_for_request,
                requestedBy=account_request.requestedBy,
                purpose=account_request.purpose,
                authorizationContextRef=account_request.authorizationContextRef,
            )
            return await build_experience360_frame(
                profile_request,
                policy_evaluator=evaluator,
                projection_runtime=runner,
                actor_attribution=actor_attribution,
                generated_at=generated_timestamp,
                max_concurrency=1,
            )

        async def read_account_member_journey(
            member: Any, account_request: Experience360FrameRequest
        ) -> Experience360Frame:
            """Read one member's journey slot under Profile360 policy."""

            profile_surface = PRODUCT_360_SURFACE_DEFINITIONS.get("profile360", {})
            profile_lens_contract = profile_surface.get("lensContract", {})
            profile_lens_ids = profile_lens_contract.get("lensIds", [])
            if account_request.lensIds is None:
                profile_lens_ids_for_request = None
            else:
                allowed_profile_lenses = {
                    lens_id for lens_id in profile_lens_ids if isinstance(lens_id, str)
                }
                profile_lens_ids_for_request = [
                    lens_id
                    for lens_id in account_request.lensIds
                    if lens_id in allowed_profile_lenses
                ] or None

            profile_request = Experience360FrameRequest(
                surfaceId="profile360",
                tenantId=account_request.tenantId,
                subject=ProjectionSubject(kind="entity", id=member.entity_id),
                requestedSlotIds=["journey_participation"],
                asOf=account_request.asOf,
                timeRange=account_request.timeRange,
                includeEvidence=account_request.includeEvidence,
                lensIds=profile_lens_ids_for_request,
                requestedBy=account_request.requestedBy,
                purpose=account_request.purpose,
                authorizationContextRef=account_request.authorizationContextRef,
            )
            return await build_experience360_frame(
                profile_request,
                policy_evaluator=evaluator,
                projection_runtime=runner,
                actor_attribution=actor_attribution,
                generated_at=generated_timestamp,
                max_concurrency=1,
            )

        async def read_account_member_risk(
            member: Any, account_request: Experience360FrameRequest
        ) -> Experience360Frame:
            """Build each member's Risk360 frame through its own policy gate."""

            risk_surface = PRODUCT_360_SURFACE_DEFINITIONS.get("risk360", {})
            risk_lens_contract = risk_surface.get("lensContract", {})
            risk_lens_ids = risk_lens_contract.get("lensIds", [])
            if account_request.lensIds is None:
                risk_lens_ids_for_request = None
            else:
                allowed_risk_lenses = {
                    lens_id for lens_id in risk_lens_ids if isinstance(lens_id, str)
                }
                risk_lens_ids_for_request = [
                    lens_id
                    for lens_id in account_request.lensIds
                    if lens_id in allowed_risk_lenses
                ] or None

            risk_request = Experience360FrameRequest(
                surfaceId="risk360",
                tenantId=account_request.tenantId,
                subject=ProjectionSubject(
                    kind="agent" if member.entity_type == "agent" else "entity",
                    id=member.entity_id,
                ),
                asOf=account_request.asOf,
                timeRange=account_request.timeRange,
                includeEvidence=account_request.includeEvidence,
                lensIds=risk_lens_ids_for_request,
                requestedSlotIds=["risk_summary"],
                requestedBy=account_request.requestedBy,
                purpose=account_request.purpose,
                authorizationContextRef=account_request.authorizationContextRef,
            )
            return await build_experience360_frame(
                risk_request,
                policy_evaluator=evaluator,
                projection_runtime=runner,
                actor_attribution=actor_attribution,
                generated_at=generated_timestamp,
                max_concurrency=1,
            )

        return await account_provider.compose(
            request,
            results,
            identity_read=account_identity_read,
            frame_policy=frame_gate,
            policy_by_slot=account_policy,
            freshness_by_slot=freshness_by_slot,
            quality_by_slot=quality_by_slot,
            actor_attribution=actor_attribution,
            actor_attribution_by_slot=resolved_actor_metadata,
            member_profile_reader=read_account_member_profile,
            member_journey_reader=read_account_member_journey,
            member_risk_reader=read_account_member_risk,
            generated_at=generated_timestamp,
        )
    frame = compose_experience360_frame(
        request,
        results,
        freshness_by_slot=freshness_by_slot,
        quality_by_slot=quality_by_slot,
        policy_by_slot=selected_policy,
        frame_policy=frame_gate,
        actor_attribution=actor_attribution,
        actor_attribution_by_slot=resolved_actor_metadata,
        generated_at=generated_timestamp,
    )
    if identity_result is not None:
        return _merge_identity360_authority_result(
            frame,
            identity_result,
            readable_slot_ids=identity_readable_slot_ids,
            slot_definitions=slot_definitions,
        )
    if request.surfaceId == "identity360" and identity_readable_slot_ids:
        return frame.model_copy(
            update={
                "warnings": sorted(set([*frame.warnings, "identity360_authority_read_unavailable"]))
            }
        )
    return frame


def _derive_agent_actor_metadata(
    request: Experience360FrameRequest,
    results: list[ProjectionResult],
) -> dict[str, Experience360ActorAttribution]:
    """Translate execution evidence into explicit actor/authority frame metadata.

    The function does not resolve identity or evaluate standing permissions.
    It accepts only structured actor IDs paired with provider claims and their
    evidence. Execution360 can supply an authenticated initiating-principal
    assertion and action-scoped actor/delegation decisions; Agent360 can supply
    those same action-scoped decisions, canonical actor binding evidence, and a
    tenant USER_ID resolution for an authenticated execution principal. Absent
    action-scoped decisions stay unknown, and identity resolution never grants
    action authority.
    """
    if request.surfaceId not in {"agent360", "execution360"}:
        return {}

    surface = PRODUCT_360_SURFACE_DEFINITIONS.get(request.surfaceId, {})
    slots = surface.get("domainSlots", [])
    required_slots = {
        slot.get("id"): set(slot.get("requiredFrameMetadata", []))
        for slot in slots
        if isinstance(slot, Mapping)
        and isinstance(slot.get("id"), str)
        and isinstance(slot.get("requiredFrameMetadata", []), (list, tuple))
    }
    requested_slots = (
        set(required_slots) if request.requestedSlotIds is None else set(request.requestedSlotIds)
    )
    metadata_slots = {
        slot_id
        for slot_id, requirements in required_slots.items()
        if slot_id in requested_slots and "slotActorAttribution" in requirements
    }
    # Agent 360 retains actor_attribution as an optional compatibility slot.
    # When explicitly requested, it carries the same evidence-backed metadata
    # as the required authority and delegation slots.
    if request.surfaceId == "agent360" and "actor_attribution" in requested_slots:
        metadata_slots.add("actor_attribution")
    if not metadata_slots:
        return {}

    execution_result = next(
        (result for result in results if result.projectionId == "execution360"),
        None,
    )
    actor_evidence: dict[str, dict[tuple[str, str], EvidenceRef]] = {}
    execution_actor_ids: set[str] = set()
    execution_principal_evidence: dict[str, dict[tuple[str, str], EvidenceRef]] = {}
    execution_ids_with_principal_evidence: set[str] = set()
    server_execution_ids: set[str] = set()
    server_execution_row_count = 0
    all_server_rows_have_principal_evidence = True
    decisions: list[
        tuple[
            str,
            Optional[str],
            Optional[str],
            Optional[str],
            str,
            EvidenceRef,
            Optional[str],
        ]
    ] = []
    interaction_content: dict[str, Any] = {}
    server_lifecycle_complete = False
    source_telemetry_complete = False
    claims: list[Any] = []
    agent_delegation_chain: list[Experience360Delegation] = []
    agent_delegator: Optional[Experience360ActorParty] = None
    agent_delegatee: Optional[Experience360ActorParty] = None
    agent360_authority_result_present = False
    agent_subject_identity_ids: set[str] = set()
    execution_principal_canonical_identity: Optional[Experience360ActorParty] = None
    execution_principal_identity_evidence: dict[tuple[str, str], EvidenceRef] = {}

    def recorded_decision_time(value: Any, record_created_at: Any = None) -> Optional[str]:
        if not isinstance(value, str):
            return None
        parsed, error = try_parse_instant(value)
        if error is not None or parsed is None:
            return None
        if isinstance(record_created_at, str):
            created, _ = try_parse_instant(record_created_at)
            if created is not None and parsed > created:
                return None
        return parsed.isoformat()

    if execution_result is not None and execution_result.tenantId == request.tenantId:
        sections = {section.id: section for section in execution_result.sections}
        state = sections.get("state")
        interactions = sections.get("interactions")
        state_content = (
            state.content if state is not None and isinstance(state.content, dict) else {}
        )
        interaction_content = (
            interactions.content
            if interactions is not None and isinstance(interactions.content, dict)
            else {}
        )
        source_states = state_content.get("sourceStates")
        server_lifecycle_complete = (
            isinstance(source_states, dict)
            and source_states.get("serverRecordedLifecycle") == "available"
        )
        source_telemetry_complete = (
            isinstance(source_states, dict)
            and source_states.get("sourceReportedTelemetry") == "available"
        )
        claims = list(execution_result.claims)
        raw_server_rows = state_content.get("serverRecordedExecutions", [])
        server_rows = raw_server_rows if isinstance(raw_server_rows, list) else []
        if server_lifecycle_complete and not isinstance(raw_server_rows, list):
            all_server_rows_have_principal_evidence = False

        def evidence_for(kind: str, record_id: str) -> list[EvidenceRef]:
            refs: list[EvidenceRef] = []
            for claim in claims:
                if claim.kind != kind or not claim.evidenceRefs:
                    continue
                for evidence in claim.evidenceRefs:
                    if evidence.id == record_id:
                        refs.append(evidence)
            return refs

        for row in server_rows if server_lifecycle_complete else []:
            server_execution_row_count += 1
            if not isinstance(row, dict):
                all_server_rows_have_principal_evidence = False
                continue
            execution_id = row.get("executionId")
            if isinstance(execution_id, str) and execution_id:
                server_execution_ids.add(execution_id)
            agent_id = row.get("agentId")
            if (
                row.get("canonicalActorResolved") is True
                and isinstance(agent_id, str)
                and agent_id
                and isinstance(execution_id, str)
            ):
                execution_actor_refs = _exact_actor_claim_evidence(
                    claims,
                    claim_id=f"execution360:server-actor:{execution_id}",
                    claim_kind="canonically_resolved_server_agent_actor",
                    claim_state="resolved",
                    subject=request.subject,
                    evidence_id=execution_id,
                    evidence_source="agent_executions",
                    domain_slot_id="actor_attribution",
                )
                for evidence in execution_actor_refs:
                    actor_evidence.setdefault(agent_id, {})[(evidence.source, evidence.id)] = (
                        evidence
                    )
                if execution_actor_refs:
                    execution_actor_ids.add(agent_id)

            principal_user_id = row.get("initiatingPrincipalUserId")
            row_has_principal_evidence = False
            if (
                isinstance(principal_user_id, str)
                and principal_user_id
                and isinstance(execution_id, str)
            ):
                for evidence in evidence_for("authenticated_execution_principal", execution_id):
                    execution_principal_evidence.setdefault(principal_user_id, {})[
                        (evidence.source, evidence.id)
                    ] = evidence
                    execution_ids_with_principal_evidence.add(execution_id)
                    row_has_principal_evidence = True
            if not row_has_principal_evidence:
                all_server_rows_have_principal_evidence = False

            decision = row.get("recordedDelegationDecision")
            delegation_id = row.get("delegationId")
            if isinstance(decision, bool) and isinstance(execution_id, str):
                for evidence in evidence_for("server_recorded_delegation_decision", execution_id):
                    decisions.append(
                        (
                            "allow" if decision else "deny",
                            delegation_id if isinstance(delegation_id, str) else None,
                            row.get("requestedAction")
                            if isinstance(row.get("requestedAction"), str)
                            and row["requestedAction"].strip()
                            else None,
                            row.get("requestedResource")
                            if isinstance(row.get("requestedResource"), str)
                            and row["requestedResource"].strip()
                            else None,
                            execution_id,
                            evidence,
                            recorded_decision_time(
                                row.get("recordedDelegationDecisionEvaluatedAt"),
                                row.get("recordCreatedAt"),
                            ),
                        )
                    )

    principal_ids = sorted(execution_principal_evidence)
    execution_principal_complete = (
        bool(server_execution_ids)
        and server_execution_row_count == len(server_execution_ids)
        and all_server_rows_have_principal_evidence
        and execution_ids_with_principal_evidence == server_execution_ids
    )
    execution_principal = (
        Experience360ActorParty(kind="human", id=principal_ids[0])
        if execution_principal_complete and len(principal_ids) == 1
        else None
    )

    if request.surfaceId == "agent360":
        agent_result = next(
            (result for result in results if result.projectionId == "agent360"),
            None,
        )
        if agent_result is not None and agent_result.tenantId == request.tenantId:
            agent360_authority_result_present = True
            sections = {section.id: section for section in agent_result.sections}
            state = sections.get("state")
            state_content = (
                state.content if state is not None and isinstance(state.content, dict) else {}
            )
            actor_section = next(
                (
                    dimension
                    for dimension in state_content.get("dimensions", [])
                    if isinstance(dimension, dict) and dimension.get("id") == "actor_attribution"
                ),
                None,
            )
            actor_content = (
                actor_section.get("content")
                if isinstance(actor_section, dict)
                and isinstance(actor_section.get("content"), dict)
                else {}
            )
            authority_section = next(
                (
                    dimension
                    for dimension in state_content.get("dimensions", [])
                    if isinstance(dimension, dict)
                    and dimension.get("id") == "authority_and_delegation"
                ),
                None,
            )
            authority_content = (
                authority_section.get("content")
                if isinstance(authority_section, dict)
                and isinstance(authority_section.get("content"), dict)
                else {}
            )
            action_scoped_decisions = authority_content.get("actionScopedDecisions")
            if isinstance(action_scoped_decisions, list):
                agent_claims = list(agent_result.claims)
                for decision in action_scoped_decisions:
                    if not isinstance(decision, dict):
                        continue
                    outcome = decision.get("decision")
                    execution_id = decision.get("executionId")
                    action_ref = decision.get("action")
                    if (
                        outcome not in {"allow", "deny"}
                        or not isinstance(execution_id, str)
                        or not execution_id.strip()
                        or execution_id != execution_id.strip()
                        or not isinstance(action_ref, str)
                        or not action_ref.strip()
                    ):
                        continue
                    try:
                        decision_evidence = EvidenceRef.model_validate(
                            decision.get("evidenceRef")
                        )
                    except Exception:  # noqa: BLE001 - invalid evidence fails closed
                        continue
                    if (
                        decision_evidence.source != "agent_executions"
                        or decision_evidence.type != "event"
                        or decision_evidence.id != execution_id
                    ):
                        continue

                    expected_claim_id = (
                        f"agent_execution_delegation_decision.{execution_id}"
                    )
                    claims_for_execution = [
                        claim for claim in agent_claims if claim.id == expected_claim_id
                    ]
                    if len(claims_for_execution) != 1:
                        continue
                    claim = claims_for_execution[0]
                    claim_state = getattr(claim.claimState, "value", claim.claimState)
                    if (
                        claim.kind != "server_recorded_delegation_decision"
                        or claim_state != "observed"
                        or claim.subject.kind != request.subject.kind
                        or claim.subject.id != request.subject.id
                        or "authority_envelope" not in (claim.domainSlotIds or [])
                        or not set(claim.domainSlotIds or []).issubset(
                            {"authority_envelope", "authority_check"}
                        )
                        or not any(
                            evidence.source == "agent_executions"
                            and evidence.type == "event"
                            and evidence.id == execution_id
                            for evidence in claim.evidenceRefs
                        )
                    ):
                        continue

                    delegation_id = decision.get("delegationId")
                    if not isinstance(delegation_id, str) or not delegation_id.strip():
                        delegation_id = None
                    resource_ref = decision.get("resource")
                    decisions.append(
                        (
                            outcome,
                            delegation_id,
                            action_ref.strip(),
                            resource_ref.strip()
                            if isinstance(resource_ref, str) and resource_ref.strip()
                            else None,
                            execution_id.strip(),
                            decision_evidence,
                            recorded_decision_time(decision.get("decisionAt")),
                        )
                    )

            canonical_identity = actor_content.get("executionPrincipalCanonicalIdentity")
            raw_principal_candidates = actor_content.get("executionPrincipalCandidates")
            identity_evidence_refs = (
                canonical_identity.get("evidenceRefs")
                if isinstance(canonical_identity, dict)
                else None
            )
            principal_evidence_refs = actor_content.get("executionPrincipalEvidenceRefs")
            canonical_human_id = (
                canonical_identity.get("canonicalHumanEntityId")
                if isinstance(canonical_identity, dict)
                else None
            )
            candidate_human_ids = (
                canonical_identity.get("candidateEntityIds")
                if isinstance(canonical_identity, dict)
                else None
            )
            parsed_identity_refs: dict[tuple[str, str], EvidenceRef] = {}
            parsed_principal_refs: dict[tuple[str, str], EvidenceRef] = {}
            evidence_is_valid = True
            identity_ref_sources: set[str] = set()
            for raw_refs, parsed_refs, reference_role in (
                (identity_evidence_refs, parsed_identity_refs, "identity"),
                (principal_evidence_refs, parsed_principal_refs, "execution"),
            ):
                if not isinstance(raw_refs, list) or not raw_refs:
                    evidence_is_valid = False
                    break
                for raw_ref in raw_refs:
                    try:
                        evidence = EvidenceRef.model_validate(raw_ref)
                    except Exception:  # noqa: BLE001 - malformed source evidence fails closed
                        evidence_is_valid = False
                        break
                    if reference_role == "identity":
                        if (
                            evidence.source not in {"identity_aliases", "identity_subjects"}
                            or evidence.type != "entity"
                        ):
                            evidence_is_valid = False
                            break
                        identity_ref_sources.add(evidence.source)
                    elif evidence.source != "agent_executions" or evidence.type != "event":
                        evidence_is_valid = False
                        break
                    parsed_refs[(evidence.source, evidence.id)] = evidence
                if not evidence_is_valid:
                    break
            evidence_is_valid = evidence_is_valid and identity_ref_sources == {
                "identity_aliases",
                "identity_subjects",
            }
            raw_candidates_are_valid = (
                isinstance(raw_principal_candidates, list) and bool(raw_principal_candidates)
            )
            candidate_execution_ids_by_principal: dict[str, set[str]] = {}
            if raw_candidates_are_valid:
                for candidate in raw_principal_candidates:
                    principal = candidate.get("principal") if isinstance(candidate, dict) else None
                    execution_ids = candidate.get("executionIds") if isinstance(candidate, dict) else None
                    if (
                        not isinstance(principal, dict)
                        or principal.get("kind") != "human"
                        or not isinstance(principal.get("id"), str)
                        or not principal["id"].strip()
                        or not isinstance(execution_ids, list)
                        or not execution_ids
                        or any(not isinstance(item, str) or not item.strip() for item in execution_ids)
                        or principal["id"] in candidate_execution_ids_by_principal
                    ):
                        raw_candidates_are_valid = False
                        break
                    candidate_execution_ids_by_principal[principal["id"]] = set(execution_ids)
            principal_execution_evidence_matches = (
                execution_principal_complete
                and raw_candidates_are_valid
                and set(candidate_execution_ids_by_principal) == set(execution_principal_evidence)
                and all(
                    execution_ids.issubset(
                        {
                            evidence.id
                            for (source, _), evidence in execution_principal_evidence[
                                principal_id
                            ].items()
                            if source == "agent_executions"
                        }
                    )
                    and execution_ids.issubset(server_execution_ids)
                    and execution_ids.issubset(
                        {
                            evidence.id
                            for evidence in parsed_principal_refs.values()
                            if evidence.source == "agent_executions"
                        }
                    )
                    for principal_id, execution_ids in candidate_execution_ids_by_principal.items()
                )
            )
            if (
                isinstance(canonical_identity, dict)
                and canonical_identity.get("state") == "resolved"
                and isinstance(canonical_human_id, str)
                and canonical_human_id.strip()
                and candidate_human_ids == [canonical_human_id]
                and actor_content.get("executionPrincipalState") in {"available", "ambiguous"}
                and raw_candidates_are_valid
                and evidence_is_valid
                and principal_execution_evidence_matches
            ):
                execution_principal_canonical_identity = Experience360ActorParty(
                    kind="human",
                    id=canonical_human_id,
                )
                execution_principal_identity_evidence.update(parsed_identity_refs)
                execution_principal_identity_evidence.update(parsed_principal_refs)

            canonical_agent_id = actor_content.get("resolvedCanonicalActor")
            if isinstance(canonical_agent_id, str) and canonical_agent_id:
                (
                    agent_delegation_chain,
                    agent_delegator,
                    agent_delegatee,
                ) = _agent360_observed_delegation_chain(
                    tenant_id=request.tenantId,
                    subject=request.subject,
                    canonical_agent_id=canonical_agent_id,
                    authority_content=authority_content,
                    claims=agent_result.claims,
                )
                for claim in agent_result.claims:
                    claim_state = getattr(claim.claimState, "value", claim.claimState)
                    if (
                        claim.kind != "canonically_resolved_agent_identity"
                        or claim_state != "resolved"
                        or not {"identity", "actor_attribution"}.issubset(
                            set(claim.domainSlotIds or [])
                        )
                        or not claim.evidenceRefs
                    ):
                        continue
                    for evidence in claim.evidenceRefs:
                        actor_evidence.setdefault(canonical_agent_id, {})[
                            (evidence.source, evidence.id)
                        ] = evidence
                    agent_subject_identity_ids.add(canonical_agent_id)

    delegation_candidates: dict[str, dict[str, Any]] = {}
    conflicted_delegations: set[str] = set()
    if request.surfaceId in {"agent360", "execution360"} and source_telemetry_complete:
        for row in interaction_content.get("interactions", []):
            if not isinstance(row, dict):
                continue
            actor_id = row.get("actorAgentId")
            source_event_id = row.get("sourceEventId")
            if isinstance(actor_id, str) and actor_id and isinstance(source_event_id, str):
                execution_actor_refs = _exact_actor_claim_evidence(
                    claims,
                    claim_id=f"execution360:actor:{source_event_id}",
                    claim_kind="canonically_resolved_execution_actor",
                    claim_state="resolved",
                    subject=request.subject,
                    evidence_id=source_event_id,
                    evidence_source=None,
                    domain_slot_id="actor_attribution",
                )
                for evidence in execution_actor_refs:
                    actor_evidence.setdefault(actor_id, {})[(evidence.source, evidence.id)] = (
                        evidence
                    )
            delegation_id = row.get("delegationId")
            if (
                row.get("delegationPartyBindingStatus") != "matched"
                or not isinstance(delegation_id, str)
                or not delegation_id
                or row.get("delegationEvidenceId") != delegation_id
                or not isinstance(source_event_id, str)
            ):
                continue
            resolved_claim = next(
                (
                    claim
                    for claim in claims
                    if claim.kind == "canonically_resolved_delegation_parties"
                    and claim.id == f"execution360:delegation-parties:{source_event_id}"
                    and getattr(claim.claimState, "value", claim.claimState) == "resolved"
                    and claim.subject.kind == request.subject.kind
                    and claim.subject.id == request.subject.id
                    and any(
                        evidence.source == "delegations" and evidence.id == delegation_id
                        for evidence in claim.evidenceRefs
                    )
                    and any(evidence.id == source_event_id for evidence in claim.evidenceRefs)
                ),
                None,
            )
            delegator_id = row.get("delegatorAgentId")
            delegatee_id = row.get("delegateeAgentId")
            scope = row.get("delegationScope")
            status = row.get("delegationStatus")
            valid_from = row.get("delegationValidFrom")
            valid_until = row.get("delegationValidUntil")
            if (
                resolved_claim is None
                or not isinstance(delegator_id, str)
                or not delegator_id
                or not isinstance(delegatee_id, str)
                or not delegatee_id
            ):
                continue
            candidate = {
                "id": delegation_id,
                "delegator": Experience360ActorParty(kind="agent", id=delegator_id),
                "delegatee": Experience360ActorParty(kind="agent", id=delegatee_id),
                "scope": sorted(
                    {value.strip() for value in scope if isinstance(value, str) and value.strip()}
                )
                if isinstance(scope, list)
                else [],
                "validFrom": valid_from,
                "validUntil": valid_until,
                "status": status,
                "evidenceRefs": resolved_claim.evidenceRefs,
            }
            signature = (
                delegator_id,
                delegatee_id,
                tuple(candidate["scope"]),
                valid_from,
                valid_until,
                status,
                tuple(
                    sorted(
                        (evidence.source, evidence.id)
                        for evidence in candidate["evidenceRefs"]
                        if evidence.source == "delegations"
                    )
                ),
            )
            existing = delegation_candidates.get(delegation_id)
            if existing is not None and existing["signature"] != signature:
                conflicted_delegations.add(delegation_id)
            else:
                if existing is not None:
                    refs = {
                        (evidence.source, evidence.id): evidence
                        for evidence in existing["evidenceRefs"]
                    }
                    refs.update(
                        {
                            (evidence.source, evidence.id): evidence
                            for evidence in candidate["evidenceRefs"]
                        }
                    )
                    candidate["evidenceRefs"] = list(refs.values())
                delegation_candidates[delegation_id] = {
                    **candidate,
                    "signature": signature,
                }

    actor_ids = sorted(actor_evidence)
    all_actor_refs = [
        actor_evidence[actor_id][key]
        for actor_id in actor_ids
        for key in sorted(actor_evidence[actor_id])
    ]
    if len(actor_ids) == 1:
        attribution_state = "resolved"
        canonical_actor = Experience360ActorParty(kind="agent", id=actor_ids[0])
    elif len(actor_ids) > 1:
        attribution_state = "ambiguous"
        canonical_actor = None
    else:
        attribution_state = "unknown"
        canonical_actor = None

    delegation: Optional[dict[str, Any]] = None
    if len(delegation_candidates) == 1 and not conflicted_delegations:
        delegation = next(iter(delegation_candidates.values()))
    delegator = delegation["delegator"] if delegation is not None else None
    delegatee = delegation["delegatee"] if delegation is not None else None
    delegation_chain: list[Experience360Delegation] = []
    if delegation is not None:
        status = delegation.get("status")
        valid_from = delegation.get("validFrom")
        valid_until = delegation.get("validUntil")
        scope = delegation.get("scope")
        if (
            status in {"asserted", "granted", "verified", "revoked", "expired", "unknown"}
            and isinstance(valid_from, str)
            and _has_timezone(valid_from)
            and (
                valid_until is None or (isinstance(valid_until, str) and _has_timezone(valid_until))
            )
            and isinstance(scope, list)
            and scope
        ):
            try:
                delegation_chain = [
                    Experience360Delegation(
                        id=delegation["id"],
                        tenantId=request.tenantId,
                        delegator=delegator,
                        delegatee=delegatee,
                        scope=scope,
                        validFrom=valid_from,
                        validUntil=valid_until,
                        status=status,
                        evidenceRefs=delegation["evidenceRefs"],
                    )
                ]
            except (TypeError, ValueError):
                # Malformed, noncontinuous, or insufficient canonical records
                # remain omitted from the typed chain rather than guessed.
                delegation_chain = []

    if request.surfaceId == "agent360" and agent360_authority_result_present:
        # Agent360's chain is backed by exact tenant delegation rows and
        # canonical party resolutions. Execution telemetry remains a separate
        # event-time input and cannot replace the Agent authority read.
        delegation_chain = agent_delegation_chain
        delegator = agent_delegator
        delegatee = agent_delegatee

    attribution_evidence = {(evidence.source, evidence.id): evidence for evidence in all_actor_refs}
    if execution_principal_complete and len(principal_ids) == 1:
        attribution_evidence.update(execution_principal_evidence[principal_ids[0]])
    attribution_evidence.update(execution_principal_identity_evidence)
    if delegation is not None:
        for evidence in delegation["evidenceRefs"]:
            attribution_evidence[(evidence.source, evidence.id)] = evidence

    unique_decisions = {
        (outcome, delegation_id, action_ref, resource_ref)
        for outcome, delegation_id, action_ref, resource_ref, _, _, _ in decisions
    }
    decision_refs = {
        (evidence.source, evidence.id): evidence
        for _, _, _, _, _, evidence, _ in decisions
    }
    decision_action_refs = sorted(
        {
            action_ref
            for _, _, action_ref, _, _, _, _ in decisions
            if action_ref is not None
        }
    )
    decision_resource_refs = sorted(
        {
            resource_ref
            for _, _, _, resource_ref, _, _, _ in decisions
            if resource_ref is not None
        }
    )
    decision_execution_refs = sorted(
        {execution_id for _, _, _, _, execution_id, _, _ in decisions}
    )
    if len(unique_decisions) == 1:
        outcome, delegation_id, action_ref, resource_ref = next(iter(unique_decisions))
        action_scope_known = action_ref is not None
        authority_decision = Experience360AuthorityDecision(
            tenantId=request.tenantId,
            outcome=outcome if action_scope_known else "unknown",
            authorityRef="aether.agent_delegation_engine" if action_scope_known else None,
            decidedAt=decisions[0][6] if action_scope_known and len(decisions) == 1 else None,
            delegationRefs=[delegation_id] if delegation_id is not None else [],
            actionRefs=[action_ref] if action_ref is not None else [],
            resourceRefs=[resource_ref] if resource_ref is not None else [],
            executionRefs=decision_execution_refs,
            evidenceRefs=list(decision_refs.values()),
            reasonCodes=[
                "recorded_execution_decision_missing_action_scope"
                if not action_scope_known
                else "recorded_execution_scoped_decision_not_standing_authority"
                if delegation_id is not None
                else "recorded_delegation_denial_without_matching_grant"
            ],
        )
    else:
        authority_decision = Experience360AuthorityDecision(
            tenantId=request.tenantId,
            outcome="unknown",
            delegationRefs=sorted(
                {
                    delegation_id
                    for _, delegation_id, _, _, _, _, _ in decisions
                    if delegation_id is not None
                }
            ),
            actionRefs=decision_action_refs,
            resourceRefs=decision_resource_refs,
            executionRefs=decision_execution_refs,
            evidenceRefs=list(decision_refs.values()),
            reasonCodes=[
                "no_action_scoped_decision_available"
                if not decisions
                else "multiple_action_scoped_decisions_not_collapsed"
            ],
        )

    agent_actor_is_execution_driver = (
        canonical_actor is not None
        and len(execution_actor_ids) == 1
        and execution_actor_ids == {canonical_actor.id}
    )
    agent_subject_identity_only = (
        request.surfaceId == "agent360"
        and canonical_actor is not None
        and canonical_actor.id in agent_subject_identity_ids
        and not execution_actor_ids
    )
    if agent_actor_is_execution_driver or agent_subject_identity_only:
        actor_kind = "agent"
        actor_subject_id = canonical_actor.id
        attributed_agent_id = canonical_actor.id
        driver_score = Experience360DriverScore(
            agentDriven=1.0 if agent_actor_is_execution_driver else 0.0,
            unknown=0.0 if agent_actor_is_execution_driver else 1.0,
        )
        confidence = "high" if agent_actor_is_execution_driver else "medium"
        explanation = (
            "Exact tenant-scoped execution evidence resolves one canonical Agent actor; "
            "the authenticated initiating principal remains a separate role."
            if agent_actor_is_execution_driver
            else "The Agent subject identity is resolved, but no execution-specific actor "
            "evidence establishes who drove an action."
        )
    else:
        actor_kind = "unknown"
        actor_subject_id = None
        attributed_agent_id = None
        driver_score = Experience360DriverScore(unknown=1.0)
        confidence = "low"
        explanation = (
            "Multiple canonical actor candidates remain; the action driver is unknown."
            if attribution_state == "ambiguous"
            else "No exact tenant-scoped action-driver evidence was available. An authenticated "
            "initiating principal is retained separately and is not treated as the actor."
        )

    authority_edge_ids = sorted(
        {
            *[step.id for step in delegation_chain],
            *authority_decision.delegationRefs,
        }
    )
    attribution = Experience360ActorAttribution(
        tenantId=request.tenantId,
        actorKind=actor_kind,
        actorSubjectId=actor_subject_id,
        representedSubjectId=request.subject.id,
        agentId=attributed_agent_id,
        humanPrincipalId=(
            execution_principal.id if execution_principal is not None else None
        ),
        authorityEdgeIds=authority_edge_ids,
        driverScore=driver_score,
        confidence=confidence,
        explanation=explanation,
        resolutionState=attribution_state,
        resolvedCanonicalActor=canonical_actor,
        executionPrincipal=execution_principal,
        executionPrincipalCanonicalIdentity=execution_principal_canonical_identity,
        delegator=delegator,
        delegatee=delegatee,
        delegationChain=delegation_chain,
        authorityDecision=authority_decision,
        evidenceRefs=list(attribution_evidence.values()),
    )
    return {slot_id: attribution for slot_id in metadata_slots}


def _exact_actor_claim_evidence(
    claims: list[Any],
    *,
    claim_id: str,
    claim_kind: str,
    claim_state: str,
    subject: ProjectionSubject,
    evidence_id: str,
    evidence_source: Optional[str],
    domain_slot_id: str,
) -> list[EvidenceRef]:
    """Return one exact action-event ref from a unique, slot-bound actor claim."""

    matches = [claim for claim in claims if getattr(claim, "id", None) == claim_id]
    if len(matches) != 1:
        return []
    claim = matches[0]
    state = getattr(claim.claimState, "value", claim.claimState)
    if (
        claim.kind != claim_kind
        or state != claim_state
        or claim.subject != subject
        or domain_slot_id not in (claim.domainSlotIds or [])
    ):
        return []
    evidence = [
        ref
        for ref in claim.evidenceRefs
        if ref.id == evidence_id
        and ref.type == "event"
        and (evidence_source is None or ref.source == evidence_source)
        and bool(ref.source.strip())
    ]
    unique = {(ref.source, ref.id): ref for ref in evidence}
    return list(unique.values()) if len(unique) == 1 else []


def _agent360_observed_delegation_chain(
    *,
    tenant_id: str,
    subject: ProjectionSubject,
    canonical_agent_id: str,
    authority_content: dict[str, Any],
    claims: list[Any],
) -> tuple[list[Experience360Delegation], Optional[Experience360ActorParty], Optional[Experience360ActorParty]]:
    """Type one exact Agent360 two-edge observation without inferring authority.

    The source path must be complete, continuous, tenant-bound, and supported by
    unique record and canonical-party claims. Any ambiguity or malformed edge
    suppresses the entire typed path.
    """

    empty: tuple[
        list[Experience360Delegation],
        Optional[Experience360ActorParty],
        Optional[Experience360ActorParty],
    ] = ([], None, None)
    chain = authority_content.get("delegationChain")
    records = authority_content.get("delegationRecords")
    if (
        not isinstance(chain, dict)
        or not isinstance(records, list)
        or chain.get("state") != "partial"
        or chain.get("boundedReadComplete") is not True
        or chain.get("intermediateCanonicalAgentEntityId") != canonical_agent_id
        or chain.get("transitiveAuthority") != "unknown"
        or chain.get("effectiveAuthorizationDecision") != "unknown"
    ):
        return empty

    paths = chain.get("observedAdjacentPaths")
    if not isinstance(paths, list) or len(paths) != 1:
        return empty
    path = paths[0]
    if not isinstance(path, dict) or path.get("kind") != "observed_adjacent_delegation_records":
        return empty

    delegation_ids = path.get("delegationRecordIds")
    party_ids = path.get("partyEntityIds")
    party_identities = path.get("partyIdentities")
    if (
        not isinstance(delegation_ids, list)
        or len(delegation_ids) != 2
        or any(not isinstance(value, str) or not value.strip() for value in delegation_ids)
        or delegation_ids[0] == delegation_ids[1]
        or not isinstance(party_ids, list)
        or len(party_ids) != 3
        or any(not isinstance(value, str) or not value.strip() for value in party_ids)
        or party_ids[1] != canonical_agent_id
        or not isinstance(party_identities, list)
        or len(party_identities) != 3
    ):
        return empty

    resolved_parties: list[Experience360ActorParty] = []
    for entity_id, raw_party in zip(party_ids, party_identities):
        if (
            not isinstance(raw_party, dict)
            or raw_party.get("entityId") != entity_id
            or raw_party.get("state") != "resolved"
            or not isinstance(raw_party.get("party"), dict)
            or raw_party["party"].get("id") != entity_id
        ):
            return empty
        try:
            resolved_parties.append(Experience360ActorParty.model_validate(raw_party["party"]))
        except (TypeError, ValueError):
            return empty
    if resolved_parties[1].kind != "agent":
        return empty

    records_by_id: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        record_id = record.get("delegationId")
        if isinstance(record_id, str) and record_id:
            records_by_id.setdefault(record_id, []).append(record)
    edge_records: list[dict[str, Any]] = []
    record_evidence: list[EvidenceRef] = []
    for delegation_id in delegation_ids:
        matching_records = records_by_id.get(delegation_id, [])
        if len(matching_records) != 1:
            return empty
        record = matching_records[0]
        if (
            record.get("recordState") == "conflicted"
            or record.get("authorizationDecision") != "unknown"
        ):
            return empty
        try:
            evidence_ref = EvidenceRef.model_validate(record.get("evidenceRef"))
        except Exception:  # noqa: BLE001 - malformed repository evidence fails closed
            return empty
        if evidence_ref.source != "delegations" or evidence_ref.id != delegation_id:
            return empty
        matching_claims = [
            claim for claim in claims if getattr(claim, "id", None) == f"delegation.{delegation_id}"
        ]
        if len(matching_claims) != 1:
            return empty
        record_claim = matching_claims[0]
        if (
            record_claim.kind != "agent_delegation_record"
            or getattr(record_claim.claimState, "value", record_claim.claimState) != "observed"
            or record_claim.subject != subject
            or not any(
                ref.source == "delegations" and ref.id == delegation_id
                for ref in record_claim.evidenceRefs
            )
        ):
            return empty
        edge_records.append(record)
        record_evidence.append(evidence_ref)

    # Prove that each stored edge points to the exact resolved party IDs in
    # the path, including both sides of the shared intermediate Agent.
    expected_party_edges = (
        (delegation_ids[0], "grantor", party_ids[0]),
        (delegation_ids[0], "grantee", party_ids[1]),
        (delegation_ids[1], "grantor", party_ids[1]),
        (delegation_ids[1], "grantee", party_ids[2]),
    )
    party_evidence_by_edge: dict[tuple[str, str], list[EvidenceRef]] = {}
    for edge_id, side, party_id in expected_party_edges:
        record = edge_records[delegation_ids.index(edge_id)]
        field = "grantorEntityId" if side == "grantor" else "granteeEntityId"
        if record.get(field) != party_id:
            return empty
        matching_claims = [
            claim
            for claim in claims
            if getattr(claim, "id", None) == f"delegation_party.{edge_id}.{side}"
        ]
        if len(matching_claims) != 1:
            return empty
        party_claim = matching_claims[0]
        if (
            party_claim.kind != "canonically_resolved_delegation_party"
            or getattr(party_claim.claimState, "value", party_claim.claimState) != "resolved"
            or party_claim.subject != subject
            or not {"delegation_chain", "actor_attribution"}.issubset(
                set(party_claim.domainSlotIds or [])
            )
        ):
            return empty
        refs = list(party_claim.evidenceRefs)
        if not any(ref.source == "delegations" and ref.id == edge_id for ref in refs):
            return empty
        if not any(
            ref.source == "entities" and ref.type == "entity" and ref.id == party_id
            for ref in refs
        ):
            return empty
        party_evidence_by_edge[(edge_id, side)] = refs

    try:
        path_refs = [EvidenceRef.model_validate(ref) for ref in path.get("evidenceRefs", [])]
    except Exception:  # noqa: BLE001 - malformed path provenance fails closed
        return empty
    path_ref_keys = {(ref.source, ref.id) for ref in path_refs}
    required_path_refs = {
        (ref.source, ref.id)
        for refs in party_evidence_by_edge.values()
        for ref in refs
    }
    required_path_refs.update((ref.source, ref.id) for ref in record_evidence)
    if not required_path_refs.issubset(path_ref_keys):
        return empty

    typed_edges: list[Experience360Delegation] = []
    for index, record in enumerate(edge_records):
        start = record.get("startsAt")
        end = record.get("endsAt")
        scope = record.get("scope")
        if (
            not isinstance(start, str)
            or not _has_timezone(start)
            or (end is not None and (not isinstance(end, str) or not _has_timezone(end)))
            or not isinstance(scope, dict)
            or not isinstance(scope.get("actions"), list)
            or not isinstance(scope.get("resources"), list)
        ):
            return empty
        actions = scope["actions"]
        resources = scope["resources"]
        if any(not isinstance(value, str) or not value.strip() for value in actions + resources):
            return empty
        scope_values = [*(f"action:{value}" for value in actions), *(f"resource:{value}" for value in resources)]
        if not scope_values or len(scope_values) != len(set(scope_values)):
            return empty
        delegation_id = delegation_ids[index]
        state = record.get("recordState")
        if state not in {"active_as_reported_by_repository", "not_evaluated"}:
            return empty
        if state == "active_as_reported_by_repository" and record.get("revokedAt") is not None:
            return empty
        edge_refs = [record_evidence[index]]
        edge_refs.extend(party_evidence_by_edge[(delegation_id, side)])
        unique_edge_refs = {
            (ref.source, ref.id): ref for ref in edge_refs
        }
        try:
            typed_edges.append(
                Experience360Delegation(
                    id=delegation_id,
                    tenantId=tenant_id,
                    delegator=resolved_parties[index],
                    delegatee=resolved_parties[index + 1],
                    scope=scope_values,
                    validFrom=start,
                    validUntil=end,
                    status=(
                        "granted"
                        if state == "active_as_reported_by_repository"
                        else "unknown"
                    ),
                    evidenceRefs=list(unique_edge_refs.values()),
                )
            )
        except (TypeError, ValueError):
            return empty

    return typed_edges, resolved_parties[0], resolved_parties[-1]


def _has_timezone(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _merge_identity360_authority_result(
    frame: Experience360Frame,
    identity_result: Any,
    *,
    readable_slot_ids: set[str],
    slot_definitions: Mapping[str, Any],
) -> Experience360Frame:
    """Attach direct identity-authority evidence to permitted Identity360 slots."""

    if (
        identity_result.tenant_id != frame.tenantId
        or identity_result.subject_kind != frame.subject.kind
        or identity_result.subject_id != frame.subject.id
    ):
        raise ProjectionError(
            "Identity360 authority result scope does not match the frame request",
            context={"surfaceId": frame.surfaceId},
        )
    direct_slots = {slot.id: slot for slot in identity_result.slots}
    merged_slots = []
    for slot in frame.slots:
        direct = direct_slots.get(slot.id)
        definition = slot_definitions.get(slot.id)
        if (
            direct is None
            or slot.id not in readable_slot_ids
            or slot.policyDisposition.state not in {"allowed", "not_applicable"}
            or slot.id == "actor_and_agent_binding"
        ):
            merged_slots.append(slot)
            continue

        direct_state = direct.state
        if direct_state == "truncated":
            provenance_state = "degraded"
        elif direct_state == "partial":
            # The provider returned usable source evidence, while the frame
            # slot retains the broader partial-completeness state.
            provenance_state = "available"
        elif direct_state in {
            "available",
            "empty",
            "missing",
            "degraded",
            "not_applicable",
            "unknown",
            "suppressed",
            "stale",
        }:
            provenance_state = direct_state
        else:
            provenance_state = "unknown"
        canonical_authorities = (
            list(definition.get("canonicalAuthorityRefs") or [])
            if isinstance(definition, Mapping)
            else []
        )
        direct_evidence = list(direct.evidence_refs)
        provenance = Experience360ProjectionProvenance(
            tenantId=frame.tenantId,
            sourceState=provenance_state,
            generatedAt=identity_result.generated_at,
            sourceKind="authority",
            evidenceRefs=direct_evidence,
            claimOrigin="canonical_authority" if direct_evidence else "unknown",
            canonicalAuthorityRefs=canonical_authorities,
        )
        payload = {
            "state": direct.state,
            "content": (
                direct.content if direct_state not in {"unknown", "suppressed", "missing"} else None
            ),
            "reason": direct.reason,
            "truncated": direct.truncated,
        }
        content = (
            dict(slot.content)
            if isinstance(slot.content, dict)
            else {"projectionContent": slot.content}
            if slot.content is not None
            else {}
        )
        evidence_refs = {(ref.source, ref.id): ref for ref in slot.evidenceRefs}
        evidence_refs.update({(ref.source, ref.id): ref for ref in direct_evidence})
        state = slot.state
        useful_direct_states = {
            "available",
            "empty",
            "partial",
            "degraded",
            "truncated",
            "suppressed",
        }
        if state in {"missing", "unknown", "unavailable"} and direct_state in useful_direct_states:
            state = direct_state
        if direct_state not in {"unknown", "suppressed", "missing"} or slot.content is not None:
            content["identityAuthorityRead"] = payload
        if state in {"available", "partial", "degraded"} and not (
            evidence_refs or any(item.evidenceRefs for item in slot.provenance)
        ):
            state = "unknown" if state == "available" else "degraded"
            content = {}
        if state in {"unknown", "suppressed", "missing", "unavailable"}:
            content = {}
        reason_codes = set(slot.reasonCodes)
        if direct.reason:
            reason_codes.add(direct.reason)
        if direct_state in {"available", "empty", "partial", "degraded", "truncated"}:
            reason_codes.add("identity360_direct_freshness_threshold_unknown")
        freshness = Experience360Freshness(
            state="unknown",
            sourceAsOf=(
                direct.content.get("freshness", {}).get("observedAt")
                if isinstance(direct.content, dict)
                and isinstance(direct.content.get("freshness"), dict)
                else None
            ),
            evaluatedAt=identity_result.generated_at,
            ageSeconds=(
                direct.content.get("freshness", {}).get("ageSeconds")
                if isinstance(direct.content, dict)
                and isinstance(direct.content.get("freshness"), dict)
                else None
            ),
        )
        merged_slots.append(
            slot.model_copy(
                update={
                    "state": state,
                    "content": content or None,
                    "provenance": [*slot.provenance, provenance],
                    "evidenceRefs": list(evidence_refs.values()),
                    "freshness": freshness,
                    "reasonCodes": sorted(reason_codes),
                    "limitations": sorted(set([*slot.limitations, *identity_result.warnings])),
                }
            )
        )

    merged_state = _aggregate_frame_state(merged_slots)
    frame_freshness = _aggregate_freshness(merged_slots, frame.generatedAt)
    frame_quality = _aggregate_quality(merged_slots)
    warnings = sorted(set([*frame.warnings, *identity_result.warnings]))
    if any(
        "identity360_direct_freshness_threshold_unknown" in slot.reasonCodes
        for slot in merged_slots
    ):
        warnings.append("identity360_direct_freshness_threshold_unknown")
        warnings = sorted(set(warnings))
    degradation = frame.degradation
    if merged_state not in {"ready", "empty"} and (
        degradation is None or degradation.level == "none"
    ):
        degradation = ProjectionDegradation(
            level="partial" if merged_state == "partial" else "full",
            reasons=sorted(set([*(degradation.reasons if degradation else []), *warnings])),
        )
    return Experience360Frame.model_validate(
        {
            **frame.model_dump(mode="python"),
            "state": merged_state,
            "slots": merged_slots,
            "freshness": frame_freshness,
            "quality": frame_quality,
            "warnings": warnings,
            "degradation": degradation,
        }
    )


def _is_readable(disposition: Experience360PolicyDisposition) -> bool:
    # The current provider contract cannot constrain reads to selected fields
    # or prove claim dependencies after redaction. A redacted slot is therefore
    # suppressed before any projection is executed.
    return disposition.state in {"allowed", "not_applicable"}


def _unavailable_result(
    projection_id: str,
    request: Experience360FrameRequest,
    section_ids: set[str],
    generated_at: str,
    reason: str,
) -> ProjectionResult:
    return ProjectionResult(
        projectionId=projection_id,
        tenantId=request.tenantId,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            ProjectionSection(id=section_id, state="unknown") for section_id in sorted(section_ids)
        ],
        claims=[],
        dependencyState=[],
        generatedAt=generated_at,
        degradedReasons=[reason],
        degradation=ProjectionDegradation(level="full", reasons=[reason]),
    )


__all__ = ["Experience360PolicyEvaluator", "build_experience360_frame"]
