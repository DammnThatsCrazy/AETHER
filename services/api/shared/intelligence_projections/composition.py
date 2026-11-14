"""Composition helpers for the product 360 frame contract.

The composer joins catalog-declared slots to already-authorized projection
results. It never resolves actors, evaluates grants, infers evidence, or writes
canonical state. Policy must be explicit for content to be returned, and each
available slot must retain evidence and projection lineage.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel

from shared.intelligence_projections import generated_registry as _generated_registry
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    Experience360ActorAttribution,
    Experience360Frame,
    Experience360FrameRequest,
    Experience360FrameSlot,
    Experience360Freshness,
    Experience360PolicyDisposition,
    Experience360ProjectionProvenance,
    Experience360Quality,
    Experience360SlotState,
    Experience360SurfaceId,
    EvidenceRef,
    ProjectionResult,
    SectionState,
)
from shared.intelligence_projections.errors import ProjectionError, ProjectionNotFound


PRODUCT_360_SURFACE_IDS: tuple[str, ...] = tuple(
    getattr(_generated_registry, "PRODUCT_360_SURFACE_IDS", ())
)
PRODUCT_360_SURFACE_DEFINITIONS: dict[str, dict[str, Any]] = getattr(
    _generated_registry, "PRODUCT_360_SURFACE_DEFINITIONS", {}
)
INTELLIGENCE_PROJECTION_DEFINITIONS: dict[str, dict[str, Any]] = getattr(
    _generated_registry, "INTELLIGENCE_PROJECTION_DEFINITIONS", {}
)
PRODUCT_360_SURFACE_CATALOG_VERSION: str = getattr(
    _generated_registry, "PRODUCT_360_SURFACE_CATALOG_VERSION", "0.1.0"
)
INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION: str = getattr(
    _generated_registry, "INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION", "1.0.0"
)

_EVIDENCE_TYPES = {
    "event",
    "entity",
    "relationship",
    "document",
    "transaction",
    "model_output",
    "annotation",
}
_SAFE_SLOT_STATES = {"available", "empty"}
_USEFUL_SLOT_STATES = {*_SAFE_SLOT_STATES, "partial"}
_UNAVAILABLE_STATES = {"missing", "unknown", "suppressed", "unavailable"}


def compose_experience360_frame(
    request: Experience360FrameRequest,
    projection_results: Iterable[ProjectionResult],
    *,
    freshness_by_slot: Optional[Mapping[str, Experience360Freshness]] = None,
    quality_by_slot: Optional[Mapping[str, Experience360Quality]] = None,
    policy_by_slot: Optional[Mapping[str, Experience360PolicyDisposition]] = None,
    frame_policy: Optional[Experience360PolicyDisposition] = None,
    actor_attribution: Optional[Experience360ActorAttribution] = None,
    actor_attribution_by_slot: Optional[Mapping[str, Experience360ActorAttribution]] = None,
    generated_at: Optional[str] = None,
) -> Experience360Frame:
    """Compose a tenant-scoped 360 frame from catalog-mapped projections.

    ``projection_results`` must already have passed provider execution,
    authorization, and any source-level policy checks. Slot policy dispositions
    are enforced here as a second, content-boundary check. RFC 6901 redaction
    paths are applied to that slot's assembled ``content`` before evidence refs
    are extracted, so a removed value cannot leak through its evidence payload.

    Projection claims enter a slot only when their ``domainSlotIds`` explicitly
    names that catalog slot. Sections enter only through the catalog's
    ``sectionIds`` binding. No implicit section/claim-to-slot guess is made.
    """

    definition = _surface_definition(request.surfaceId)
    supported_subject_kinds = definition.get("subjectKinds", [])
    if supported_subject_kinds and request.subject.kind not in supported_subject_kinds:
        raise ProjectionError(
            "360 surface does not support the requested subject kind",
            context={
                "surfaceId": request.surfaceId,
                "subjectKind": request.subject.kind,
            },
        )
    domain_slots = definition.get("domainSlots")
    if not isinstance(domain_slots, list) or not domain_slots:
        raise ProjectionError(
            "360 surface catalog has no domain slots",
            context={"surfaceId": request.surfaceId},
        )

    slot_by_id: dict[str, dict[str, Any]] = {}
    for slot in domain_slots:
        if not isinstance(slot, Mapping) or not isinstance(slot.get("id"), str):
            raise ProjectionError(
                "360 surface catalog contains an invalid domain slot",
                context={"surfaceId": request.surfaceId},
            )
        slot_id = slot["id"]
        if slot_id in slot_by_id:
            raise ProjectionError(
                "360 surface catalog contains duplicate domain slots",
                context={"surfaceId": request.surfaceId, "slotId": slot_id},
            )
        slot_by_id[slot_id] = dict(slot)

    requested_ids = (
        list(slot_by_id) if request.requestedSlotIds is None else request.requestedSlotIds
    )
    if len(requested_ids) != len(set(requested_ids)):
        raise ProjectionError(
            "360 frame request contains duplicate slot ids",
            context={"surfaceId": request.surfaceId},
        )
    unknown_slots = sorted(set(requested_ids) - set(slot_by_id))
    if unknown_slots:
        raise ProjectionError(
            "360 frame request names an unknown slot",
            context={"surfaceId": request.surfaceId, "slotIds": unknown_slots},
        )

    normalized_results = _normalize_results(projection_results)
    allowed_projection_ids = {
        str(binding.get("projectionId"))
        for slot_id in requested_ids
        for slot in [slot_by_id[slot_id]]
        for binding in slot.get("projectionBindings", [])
        if isinstance(binding, Mapping) and binding.get("projectionId")
    }
    unexpected_results = sorted(set(normalized_results) - allowed_projection_ids)
    if unexpected_results:
        raise ProjectionError(
            "projection result is not bound to a requested 360 slot",
            context={"surfaceId": request.surfaceId, "projectionIds": unexpected_results},
        )

    for result in normalized_results.values():
        if result.tenantId != request.tenantId:
            raise ProjectionError(
                "projection result tenant does not match 360 frame tenant",
                projection_id=result.projectionId,
                context={"surfaceId": request.surfaceId},
            )
        # ProjectionResult intentionally has no top-level subject field. Its
        # typed claims do, so enforce their exact subject binding here; section
        # payloads are trusted only as the result of the provider invocation
        # made for this frame request by frame_runtime.
        if any(claim.subject != request.subject for claim in result.claims):
            raise ProjectionError(
                "projection claim subject does not match 360 frame subject",
                projection_id=result.projectionId,
                context={"surfaceId": request.surfaceId},
            )
        if result.contractVersion != INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION:
            raise ProjectionError(
                "projection result contract version does not match the registry",
                projection_id=result.projectionId,
                context={"surfaceId": request.surfaceId},
                version=result.contractVersion,
            )

    if actor_attribution is not None and actor_attribution.tenantId != request.tenantId:
        raise ProjectionError(
            "actor attribution tenant does not match 360 frame tenant",
            context={"surfaceId": request.surfaceId},
        )

    generated_timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    frame_policy_model = _as_model(
        frame_policy, Experience360PolicyDisposition, default=Experience360PolicyDisposition()
    )
    if frame_policy_model.redactedFieldPaths:
        raise ProjectionError(
            "frame-level policy cannot carry slot redaction paths",
            context={"surfaceId": request.surfaceId},
        )

    per_slot_policy = policy_by_slot or {}
    per_slot_freshness = freshness_by_slot or {}
    per_slot_quality = quality_by_slot or {}
    per_slot_attribution = actor_attribution_by_slot or {}
    unknown_metadata_slots = sorted(
        (
            set(per_slot_policy)
            | set(per_slot_freshness)
            | set(per_slot_quality)
            | set(per_slot_attribution)
        )
        - set(requested_ids)
    )
    if unknown_metadata_slots:
        raise ProjectionError(
            "360 frame metadata refers to an unrequested slot",
            context={"surfaceId": request.surfaceId, "slotIds": unknown_metadata_slots},
        )

    for attribution in per_slot_attribution.values():
        if attribution.tenantId != request.tenantId:
            raise ProjectionError(
                "slot actor attribution tenant does not match 360 frame tenant",
                context={"surfaceId": request.surfaceId},
            )

    frame_slots: list[Experience360FrameSlot] = []
    surface_warnings: list[str] = []
    missing_projection_ids: set[str] = set()
    for slot_id in requested_ids:
        slot_definition = slot_by_id[slot_id]
        result, reasons, missing = _compose_slot_content(
            slot_id=slot_id,
            slot_definition=slot_definition,
            results=normalized_results,
            include_evidence=request.includeEvidence,
            tenant_id=request.tenantId,
            requested_as_of=request.asOf,
            subject_kind=request.subject.kind,
            requires_exact_claim=(
                definition.get("contractStatus") == "source_aligned"
                and slot_definition.get("requirement") == "required"
            ),
        )
        missing_projection_ids.update(missing)

        # A frame-level deny/unknown is an outer authorization gate. A slot
        # disposition can refine an allowed frame, but cannot override that
        # gate and reopen content.
        if frame_policy_model.state in {"denied", "unknown", "redacted"}:
            policy_model = frame_policy_model
        else:
            policy_model = _as_model(
                per_slot_policy.get(slot_id),
                Experience360PolicyDisposition,
                default=frame_policy_model,
            )
        slot_actor = per_slot_attribution.get(slot_id, actor_attribution)
        freshness_model = _as_model(
            per_slot_freshness.get(slot_id),
            Experience360Freshness,
            default=_freshness_from_sources(result["sourceStates"], result["asOf"]),
        )
        quality_model = _as_model(
            per_slot_quality.get(slot_id),
            Experience360Quality,
            default=Experience360Quality(
                state=("not_applicable" if result["state"] == "empty" else "unknown"),
                reasonCodes=([] if result["state"] == "empty" else ["quality_not_evaluated"]),
            ),
        )

        slot_state: Experience360SlotState = result["state"]
        slot_content = result["content"]
        provenance = result["provenance"]
        evidence_refs = result["evidenceRefs"]
        claims = result["claims"]

        # A missing/unknown/denied policy is a closed gate. ``not_applicable``
        # is accepted only when explicitly returned by the policy authority.
        if policy_model.state in {"denied", "unknown"}:
            slot_state = "suppressed"
            slot_content = None
            provenance = []
            evidence_refs = []
            claims = []
            slot_actor = None
            freshness_model = Experience360Freshness(state="unknown")
            quality_model = Experience360Quality(state="unknown", reasonCodes=["policy_suppressed"])
            reasons.append(
                "policy_denied" if policy_model.state == "denied" else "policy_not_evaluated"
            )
        elif policy_model.state == "redacted":
            # Without provider-level field authorization and field-to-claim
            # dependency metadata, partial JSON redaction can leave a derived
            # claim or duplicate summary exposing the removed value. Suppress
            # the whole slot and retain only the policy's denied field paths.
            slot_state = "suppressed"
            slot_content = None
            provenance = []
            evidence_refs = []
            claims = []
            slot_actor = None
            freshness_model = Experience360Freshness(state="unknown")
            quality_model = Experience360Quality(state="unknown", reasonCodes=["policy_suppressed"])
            reasons.append("policy_redacted_slot_suppressed")

        if slot_state == "available" and (
            slot_content is None or not provenance or not evidence_refs
        ):
            slot_state = "unknown"
            slot_content = None
            provenance = []
            claims = []
            evidence_refs = []
            reasons.append("available_content_missing_evidence_or_provenance")

        required_frame_metadata = set(slot_definition.get("requiredFrameMetadata", []))
        explicit_slot_actor = per_slot_attribution.get(slot_id)
        missing_frame_metadata: list[str] = []
        if "slotActorAttribution" in required_frame_metadata and (
            explicit_slot_actor is None or policy_model.state == "redacted"
        ):
            missing_frame_metadata.append("slotActorAttribution")
        if "slotAuthorityDecision" in required_frame_metadata and (
            explicit_slot_actor is None
            or explicit_slot_actor.authorityDecision is None
            or policy_model.state == "redacted"
        ):
            missing_frame_metadata.append("slotAuthorityDecision")
        if slot_state == "available" and missing_frame_metadata:
            slot_state = "unknown"
            slot_content = None
            provenance = []
            evidence_refs = []
            claims = []
            reasons.append("required_slot_metadata_missing")

        freshness_policy = definition.get("freshnessPolicy", {})
        if (
            slot_state in {"available", "degraded"}
            and freshness_model.state == "unknown"
            and isinstance(freshness_policy, Mapping)
        ):
            if freshness_policy.get("maxAgeSeconds") is None:
                reasons.append("freshness_threshold_not_configured")
            elif freshness_model.sourceAsOf is None:
                reasons.append("freshness_source_timestamp_missing")
            else:
                reasons.append("freshness_not_evaluated")

        # The catalog is reconstructed from the previously reviewed SSOT and
        # awaits clause-by-clause source alignment. Surface this as metadata.
        if definition.get("contractStatus") == "reconstructed_pending_source_alignment":
            surface_warnings.append("surface_contract_pending_source_alignment")

        frame_slots.append(
            Experience360FrameSlot(
                id=slot_id,
                requirement=slot_definition.get("requirement", "required"),
                description=slot_definition.get("description"),
                canonicalAuthorityRefs=list(slot_definition.get("canonicalAuthorityRefs") or []),
                state=slot_state,
                content=slot_content,
                claims=claims,
                provenance=provenance,
                evidenceRefs=evidence_refs,
                freshness=freshness_model,
                quality=quality_model,
                policyDisposition=policy_model,
                actorAttribution=(
                    slot_actor if policy_model.state in {"allowed", "not_applicable"} else None
                ),
                limitations=sorted(set(result["limitations"] + reasons)),
                reasonCodes=sorted(set(reasons)),
            )
        )

    frame_state = _aggregate_frame_state(frame_slots)
    frame_freshness = _aggregate_freshness(frame_slots, generated_timestamp)
    frame_quality = _aggregate_quality(frame_slots)
    frame_policy_disposition = _aggregate_policy(
        frame_slots, frame_policy_model, generated_timestamp
    )
    degraded_reasons = _degradation_reasons(frame_slots)
    degradation_level = (
        "none"
        if frame_state in {"ready", "empty"}
        else "partial"
        if frame_state == "partial"
        else "full"
    )

    result_as_ofs = {value.asOf for value in normalized_results.values() if value.asOf is not None}
    frame_as_of = request.asOf
    if frame_as_of is None:
        frame_as_of = _single_equivalent_instant(result_as_ofs)
        if result_as_ofs and frame_as_of is None:
            surface_warnings.append("projection_results_use_different_as_of_anchors")

    if missing_projection_ids:
        surface_warnings.append("one_or_more_projection_results_missing")
    if any(
        reason == "section_binding_unresolved"
        for slot in frame_slots
        for reason in slot.reasonCodes
    ):
        surface_warnings.append("one_or_more_slot_section_bindings_unresolved")

    return Experience360Frame(
        surfaceId=request.surfaceId,
        tenantId=request.tenantId,
        subject=request.subject,
        surfaceCatalogVersion=PRODUCT_360_SURFACE_CATALOG_VERSION,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        generatedAt=generated_timestamp,
        asOf=frame_as_of,
        state=frame_state,
        slots=frame_slots,
        freshness=frame_freshness,
        quality=frame_quality,
        policyDisposition=frame_policy_disposition,
        actorAttribution=(
            actor_attribution if frame_policy_model.state in {"allowed", "not_applicable"} else None
        ),
        degradation={
            "level": degradation_level,
            "reasons": degraded_reasons,
            "missingDependencies": sorted(missing_projection_ids) or None,
        }
        if degradation_level != "none"
        else {"level": "none", "reasons": []},
        warnings=sorted(set(surface_warnings)),
    )


def _surface_definition(surface_id: Experience360SurfaceId) -> dict[str, Any]:
    if surface_id not in PRODUCT_360_SURFACE_IDS:
        raise ProjectionNotFound("unknown product 360 surface", context={"surfaceId": surface_id})
    definition = PRODUCT_360_SURFACE_DEFINITIONS.get(surface_id)
    if not isinstance(definition, dict):
        raise ProjectionError(
            "product 360 surface catalog is not generated or is malformed",
            context={"surfaceId": surface_id},
        )
    return definition


def _normalize_results(
    projection_results: Iterable[ProjectionResult],
) -> dict[str, ProjectionResult]:
    results: dict[str, ProjectionResult] = {}
    for result in projection_results:
        projection_id = result.projectionId
        if projection_id in results:
            raise ProjectionError(
                "duplicate projection result supplied to 360 composer",
                projection_id=projection_id,
            )
        results[projection_id] = result
    return results


def _compose_slot_content(
    *,
    slot_id: str,
    slot_definition: dict[str, Any],
    results: dict[str, ProjectionResult],
    include_evidence: bool,
    tenant_id: str,
    requested_as_of: Optional[str],
    subject_kind: str,
    requires_exact_claim: bool = False,
) -> tuple[dict[str, Any], list[str], set[str]]:
    reasons: list[str] = []
    missing_projection_ids: set[str] = set()
    source_states: list[SectionState] = []
    source_as_ofs: set[str] = set()
    temporal_anchor_invalid = False
    incomplete_bound_source = False
    projection_failure_for_binding = False
    source_policy_suppressed = False
    source_conflicted = False
    unsupported_binding_subject = False
    claim_projection_ids: set[str] = set()
    section_payloads: list[dict[str, Any]] = []
    claims: list[ClaimEnvelope] = []
    provenance: list[Experience360ProjectionProvenance] = []
    evidence_refs: list[EvidenceRef] = []
    bindings = slot_definition.get("projectionBindings", [])
    if slot_definition.get("unboundCanonicalAuthorityRefs"):
        incomplete_bound_source = True
        reasons.append("slot_canonical_authority_gap")
        authority_gap_reason = slot_definition.get("authorityGapReason")
        if isinstance(authority_gap_reason, str) and authority_gap_reason:
            reasons.append(authority_gap_reason)
    partial_implementation_reason = slot_definition.get("partialImplementationReason")
    if isinstance(partial_implementation_reason, str) and partial_implementation_reason:
        incomplete_bound_source = True
        reasons.append("slot_partial_implementation")
        reasons.append(partial_implementation_reason)
    if not isinstance(bindings, list):
        return (
            _slot_result("unknown", reasons + ["invalid_slot_projection_bindings"]),
            reasons,
            missing_projection_ids,
        )
    if not bindings:
        unbound_reason = slot_definition.get("unboundReason")
        if isinstance(unbound_reason, str) and unbound_reason.strip():
            return (
                _slot_result(
                    "unknown",
                    reasons + ["slot_provider_not_connected", unbound_reason.strip()],
                ),
                reasons + ["slot_provider_not_connected", unbound_reason.strip()],
                missing_projection_ids,
            )
        return (
            _slot_result("missing", reasons + ["slot_has_no_projection_binding"]),
            reasons,
            missing_projection_ids,
        )

    required_claim_projection_ids = slot_definition.get("requiredClaimProjectionIds", [])
    if (
        not isinstance(required_claim_projection_ids, (list, tuple))
        or not all(isinstance(value, str) and value for value in required_claim_projection_ids)
        or len(set(required_claim_projection_ids)) != len(required_claim_projection_ids)
    ):
        reason = "invalid_required_claim_projection_ids"
        return _slot_result("unknown", [*reasons, reason]), [*reasons, reason], missing_projection_ids
    bound_projection_ids = {
        binding.get("projectionId")
        for binding in bindings
        if isinstance(binding, Mapping) and isinstance(binding.get("projectionId"), str)
    }
    if not set(required_claim_projection_ids).issubset(bound_projection_ids):
        reason = "required_claim_projection_not_bound"
        return _slot_result("unknown", [*reasons, reason]), [*reasons, reason], missing_projection_ids

    for binding in bindings:
        if not isinstance(binding, Mapping):
            reasons.append("invalid_projection_binding")
            continue
        projection_id = binding.get("projectionId")
        if not isinstance(projection_id, str):
            reasons.append("invalid_projection_binding")
            continue
        supported_subject_kinds = binding.get("subjectKinds")
        if not isinstance(supported_subject_kinds, (list, tuple)) or not all(
            isinstance(kind, str) for kind in supported_subject_kinds
        ):
            reasons.append("invalid_projection_binding_subject_kinds")
            unsupported_binding_subject = True
            continue
        if subject_kind not in supported_subject_kinds:
            reasons.append("projection_binding_subject_kind_unsupported")
            unsupported_binding_subject = True
            # Subject-specific providers are alternatives within a slot. A
            # provider that cannot serve this subject is not a missing source;
            # the applicable bindings determine whether the slot is complete.
            continue
        projection_definition = INTELLIGENCE_PROJECTION_DEFINITIONS.get(projection_id, {})
        slot_authorities = {
            value
            for value in slot_definition.get("canonicalAuthorityRefs", [])
            if isinstance(value, str)
        }
        projection_authorities = {
            value
            for value in projection_definition.get("canonicalAuthorities", [])
            if isinstance(value, str)
        }
        # Provenance names only authorities declared by both contracts. A slot
        # can combine several providers, so copying the slot's whole authority
        # list onto every provider would attribute sibling-owned facts to the
        # wrong source. An empty intersection is a contract gap: retain any
        # evidenced content as degraded, but do not claim unaligned authority
        # lineage.
        binding_authorities = sorted(slot_authorities & projection_authorities)
        if not binding_authorities:
            reasons.append("projection_authority_unmapped_to_slot")
            incomplete_bound_source = True
        result = results.get(projection_id)
        if result is None:
            missing_projection_ids.add(projection_id)
            reasons.append("projection_result_missing")
            continue
        if result.asOf:
            source_as_ofs.add(result.asOf)
        if requested_as_of is not None:
            if result.asOf is None:
                reasons.append("source_as_of_unreported")
                temporal_anchor_invalid = True
            elif not _same_temporal_instant(requested_as_of, result.asOf):
                reasons.append("source_as_of_mismatch")
                temporal_anchor_invalid = True

        section_ids = binding.get("sectionIds", [])
        if not isinstance(section_ids, (list, tuple)) or not all(
            isinstance(value, str) for value in section_ids
        ):
            reasons.append("invalid_projection_section_binding")
            continue
        if not section_ids:
            reasons.append("section_binding_unresolved")
            continue

        section_map = {section.id: section for section in result.sections}
        binding_states: list[SectionState] = []
        for section_id in section_ids:
            section = section_map.get(section_id)
            if section is None:
                source_states.append("missing")
                binding_states.append("missing")
                reasons.append("bound_projection_section_missing")
                continue
            source_states.append(section.state)
            binding_states.append(section.state)
            section_authorities = binding_authorities
            if section.canonicalAuthorityRefs is not None:
                requested_authorities = section.canonicalAuthorityRefs
                if (
                    not requested_authorities
                    or len(set(requested_authorities)) != len(requested_authorities)
                    or not set(requested_authorities).issubset(slot_authorities)
                    or not set(requested_authorities).issubset(projection_authorities)
                ):
                    reasons.append("projection_section_authority_refs_invalid")
                    incomplete_bound_source = True
                    section_authorities = []
                else:
                    section_authorities = sorted(set(requested_authorities))
            if section.state == "suppressed":
                source_policy_suppressed = True
            if section.state == "conflicted":
                source_conflicted = True
            if section.state in {
                "missing",
                "unknown",
                "unavailable",
                "stale",
                "degraded",
            }:
                incomplete_bound_source = True
            section_evidence: list[EvidenceRef] = []
            if section.state == "available" and section.content is not None:
                section_payload = {
                    "projectionId": projection_id,
                    "sectionId": section_id,
                    "state": section.state,
                    "content": copy.deepcopy(section.content),
                    "warnings": list(section.warnings or []),
                }
                section_evidence = _collect_evidence_refs(section_payload["content"])
                section_payloads.append(section_payload)
                evidence_refs.extend(section_evidence)
            elif section.state == "available":
                reasons.append("available_section_content_missing")

            provenance.append(
                Experience360ProjectionProvenance(
                    tenantId=tenant_id,
                    projectionId=projection_id,
                    sourceKind="section",
                    sectionId=section_id,
                    sourceState=section.state,
                    generatedAt=result.generatedAt,
                    asOf=result.asOf,
                    digest=result.digest,
                    claimOrigin="unknown",
                    evidenceRefs=section_evidence,
                    claimStates=[],
                    canonicalAuthorityRefs=section_authorities,
                )
            )

        # Claims are copied only when the provider marks this exact slot.
        for claim in result.claims:
            if slot_id not in (claim.domainSlotIds or []):
                continue
            claims.append(claim)
            claim_projection_ids.add(projection_id)
            evidence_refs.extend(claim.evidenceRefs)
            provenance.append(
                Experience360ProjectionProvenance(
                    tenantId=tenant_id,
                    projectionId=projection_id,
                    sourceKind="claim",
                    claimId=claim.id,
                    sourceState="available",
                    generatedAt=result.generatedAt,
                    asOf=result.asOf,
                    digest=result.digest,
                    claimOrigin="unknown",
                    evidenceRefs=list(claim.evidenceRefs),
                    claimStates=[claim.claimState] if claim.claimState is not None else [],
                    canonicalAuthorityRefs=binding_authorities,
                )
            )

        # Engine degradation is projection-wide, while this composer is
        # slot-scoped. A partial sibling section must not erase or taint a
        # different, explicitly bound section that is available with evidence.
        # Use projection-level degradation only when this binding itself is
        # incomplete, or when the provider failed without returning any of its
        # bound sections.
        binding_is_incomplete = any(
            state not in {"available", "empty", "not_applicable"} for state in binding_states
        )
        provider_failed_without_bound_sections = bool(result.degradedReasons) and not binding_states
        full_projection_failure = (
            result.degradation is not None and result.degradation.level == "full"
        )
        if (
            binding_is_incomplete
            or provider_failed_without_bound_sections
            or full_projection_failure
        ):
            incomplete_bound_source = True
            if result.degradation is not None and result.degradation.level != "none":
                reasons.extend(result.degradation.reasons)
            if result.degradedReasons or full_projection_failure:
                reasons.append("projection_provider_degraded")
                projection_failure_for_binding = True

    evidence_refs = _unique_evidence_refs(evidence_refs)
    claims = _unique_claims(claims)

    distinct_instants: list[str] = []
    for value in source_as_ofs:
        if not any(_same_temporal_instant(value, known) for known in distinct_instants):
            distinct_instants.append(value)
    if len(distinct_instants) > 1:
        reasons.append("source_as_of_conflict")
        temporal_anchor_invalid = True

    if not include_evidence and (section_payloads or claims):
        reasons.append("evidence_not_requested_for_evidence_backed_content")
        return (
            {
                "state": "unknown",
                "content": None,
                "claims": [],
                "provenance": [],
                "evidenceRefs": [],
                "sourceStates": source_states,
                "asOf": _single_equivalent_instant(source_as_ofs),
                "limitations": reasons,
            },
            reasons,
            missing_projection_ids,
        )

    content = None
    if section_payloads or claims:
        content = {
            "sections": section_payloads,
            "claims": [
                claim.model_dump(mode="json", by_alias=True, exclude_none=True) for claim in claims
            ],
        }

    if temporal_anchor_invalid:
        slot_state = "unknown"
        content = None
        claims = []
        evidence_refs = []
    elif source_policy_suppressed:
        # A provider-level policy suppression is a closed slot boundary. Do
        # not let another binding re-expose an overlapping claim or value.
        slot_state = "suppressed"
        content = None
        claims = []
        evidence_refs = []
        provenance = []
        reasons.append("bound_source_policy_suppressed")
    elif source_conflicted:
        # Conflicting canonical evidence is not safe to combine into an
        # apparently coherent aggregate, even if another sibling has data.
        slot_state = "conflicted"
        content = None
        claims = []
        evidence_refs = []
        provenance = []
        reasons.append("bound_source_conflicted")
    elif content is not None and evidence_refs and requires_exact_claim and not claims:
        # An available generic section can contain real evidence for a
        # sibling capability. It does not prove this exact blueprint slot.
        # Required source-aligned slots need a provider claim explicitly
        # routed with domainSlotIds before exposing section content.
        slot_state = "unknown"
        content = None
        evidence_refs = []
        provenance = []
        reasons.append("exact_slot_claim_missing")
    elif content is not None and evidence_refs and (
        set(required_claim_projection_ids) - claim_projection_ids
    ):
        slot_state = "unknown"
        content = None
        claims = []
        evidence_refs = []
        provenance = []
        reasons.append("required_source_claim_missing")
    elif content is not None and evidence_refs:
        if incomplete_bound_source or missing_projection_ids:
            slot_state = "degraded"
            reasons.append("slot_contains_partial_evidence")
        else:
            slot_state = "available"
    elif source_states and all(state in {"empty", "not_applicable"} for state in source_states):
        slot_state = "empty"
        content = None
        claims = []
        evidence_refs = []
    elif "conflicted" in reasons:
        slot_state = "conflicted"
        content = None
    elif "stale" in source_states:
        slot_state = "stale"
        content = None
        claims = []
        evidence_refs = []
    elif "degraded" in source_states or projection_failure_for_binding:
        slot_state = "degraded"
        content = None
        claims = []
        evidence_refs = []
    elif "suppressed" in source_states:
        slot_state = "suppressed"
        content = None
        claims = []
        evidence_refs = []
    elif "unknown" in source_states or "section_binding_unresolved" in reasons:
        slot_state = "unknown"
        content = None
        claims = []
        evidence_refs = []
    elif unsupported_binding_subject:
        slot_state = "unknown"
        content = None
        claims = []
        evidence_refs = []
    elif content is not None and not evidence_refs:
        slot_state = "unknown"
        content = None
        claims = []
        reasons.append("slot_evidence_missing")
        evidence_refs = []
    elif "available" in source_states:
        slot_state = "unknown"
        content = None
        claims = []
        reasons.append("available_section_content_unavailable")
        evidence_refs = []
    elif any(
        code in reasons
        for code in {
            "invalid_projection_binding",
            "invalid_projection_section_binding",
            "invalid_slot_projection_bindings",
        }
    ):
        slot_state = "unknown"
        content = None
        claims = []
        evidence_refs = []
    elif source_states or missing_projection_ids:
        slot_state = "missing"
        content = None
        claims = []
        evidence_refs = []
    else:
        slot_state = "unavailable"
        content = None
        claims = []
        evidence_refs = []

    if slot_state == "available" and not evidence_refs:
        slot_state = "unknown"
        content = None
        claims = []
        provenance = []
        reasons.append("slot_evidence_missing")

    degraded_content_is_evidenced = (
        slot_state == "degraded" and content is not None and bool(evidence_refs)
    )
    if slot_state != "available" and not degraded_content_is_evidenced:
        claims = []
        evidence_refs = []
        if slot_state in _UNAVAILABLE_STATES:
            content = None

    return (
        {
            "state": slot_state,
            "content": content,
            "claims": claims,
            "provenance": (
                provenance if slot_state == "available" or degraded_content_is_evidenced else []
            ),
            "evidenceRefs": evidence_refs,
            "sourceStates": source_states,
            "asOf": _single_equivalent_instant(source_as_ofs),
            "limitations": reasons,
        },
        reasons,
        missing_projection_ids,
    )


def _slot_result(state: Experience360SlotState, reasons: list[str]) -> dict[str, Any]:
    return {
        "state": state,
        "content": None,
        "claims": [],
        "provenance": [],
        "evidenceRefs": [],
        "sourceStates": [],
        "asOf": None,
        "limitations": reasons,
    }


def _as_model(value: Any, model_type: type[BaseModel], *, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, model_type):
        return value
    if isinstance(value, Mapping):
        return model_type.model_validate(value)
    raise ProjectionError(
        "360 frame metadata has an invalid contract type",
        context={"model": model_type.__name__},
    )


def _freshness_from_sources(
    source_states: list[SectionState], source_as_of: Optional[str]
) -> Experience360Freshness:
    if "stale" in source_states:
        state = "stale"
    elif source_states and all(value in {"empty", "not_applicable"} for value in source_states):
        state = "not_applicable"
    elif source_states and all(value == "not_applicable" for value in source_states):
        state = "not_applicable"
    elif not source_states:
        state = "missing"
    else:
        state = "unknown"
    return Experience360Freshness(state=state, sourceAsOf=source_as_of)


def _aggregate_frame_state(slots: list[Experience360FrameSlot]) -> str:
    if not slots:
        return "missing"
    required_slots = [slot for slot in slots if slot.requirement == "required"]
    optional_slots = [slot for slot in slots if slot.requirement == "optional"]
    evaluated_slots = required_slots or slots
    states = [slot.state for slot in evaluated_slots]
    if "conflicted" in states:
        return "conflicted"
    useful = sum(
        slot.state in _USEFUL_SLOT_STATES
        or (slot.state == "degraded" and slot.content is not None)
        for slot in evaluated_slots
    )
    incomplete = any(
        slot.state not in _SAFE_SLOT_STATES
        or bool(slot.reasonCodes)
        or (
            slot.state == "available"
            and slot.freshness is not None
            and slot.freshness.state not in {"fresh", "not_applicable"}
        )
        or (
            slot.state == "available"
            and slot.quality is not None
            and slot.quality.state not in {"adequate", "not_applicable"}
        )
        or (slot.state == "available" and slot.policyDisposition.state == "redacted")
        for slot in evaluated_slots
    )
    if useful and incomplete:
        return "partial"
    if useful == len(states):
        all_required_empty = bool(states) and all(state == "empty" for state in states)
        optional_has_content = any(slot.state == "available" for slot in optional_slots)
        return "empty" if all_required_empty and not optional_has_content else "ready"
    if states and all(state == "suppressed" for state in states):
        return "suppressed"
    if "stale" in states and useful == 0:
        return "stale"
    if "degraded" in states and useful == 0:
        return "degraded"
    if states and all(state == "unavailable" for state in states):
        return "unavailable"
    if "missing" in states:
        return "missing"
    return "unknown"


def _aggregate_freshness(
    slots: list[Experience360FrameSlot], evaluated_at: str
) -> Experience360Freshness:
    required_slots = [slot for slot in slots if slot.requirement == "required"]
    relevant_slots = [
        slot
        for slot in slots
        if slot.requirement == "required"
        or slot.state == "available"
        or (slot.state == "degraded" and slot.content is not None)
    ]
    if (
        required_slots
        and all(slot.state == "empty" for slot in required_slots)
        and not any(slot.state == "available" for slot in slots)
    ):
        return Experience360Freshness(state="not_applicable", evaluatedAt=evaluated_at)
    values = [slot.freshness for slot in relevant_slots if slot.freshness is not None]
    states = [value.state for value in values]
    if "stale" in states:
        state = "stale"
    elif states and all(value == "fresh" for value in states):
        state = "fresh"
    elif states and all(value == "not_applicable" for value in states):
        state = "not_applicable"
    elif states and all(value == "missing" for value in states):
        state = "missing"
    elif states and all(value == "unavailable" for value in states):
        state = "unavailable"
    else:
        state = "unknown"
    as_ofs = {value.sourceAsOf for value in values if value.sourceAsOf is not None}
    return Experience360Freshness(
        state=state,
        sourceAsOf=_single_or_none(as_ofs),
        evaluatedAt=evaluated_at,
    )


def _aggregate_quality(slots: list[Experience360FrameSlot]) -> Experience360Quality:
    required_slots = [slot for slot in slots if slot.requirement == "required"]
    relevant_slots = [
        slot
        for slot in slots
        if slot.requirement == "required"
        or slot.state == "available"
        or (slot.state == "degraded" and slot.content is not None)
    ]
    if (
        required_slots
        and all(slot.state == "empty" for slot in required_slots)
        and not any(slot.state == "available" for slot in slots)
    ):
        return Experience360Quality(state="not_applicable")
    values = [slot.quality for slot in relevant_slots if slot.quality is not None]
    states = [value.state for value in values]
    if "conflicted" in states:
        state = "conflicted"
    elif "insufficient" in states:
        state = "insufficient"
    elif "partial" in states:
        state = "partial"
    elif states and all(value == "adequate" for value in states):
        state = "adequate"
    elif states and all(value == "not_applicable" for value in states):
        state = "not_applicable"
    else:
        state = "unknown"
    return Experience360Quality(
        state=state,
        confidence=None,
        evidenceRefs=_unique_evidence_refs([ref for value in values for ref in value.evidenceRefs]),
        reasonCodes=sorted({code for value in values for code in value.reasonCodes}),
    )


def _aggregate_policy(
    slots: list[Experience360FrameSlot],
    frame_policy: Experience360PolicyDisposition,
    evaluated_at: str,
) -> Experience360PolicyDisposition:
    required_slots = [slot for slot in slots if slot.requirement == "required"]
    policy_slots = required_slots or slots
    states = [slot.policyDisposition.state for slot in policy_slots]
    if "denied" in states:
        state = "denied"
    elif "unknown" in states:
        state = "unknown"
    elif "redacted" in states:
        state = "redacted"
    elif states and all(value == "not_applicable" for value in states):
        state = "not_applicable"
    else:
        state = "allowed"
    policy_ids = set(frame_policy.policyIds)
    reason_codes = set(frame_policy.reasonCodes)
    evidence_refs = list(frame_policy.evidenceRefs)
    for slot in slots:
        policy_ids.update(slot.policyDisposition.policyIds)
        reason_codes.update(slot.policyDisposition.reasonCodes)
        evidence_refs.extend(slot.policyDisposition.evidenceRefs)
    return Experience360PolicyDisposition(
        state=state,
        policyIds=sorted(policy_ids),
        redactedFieldPaths=[],
        reasonCodes=sorted(reason_codes),
        evaluatedAt=frame_policy.evaluatedAt or evaluated_at,
        evidenceRefs=_unique_evidence_refs(evidence_refs),
    )


def _degradation_reasons(slots: list[Experience360FrameSlot]) -> list[str]:
    return sorted(
        {
            f"{slot.id}:{reason}"
            for slot in slots
            for reason in slot.reasonCodes
            if reason not in {"surface_contract_pending_source_alignment"}
        }
    )


def _collect_evidence_refs(value: Any) -> list[EvidenceRef]:
    found: list[EvidenceRef] = []

    def visit(item: Any) -> None:
        if isinstance(item, EvidenceRef):
            found.append(item)
            return
        if isinstance(item, BaseModel):
            visit(item.model_dump(mode="python", by_alias=True, exclude_none=True))
            return
        if isinstance(item, Mapping):
            if (
                isinstance(item.get("id"), str)
                and item.get("type") in _EVIDENCE_TYPES
                and isinstance(item.get("source"), str)
            ):
                try:
                    found.append(EvidenceRef.model_validate(item))
                except Exception:  # a malformed ref is not accepted as evidence
                    pass
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return _unique_evidence_refs(found)


def _unique_claims(claims: list[ClaimEnvelope]) -> list[ClaimEnvelope]:
    seen: set[tuple[str, str]] = set()
    result: list[ClaimEnvelope] = []
    for claim in claims:
        key = (claim.id, claim.kind)
        if key not in seen:
            seen.add(key)
            result.append(claim)
    return result


def _unique_evidence_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[Any, ...]] = set()
    result: list[EvidenceRef] = []
    for ref in refs:
        key = _evidence_key(ref)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


def _evidence_key(ref: EvidenceRef) -> tuple[Any, ...]:
    return (ref.id, ref.type, ref.source, ref.observedAt, ref.uri)


def _single_or_none(values: set[str]) -> Optional[str]:
    return next(iter(values)) if len(values) == 1 else None


def _single_equivalent_instant(values: set[str]) -> Optional[str]:
    """Return one timestamp when every value denotes the same instant."""

    if not values:
        return None
    items = list(values)
    if all(_same_temporal_instant(items[0], item) for item in items[1:]):
        return items[0]
    return None


def _same_temporal_instant(left: str, right: str) -> bool:
    """Compare timezone-aware ISO-8601 anchors without trusting their spelling."""

    try:
        left_dt = datetime.fromisoformat(left.replace("Z", "+00:00"))
        right_dt = datetime.fromisoformat(right.replace("Z", "+00:00"))
    except ValueError:
        return False
    if left_dt.tzinfo is None or right_dt.tzinfo is None:
        return False
    return left_dt.astimezone(timezone.utc) == right_dt.astimezone(timezone.utc)


__all__ = ["compose_experience360_frame"]
