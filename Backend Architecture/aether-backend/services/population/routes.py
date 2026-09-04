"""
Aether Service — Population Omniview Intelligence API

Macro-to-micro population intelligence:
- Macro: population summaries, trends, top groups
- Meso: group details, members, comparisons, intelligence
- Micro: entity group memberships, explain membership

Endpoints:
    # Macro (population-level)
    GET  /v1/population/summary                    Population overview
    GET  /v1/population/groups                     List all groups
    GET  /v1/population/trends                     Population trends

    # Meso (group-level)
    POST /v1/population/groups                     Create a group
    GET  /v1/population/groups/{id}                Get group details
    GET  /v1/population/groups/{id}/members        List members
    POST /v1/population/groups/{id}/members        Add members
    GET  /v1/population/groups/{id}/intelligence    Group intelligence summary
    GET  /v1/population/compare                    Compare two groups

    # Micro (entity-level)
    GET  /v1/population/entity/{id}/memberships    Entity's group memberships
    GET  /v1/population/entity/{id}/explain/{pop_id} Explain membership
"""

from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, Request, Query

from dependencies.providers import get_graph, get_producer
from shared.common.common import (
    APIResponse,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    utc_now,
)
from shared.events.events import Event, Topic
from shared.events.producer import EventProducer
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger, metrics
from services.population.governance import (
    MembershipConsentDeniedError,
    PopulationMembershipGovernor,
)
from services.population.models import (
    DefinitionRevision,
    MembershipAdd,
    PopulationCreate,
    PopulationType,
)
from services.population.registry import definition_repo, membership_repo, population_repo

logger = get_logger("aether.service.population")
router = APIRouter(prefix="/v1/population", tags=["Population Intelligence"])


async def _require_owned_group(population_id: str, tenant_id: str) -> dict:
    """Fetch a population group, enforcing tenant ownership (IDOR guard).

    Population rows are tenant-scoped, but ``population_repo.find_by_id`` is a
    global lookup; a caller who knows another tenant's ``population_id`` must
    not be able to read or mutate that group through these routes. Returns 404
    (not 403) so a foreign group id is indistinguishable from a missing one.
    """
    group = await population_repo.find_by_id(population_id)
    if group is None or group.get("tenant_id") != tenant_id:
        raise NotFoundError("Population group")
    return group


# ══════════════════════════════════════════════════════════════════════
# MACRO — Population-level views
# ══════════════════════════════════════════════════════════════════════

@router.get("/summary")
async def population_summary(request: Request):
    """
    Macro overview of the entire population across all group types.
    Shows counts per type, total entities tracked, and top groups.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")

    # Count populations by type
    type_counts = {}
    for ptype in PopulationType:
        groups = await population_repo.query_populations(
            tenant_id=tenant.tenant_id, population_type=ptype.value, limit=1000
        )
        type_counts[ptype.value] = len(groups)

    # Total groups
    all_groups = await population_repo.query_populations(tenant_id=tenant.tenant_id, limit=1000)

    # Total memberships (approximate from group member counts)
    total_members = sum(g.get("member_count", 0) for g in all_groups)

    metrics.increment("population_macro_summary")
    return APIResponse(data={
        "total_groups": len(all_groups),
        "total_tracked_memberships": total_members,
        "groups_by_type": type_counts,
        "top_groups": sorted(all_groups, key=lambda g: g.get("member_count", 0), reverse=True)[:10],
        "computed_at": utc_now().isoformat(),
    }).to_dict()


@router.get("/groups")
async def list_groups(
    request: Request,
    population_type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(50, ge=1, le=500),
):
    """List all population groups, optionally filtered by type."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    groups = await population_repo.query_populations(
        tenant_id=tenant.tenant_id, population_type=population_type, limit=limit
    )
    return APIResponse(data={"groups": groups, "count": len(groups)}).to_dict()


