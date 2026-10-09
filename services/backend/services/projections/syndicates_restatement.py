"""Syndicates identity restatement over explicitly opted-in Population 360 groups."""

from __future__ import annotations

from typing import Any

from services.projections.syndicates_restatement_capability import is_syndicates_group


def _is_active(row: dict[str, Any]) -> bool:
    return (row.get("membership_state") or row.get("status") or "active") == "active"


async def restate_syndicates_merge(
    *,
    tenant_id: str,
    survivor_entity_id: str,
    consumed_entity_ids: list[str],
    decision_id: str,
    population_repository=None,
    membership_repository=None,
    governor=None,
) -> dict[str, Any]:
    """Union opted-in Syndicates memberships through governed Population writes.

    Group membership is explicitly opted in through population metadata. The
    survivor join is consent checked before the consumed entity leaves, so a
    denied join cannot silently erase the source membership. Each write is
    idempotent and the decision reference is carried as provenance.
    """
    if not tenant_id or not survivor_entity_id or not decision_id:
        raise ValueError("tenant, survivor, and decision identifiers are required")
    consumed = list(dict.fromkeys(
        entity_id for entity_id in consumed_entity_ids
        if entity_id and entity_id != survivor_entity_id
    ))
    if not consumed:
        return {"status": "completed", "groups_rewritten": 0, "memberships_rewritten": 0}

    if population_repository is None or membership_repository is None or governor is None:
        from shared.graph.graph import get_graph_client
        from services.population.governance import PopulationMembershipGovernor
        from services.population.registry import membership_repo, population_repo

        population_repository = population_repository or population_repo
        membership_repository = membership_repository or membership_repo
        governor = governor or PopulationMembershipGovernor(graph_client=get_graph_client())

    groups = await population_repository.query_populations(tenant_id, limit=10000)
    opted_groups = [group for group in groups if is_syndicates_group(group)]
    rewritten = 0
    changed_groups: set[str] = set()
    for group in opted_groups:
        if str(group.get("tenant_id") or "") != tenant_id:
            continue
        group_id = str(group.get("id") or "")
        if not group_id:
            continue
        rows = await membership_repository.get_members(
            group_id, limit=10000, include_inactive=True
        )
        for row in rows:
            source_id = str(row.get("entity_id") or "")
            if (
                source_id not in consumed
                or str(row.get("tenant_id") or "") != tenant_id
                or not _is_active(row)
            ):
                continue
            provenance = list(row.get("evidence_refs") or [])
            reference = f"identity_restatement:{decision_id}"
            if reference not in provenance:
                provenance.append(reference)
            from services.population.models import MembershipBasis

            await governor.add_membership(
                population=group,
                entity_id=survivor_entity_id,
                entity_type=str(row.get("entity_type") or "user"),
                basis=MembershipBasis(str(row.get("basis") or "rule")),
                confidence=float(row.get("confidence", 1.0)),
                reason=f"identity merge union ({decision_id})",
                source_tag=str(row.get("source_tag") or "identity_restatement"),
                tenant_id=tenant_id,
                evidence_refs=provenance,
                source_event_id=decision_id,
                actor_id="identity_projection_restatement",
            )
            await governor.remove_membership(
                population=group,
                entity_id=source_id,
                reason=f"identity_merged_into:{survivor_entity_id}:{decision_id}",
                tenant_id=tenant_id,
                actor_id="identity_projection_restatement",
            )
            rewritten += 1
            changed_groups.add(group_id)

    return {
        "status": "completed",
        "groups_rewritten": len(changed_groups),
        "memberships_rewritten": rewritten,
        "membership_authority": "population360.governed_membership",
        "decision_id": decision_id,
    }


def _split_ref(reference: str) -> tuple[str, str] | None:
    """Parse the accepted, non-PII Syndicates split evidence-ref namespace."""
    for kind in ("alias", "observation"):
        prefix = f"syndicates:identity_{kind}:"
        if reference.startswith(prefix) and reference[len(prefix):]:
            return kind, reference[len(prefix):]
    return None


