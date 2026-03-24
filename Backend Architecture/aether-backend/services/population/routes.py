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

from typing import Optional

from fastapi import APIRouter, Request, Query
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError, utc_now
from shared.logger.logger import get_logger, metrics
from services.population.models import PopulationCreate, MembershipAdd, PopulationType
from services.population.registry import population_repo, membership_repo

logger = get_logger("aether.service.population")
router = APIRouter(prefix="/v1/population", tags=["Population Intelligence"])


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
    )
    return APIResponse(data=result).to_dict()


@router.get("/groups/{population_id}")
async def get_group(population_id: str, request: Request):
    """Get group details including definition, metadata, and member count."""
    request.state.tenant.require_permission("read")

    group = await population_repo.find_by_id(population_id)
    if not group:
        raise NotFoundError("Population group")

    # Get current member count
    members = await membership_repo.get_members(population_id, limit=1)
    member_count = await membership_repo.count(filters={"population_id": population_id})
    group["member_count"] = member_count

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
async def add_members(population_id: str, body: MembershipAdd, request: Request):
    """Add members to a group with basis, confidence, and provenance."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    # Verify group exists
    group = await population_repo.find_by_id(population_id)
    if not group:
        raise NotFoundError("Population group")

    count = await membership_repo.add_members_batch(
        population_id=population_id,
        entity_ids=body.entity_ids,
        entity_type=body.entity_type,
        basis=body.basis,
        confidence=body.confidence,
        reason=body.reason,
        source_tag=body.source_tag,
        tenant_id=tenant.tenant_id,
    )

    # Update member count on group
    total = await membership_repo.count(filters={"population_id": population_id})
    await population_repo.update(population_id, {"member_count": total})

    metrics.increment("population_members_added", labels={"type": group.get("population_type", "")})
    return APIResponse(data={
        "population_id": population_id,
        "members_added": count,
        "total_members": total,
    }).to_dict()


@router.get("/groups/{population_id}/intelligence")
async def group_intelligence(population_id: str, request: Request):
    """
    Intelligence summary for a group: dominant behaviors, risk distribution,
    feature summaries, top relationships.
    """
    request.state.tenant.require_permission("read")

    group = await population_repo.find_by_id(population_id)
    if not group:
        raise NotFoundError("Population group")

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

    pop_a = await population_repo.find_by_id(group_a)
    pop_b = await population_repo.find_by_id(group_b)
    if not pop_a or not pop_b:
        raise NotFoundError("One or both groups not found")

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

    memberships = await membership_repo.get_populations_for_entity(entity_id)

    # Enrich with group names
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

    import hashlib
    record_id = hashlib.sha256(f"{population_id}:{entity_id}".encode()).hexdigest()[:24]
    membership = await membership_repo.find_by_id(record_id)

    if not membership:
        raise NotFoundError("Membership not found — entity may not be in this group")

    group = await population_repo.find_by_id(population_id)

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