@router.get("/trends")
async def population_trends(request: Request):
    """Population-level trends: group creation over time, membership changes."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    all_groups = await population_repo.query_populations(tenant_id=tenant.tenant_id, limit=1000)

    # Group by creation date (simplified — production would use time-series queries)
    by_date: dict[str, int] = {}
    for g in all_groups:
        date = g.get("created_at", "")[:10]  # YYYY-MM-DD
        by_date[date] = by_date.get(date, 0) + 1

    return APIResponse(data={
        "groups_created_by_date": by_date,
        "total_groups": len(all_groups),
        "computed_at": utc_now().isoformat(),
    }).to_dict()


# ══════════════════════════════════════════════════════════════════════
# MESO — Group-level views
# ══════════════════════════════════════════════════════════════════════

@router.post("/groups")
async def create_group(body: PopulationCreate, request: Request):
    """Create a new population group (segment, cohort, cluster, community, etc.)."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    result = await population_repo.create_population(
        name=body.name,
        population_type=body.population_type,
        description=body.description,
        definition=body.definition,
        source_tag=body.source_tag,
        tenant_id=tenant.tenant_id,
        metadata=body.metadata,
        consent_purpose=body.consent_purpose,
    )
    return APIResponse(data=result).to_dict()


@router.post("/groups/{population_id}/definition-revision")
async def revise_group_definition(
    population_id: str,
    body: DefinitionRevision,
    request: Request,
):
    """Publish a NEW immutable population-definition version (P3.2).

    Definitions are versioned contracts: this endpoint appends a new immutable
    version (the previous definition stays reconstructable in the version
    ledger) and advances the population's current definition, with the required
    ``reason`` documenting the transition. It refuses an identical no-op
    revision. Memberships are never silently reinterpreted: old cohorts keep
    the version they were computed against.
    """
    request.state.tenant.require_permission("write")
    tenant_id = request.state.tenant.tenant_id
    group = await _require_owned_group(population_id, tenant_id)

    created_by = getattr(request.state.tenant, "user_id", "") or "population_api"
    updated, version = await population_repo.revise_definition(
        group,
        body.definition,
        reason=body.reason,
        created_by=created_by,
    )
    metrics.increment("population_definition_revision", labels={"type": group.get("population_type", "")})
    return APIResponse(data={
        "population": updated,
        "definition_version": version["definition_version"],
        "supersedes_version": version["supersedes_version"],
        "definition_hash": version["definition_hash"],
        "reason": version["reason"],
    }).to_dict()


@router.get("/groups/{population_id}/definition-history")
async def group_definition_history(population_id: str, request: Request):
    """Immutable definition-version history, oldest -> newest (P3.2)."""
    request.state.tenant.require_permission("read")
    tenant_id = request.state.tenant.tenant_id
    await _require_owned_group(population_id, tenant_id)

    history = await definition_repo.history(population_id)
    return APIResponse(data={
        "population_id": population_id,
        "definition_versions": history,
        "count": len(history),
    }).to_dict()


@router.get("/groups/{population_id}")
async def get_group(population_id: str, request: Request):
    """Get group details including definition, metadata, and member count."""
    request.state.tenant.require_permission("read")

    tenant_id = request.state.tenant.tenant_id
    group = await _require_owned_group(population_id, tenant_id)

    # Get current *active* member count (governed materialisation, P3.1)
    group["member_count"] = await membership_repo.count_active_members(population_id)

    return APIResponse(data=group).to_dict()