async def restate_syndicates_split(
    *,
    tenant_id: str,
    split_event: dict[str, Any],
    decision_id: str,
    population_repository=None,
    membership_repository=None,
    identity_repository=None,
    governor=None,
) -> dict[str, Any]:
    """Move only memberships whose complete evidence refs prove one fragment.

    Accepted membership refs are ``syndicates:identity_alias:<alias-id>`` and
    ``syndicates:identity_observation:<observation-id>``. Each referenced row
    must belong to this tenant and, after the split, resolve to either the
    original entity or the resulting entity. All refs on one membership must
    resolve to the same side. Missing, malformed, foreign, or mixed-side refs
    leave that membership untouched and appear in ``unsupported_memberships``.
    """
    if not tenant_id or not decision_id:
        raise ValueError("tenant and decision identifiers are required")
    if str(split_event.get("tenant_id") or "") != tenant_id:
        raise ValueError("split event tenant does not match restatement tenant")
    if str(split_event.get("id") or "") != decision_id:
        raise ValueError("split event does not match the identity decision")

    source_id = str(split_event.get("original_entity_id") or "")
    resulting_ids = list(dict.fromkeys(
        str(value) for value in split_event.get("resulting_entity_ids") or [] if value
    ))
    targets = [entity_id for entity_id in resulting_ids if entity_id != source_id]
    fragment = split_event.get("fragment")
    if not source_id or len(targets) != 1 or not isinstance(fragment, dict):
        return {
            "status": "unsupported",
            "reason_code": "syndicates_split_fragment_contract_invalid",
            "membership_unchanged": True,
            "rewritten_memberships": 0,
            "unsupported_memberships": [],
        }
    target_id = targets[0]

    if population_repository is None or membership_repository is None or identity_repository is None or governor is None:
        from shared.graph.graph import get_graph_client
        from services.identity.repository import IdentityResolutionRepository
        from services.population.governance import PopulationMembershipGovernor
        from services.population.registry import membership_repo, population_repo

        population_repository = population_repository or population_repo
        membership_repository = membership_repository or membership_repo
        identity_repository = identity_repository or IdentityResolutionRepository()
        governor = governor or PopulationMembershipGovernor(graph_client=get_graph_client())

    # Selector IDs name the old aliases/observations. The durable event's
    # moved-ID lists prove which aliases were reissued and which observations
    # now belong to the destination. Alias selectors and reissued aliases are
    # positional pairs emitted from the validated fragment plan.
    selected_alias_ids = [str(value) for value in fragment.get("alias_ids") or []]
    moved_alias_ids = [str(value) for value in fragment.get("moved_alias_ids") or []]
    selected_observation_ids = [str(value) for value in fragment.get("observation_ids") or []]
    moved_observation_ids = [str(value) for value in fragment.get("moved_observation_ids") or []]
    moved_alias_map_rows = fragment.get("moved_alias_map")
    alias_moved_map: dict[str, str] = {}
    if isinstance(moved_alias_map_rows, list):
        for item in moved_alias_map_rows:
            if not isinstance(item, dict):
                continue
            source_alias_id = str(item.get("source_alias_id") or "")
            resulting_alias_id = str(item.get("resulting_alias_id") or "")
            if source_alias_id and resulting_alias_id and source_alias_id not in alias_moved_map:
                alias_moved_map[source_alias_id] = resulting_alias_id
    alias_map_valid = (
        set(alias_moved_map) == set(selected_alias_ids)
        and set(alias_moved_map.values()).issubset(set(moved_alias_ids))
        and len(alias_moved_map) == len(selected_alias_ids)
    )
    if not alias_map_valid:
        alias_moved_map = {}
    selected_observations = set(selected_observation_ids)
    moved_observations = set(moved_observation_ids)

    async def classify(reference: str) -> str | None:
        parsed = _split_ref(reference)
        if parsed is None:
            return None
        kind, ref_id = parsed
        if kind == "alias":
            row = await identity_repository.get_alias_by_id(ref_id)
            if row is None or row.get("tenant_id") != tenant_id:
                return None
            mapped_target = alias_moved_map.get(ref_id)
            if mapped_target:
                moved_row = await identity_repository.get_alias_by_id(mapped_target)
                if (
                    row.get("canonical_entity_id") == source_id
                    and row.get("revoked_at")
                    and moved_row is not None
                    and moved_row.get("tenant_id") == tenant_id
                    and moved_row.get("canonical_entity_id") == target_id
                    and row.get("alias_type") == moved_row.get("alias_type")
                    and row.get("alias_value_hash") == moved_row.get("alias_value_hash")
                ):
                    return "resulting"
                return None
            if row.get("canonical_entity_id") == target_id:
                return "resulting" if ref_id in moved_alias_ids else None
            if row.get("canonical_entity_id") == source_id and not row.get("revoked_at"):
                return "original"
            return None

        row = await identity_repository.get_observation_by_id(ref_id)
        if row is None or row.get("tenant_id") != tenant_id:
            return None
        if ref_id in selected_observations:
            if ref_id in moved_observations and row.get("canonical_entity_id") == target_id:
                return "resulting"
            return None
        if row.get("canonical_entity_id") == source_id:
            return "original"
        if row.get("canonical_entity_id") == target_id and ref_id in moved_observations:
            return "resulting"
        return None

    groups = await population_repository.query_populations(tenant_id, limit=10000)
    opted_groups = [group for group in groups if is_syndicates_group(group)]
    rewritten = 0
    changed_groups: set[str] = set()
    unsupported_memberships: list[dict[str, str]] = []
    for group in opted_groups:
        if str(group.get("tenant_id") or "") != tenant_id:
            continue
        group_id = str(group.get("id") or "")
        if not group_id:
            continue
        rows = await membership_repository.get_members(
            group_id, limit=10000, include_inactive=True
        )
        for row in rows:
            if (
                str(row.get("tenant_id") or "") != tenant_id
                or str(row.get("entity_id") or "") != source_id
                or not _is_active(row)
            ):
                continue
            entity_id = str(row.get("entity_id") or "")
            refs = row.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                unsupported_memberships.append({
                    "population_id": group_id,
                    "entity_id": entity_id,
                    "reason_code": "syndicates_membership_evidence_missing",
                })
                continue
            classifications = [await classify(str(ref)) for ref in refs]
            sides = set(classifications)
            if None in sides or len(sides) != 1:
                unsupported_memberships.append({
                    "population_id": group_id,
                    "entity_id": entity_id,
                    "reason_code": (
                        "syndicates_membership_evidence_unattributed"
                        if None in sides
                        else "syndicates_membership_evidence_conflicts_across_fragments"
                    ),
                })
                continue
            if sides == {"original"}:
                continue

            provenance = list(refs)
            restatement_ref = f"identity_restatement:{decision_id}"
            if restatement_ref not in provenance:
                provenance.append(restatement_ref)
            from services.population.models import MembershipBasis

            await governor.add_membership(
                population=group,
                entity_id=target_id,
                entity_type=str(row.get("entity_type") or "user"),
                basis=MembershipBasis(str(row.get("basis") or "rule")),
                confidence=float(row.get("confidence", 1.0)),
                reason=f"identity split fragment attribution ({decision_id})",
                source_tag=str(row.get("source_tag") or "identity_restatement"),
                tenant_id=tenant_id,
                evidence_refs=provenance,
                source_event_id=decision_id,
                actor_id="identity_projection_restatement",
            )
            await governor.remove_membership(
                population=group,
                entity_id=source_id,
                reason=f"identity_split_fragment:{target_id}:{decision_id}",
                tenant_id=tenant_id,
                actor_id="identity_projection_restatement",
            )
            rewritten += 1
            changed_groups.add(group_id)

    return {
        "status": "unsupported" if unsupported_memberships else "completed",
        "reason_code": (
            "syndicates_split_membership_evidence_incomplete"
            if unsupported_memberships else None
        ),
        "membership_authority": "population360.governed_membership",
        "decision_id": decision_id,
        "groups_rewritten": len(changed_groups),
        "rewritten_memberships": rewritten,
        "unsupported_memberships": unsupported_memberships,
        "membership_unchanged": rewritten == 0,
    }