@router.get("/groups/{population_id}/members")
async def get_members(
    population_id: str,
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    """List members of a group with confidence and membership evidence."""
    request.state.tenant.require_permission("read")

    members = await membership_repo.get_members(
        population_id=population_id, limit=limit, min_confidence=min_confidence
    )
    return APIResponse(data={
        "population_id": population_id,
        "members": members,
        "count": len(members),
    }).to_dict()


@router.post("/groups/{population_id}/members")
async def add_members(
    population_id: str,
    body: MembershipAdd,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    producer: EventProducer = Depends(get_producer),
):
    """Add members to a group through the governed membership path (P3.1).

    Membership is a graph fact: each join is written as a ``MEMBER_OF`` edge
    (entity -> population) through the mutation gateway with provenance
    (``definition_version`` / ``membership_state`` / ``evidence_refs`` on the
    edge and ledger vocabulary), and the population-membership table row is
    materialised after the edge write. There is no direct table-write path.
    """
    tenant = request.state.tenant
    tenant.require_permission("write")

    # Verify the group exists AND belongs to this tenant (IDOR guard).
    group = await _require_owned_group(population_id, tenant.tenant_id)

    governor = PopulationMembershipGovernor(graph_client=graph)

    # Preflight consent for EVERY requested member (P3.2) so a batch never
    # partially lands: a denied subject aborts the whole request before any
    # edge, ledger row, or materialised membership is written.
    for entity_id in body.entity_ids:
        try:
            await governor.assert_membership_allowed(
                population=group,
                entity_id=entity_id,
                tenant_id=tenant.tenant_id,
            )
        except MembershipConsentDeniedError as exc:
            raise ForbiddenError(
                f"Membership denied by consent for entity {exc.entity_id}",
                details={
                    "reason_code": exc.reason_code,
                    "purpose": exc.purpose,
                    "entity_id": exc.entity_id,
                },
            ) from exc

    added = 0
    for entity_id in body.entity_ids:
        row = await governor.add_membership(
            population=group,
            entity_id=entity_id,
            entity_type=body.entity_type,
            basis=body.basis,
            confidence=body.confidence,
            reason=body.reason,
            source_tag=body.source_tag,
            tenant_id=tenant.tenant_id,
        )
        if row:
            added += 1

    # Recompute the materialised member count over *active* memberships.
    total = await membership_repo.count_active_members(population_id)
    await population_repo.update(population_id, {"member_count": total})

    for entity_id in body.entity_ids:
        await producer.publish(Event(
            topic=Topic.ENTITY_MEMBERSHIP_ADDED,
            tenant_id=tenant.tenant_id,
            payload={
                "entity_id": entity_id,
                "entity_type": body.entity_type,
                "population_id": population_id,
                "population_type": group.get("population_type", ""),
                "basis": body.basis,
                "membership_state": "active",
                "definition_version": group.get("definition_version", "1"),
                "confidence": body.confidence,
                "source_tag": body.source_tag,
            },
        ))

    metrics.increment("population_members_added", labels={"type": group.get("population_type", "")})
    return APIResponse(data={
        "population_id": population_id,
        "members_added": added,
        "total_members": total,
    }).to_dict()


@router.delete("/groups/{population_id}/members/{entity_id}")
async def remove_member(
    population_id: str,
    entity_id: str,
    request: Request,
    reason: str = Query("membership_left", description="Leave reason (recorded on the edge revocation)"),
    graph: GraphClient = Depends(get_graph),
):
    """Remove a member through the governed membership path (P3.1).

    A leave is a governed soft-revoke of the ``MEMBER_OF`` edge
    (``edge_expired`` — never a hard delete) and a ``membership_state=left``
    transition on the materialised row, so membership history stays
    reconstructable from the ledger.
    """
    tenant = request.state.tenant
    tenant.require_permission("write")

    # Verify the group exists AND belongs to this tenant (IDOR guard).
    group = await _require_owned_group(population_id, tenant.tenant_id)

    governor = PopulationMembershipGovernor(graph_client=graph)
    row = await governor.remove_membership(
        population=group,
        entity_id=entity_id,
        reason=reason,
        tenant_id=tenant.tenant_id,
    )

    total = await membership_repo.count_active_members(population_id)
    await population_repo.update(population_id, {"member_count": total})

    return APIResponse(data={
        "population_id": population_id,
        "entity_id": entity_id,
        "removed": bool(row),
        "membership_state": (row or {}).get("membership_state", "left"),
        "total_members": total,
    }).to_dict()


@router.get("/groups/{population_id}/intelligence")
async def group_intelligence(population_id: str, request: Request):
    """
    Intelligence summary for a group: dominant behaviors, risk distribution,
    feature summaries, top relationships.
    """
    request.state.tenant.require_permission("read")

    group = await _require_owned_group(population_id, request.state.tenant.tenant_id)

    members = await membership_repo.get_members(population_id, limit=500)

    # Aggregate membership evidence
    basis_distribution: dict[str, int] = {}
    confidence_sum = 0.0
    for m in members:
        basis = m.get("basis", "unknown")
        basis_distribution[basis] = basis_distribution.get(basis, 0) + 1
        confidence_sum += m.get("confidence", 0.0)

    avg_confidence = confidence_sum / max(len(members), 1)

    return APIResponse(data={
        "population_id": population_id,
        "name": group.get("name"),
        "type": group.get("population_type"),
        "member_count": len(members),
        "avg_confidence": round(avg_confidence, 4),
        "membership_basis_distribution": basis_distribution,
        "definition": group.get("definition", {}),
        "metadata": group.get("metadata", {}),
        "computed_at": utc_now().isoformat(),
    }).to_dict()


@router.get("/compare")
async def compare_groups(
    request: Request,
    group_a: str = Query(..., description="First group ID"),
    group_b: str = Query(..., description="Second group ID"),
):
    """Compare two groups: member overlap, feature differences, basis distribution."""
    request.state.tenant.require_permission("read")

    tenant_id = request.state.tenant.tenant_id
    pop_a = await _require_owned_group(group_a, tenant_id)
    pop_b = await _require_owned_group(group_b, tenant_id)

    members_a = await membership_repo.get_members(group_a, limit=1000)
    members_b = await membership_repo.get_members(group_b, limit=1000)

    ids_a = {m["entity_id"] for m in members_a}
    ids_b = {m["entity_id"] for m in members_b}
    overlap = ids_a & ids_b

    return APIResponse(data={
        "group_a": {"id": group_a, "name": pop_a.get("name"), "members": len(ids_a)},
        "group_b": {"id": group_b, "name": pop_b.get("name"), "members": len(ids_b)},
        "overlap_count": len(overlap),
        "overlap_percentage": round(len(overlap) / max(len(ids_a | ids_b), 1), 4),
        "unique_to_a": len(ids_a - ids_b),
        "unique_to_b": len(ids_b - ids_a),
        "computed_at": utc_now().isoformat(),
    }).to_dict()


# ══════════════════════════════════════════════════════════════════════
# MICRO — Entity-level group context
# ══════════════════════════════════════════════════════════════════════

@router.get("/entity/{entity_id}/memberships")
async def entity_memberships(entity_id: str, request: Request):
    """Get all groups an entity belongs to with confidence and basis."""
    request.state.tenant.require_permission("read")

    tenant_id = request.state.tenant.tenant_id
    memberships = [
        m for m in await membership_repo.get_populations_for_entity(entity_id)
        if m.get("tenant_id") == tenant_id
    ]

    # Enrich with group names (group ownership already enforced per row).
    enriched = []
    for m in memberships:
        group = await population_repo.find_by_id(m.get("population_id", ""))
        enriched.append({
            **m,
            "population_name": group.get("name", "") if group else "",
            "population_type": group.get("population_type", "") if group else "",
        })

    return APIResponse(data={
        "entity_id": entity_id,
        "memberships": enriched,
        "count": len(enriched),
    }).to_dict()


@router.get("/entity/{entity_id}/explain/{population_id}")
async def explain_membership(entity_id: str, population_id: str, request: Request):
    """Explain why an entity is in a specific group: basis, confidence, reason, provenance."""
    request.state.tenant.require_permission("read")

    tenant_id = request.state.tenant.tenant_id
    group = await _require_owned_group(population_id, tenant_id)

    record_id = hashlib.sha256(f"{population_id}:{entity_id}".encode()).hexdigest()[:24]
    membership = await membership_repo.find_by_id(record_id)

    if not membership or membership.get("tenant_id") != tenant_id:
        raise NotFoundError("Membership not found — entity may not be in this group")

    return APIResponse(data={
        "entity_id": entity_id,
        "population_id": population_id,
        "population_name": group.get("name", "") if group else "",
        "basis": membership.get("basis", ""),
        "confidence": membership.get("confidence", 0.0),
        "reason": membership.get("reason", ""),
        "source_tag": membership.get("source_tag", ""),
        "joined_at": membership.get("joined_at", ""),
        "definition": group.get("definition", {}) if group else {},
    }).to_dict()
