"""Consent-scoped current membership of explicitly linked campaign populations.

Population membership rows enumerate candidates. Exact tenant MEMBER_OF ledger
replay, canonical entity resolution and a current consent receipt are required
before a candidate can be projected. No roster completeness is inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

MAX_CAMPAIGN_POPULATIONS = 5
MAX_CAMPAIGN_POPULATION_MEMBERS = 20
MAX_CAMPAIGN_MEMBERSHIP_LEDGER_ROWS = 200


@dataclass(frozen=True)
class CampaignPopulationMembershipRead:
    tenant_id: str
    population_id: str
    population_type: Optional[str]
    rows: tuple[dict[str, Any], ...]
    available: bool
    truncated: bool = False
    reason: Optional[str] = None


class CampaignPopulationMembershipAuthority:
    async def read(self, tenant_id: str, population_id: str) -> CampaignPopulationMembershipRead:
        def unavailable(reason: str) -> CampaignPopulationMembershipRead:
            return CampaignPopulationMembershipRead(tenant_id, population_id, None, (), False, reason=reason)

        try:
            from governance.consent.authority import evaluate_consent_with_receipt
            from graph.temporal360.history_replay import GraphHistoryReplay
            from identity.population.registry import membership_repo, population_repo
            from repositories.graph_mutation_ledger import GraphMutationLedgerRepository
            from repositories.repos import EntityRepository
            from shared.graph.graph import EdgeType

            population = await population_repo.find_by_id(population_id)
            if (
                not isinstance(population, dict) or population.get("tenant_id") != tenant_id
                or population.get("id") != population_id or population.get("status") != "active"
            ):
                return unavailable("campaign_population_scope_unavailable")
            population_type = population.get("population_type")
            if population_type not in {"cluster", "cohort"}:
                return CampaignPopulationMembershipRead(tenant_id, population_id, None, (), True,
                                                        reason="linked_population_not_cluster_or_cohort")
            purpose = population.get("consent_purpose")
            if not isinstance(purpose, str) or not purpose.strip():
                return unavailable("campaign_population_consent_purpose_missing")
            candidates = await membership_repo.find_many(
                filters={"tenant_id": tenant_id, "population_id": population_id},
                limit=MAX_CAMPAIGN_POPULATION_MEMBERS + 1,
            )
            if not isinstance(candidates, list):
                return unavailable("campaign_population_membership_source_invalid")
            truncated = len(candidates) > MAX_CAMPAIGN_POPULATION_MEMBERS
            candidates = candidates[:MAX_CAMPAIGN_POPULATION_MEMBERS]
            candidate_ids: set[str] = set()
            for row in candidates:
                if not isinstance(row, dict) or row.get("tenant_id") != tenant_id or row.get("population_id") != population_id:
                    return unavailable("campaign_population_membership_scope_invalid")
                if row.get("membership_state", row.get("status", "active")) != "active":
                    continue
                entity_id = row.get("entity_id")
                if not isinstance(entity_id, str) or not entity_id.strip() or entity_id in candidate_ids:
                    return unavailable("campaign_population_membership_identity_invalid")
                candidate_ids.add(entity_id)
            entities, entity_truncated = await EntityRepository().find_many_for_tenant_entity_ids(tenant_id, candidate_ids)
            if entity_truncated or not isinstance(entities, list):
                return unavailable("campaign_population_entity_lookup_incomplete")
            entity_counts: dict[str, int] = {}
            for entity in entities:
                if not isinstance(entity, dict) or entity.get("tenant_id") != tenant_id or entity.get("entity_id") not in candidate_ids:
                    return unavailable("campaign_population_entity_scope_invalid")
                entity_id = entity["entity_id"]
                entity_counts[entity_id] = entity_counts.get(entity_id, 0) + 1
            ledger = GraphMutationLedgerRepository()
            accepted: list[dict[str, Any]] = []
            incomplete = truncated
            for entity_id in sorted(candidate_ids):
                if entity_counts.get(entity_id) != 1:
                    incomplete = True
                    continue
                consent = await evaluate_consent_with_receipt(tenant_id, entity_id, None, purpose)
                receipt_id = getattr(consent, "receipt_id", None)
                if getattr(consent, "allowed", False) is not True or not isinstance(receipt_id, str) or not receipt_id.strip():
                    incomplete = True
                    continue
                aggregate_id = f"{EdgeType.MEMBER_OF}:{entity_id}:{population_id}"
                ledger_rows = await ledger.list_records(tenant_id, aggregate_id=aggregate_id,
                                                        limit=MAX_CAMPAIGN_MEMBERSHIP_LEDGER_ROWS + 1)
                if not isinstance(ledger_rows, list) or len(ledger_rows) > MAX_CAMPAIGN_MEMBERSHIP_LEDGER_ROWS:
                    incomplete = True
                    continue
                for row in ledger_rows:
                    payload = row.get("payload") if isinstance(row, dict) else None
                    if (
                        not isinstance(row, dict) or row.get("tenant_id") != tenant_id
                        or row.get("aggregate_type") != "edge" or row.get("aggregate_id") != aggregate_id
                        or not isinstance(payload, dict) or payload.get("kind") not in {"edge", "edge_revocation"}
                        or payload.get("edge_type") != EdgeType.MEMBER_OF
                        or payload.get("from_vertex_id") != entity_id or payload.get("to_vertex_id") != population_id
                        or (payload.get("kind") == "edge" and
                            (not isinstance(payload.get("properties"), dict) or payload["properties"].get("tenant_id") != tenant_id))
                    ):
                        return unavailable("campaign_population_ledger_scope_invalid")
                history = GraphHistoryReplay._history_from_rows(entity_id, None, ledger_rows)
                edge_key = (EdgeType.MEMBER_OF, entity_id, population_id)
                if edge_key not in set(history.live_edges):
                    incomplete = True
                    continue
                adds = [event for event in history.events if event.kind == "edge_added" and
                        (event.edge_type, event.from_vertex_id, event.to_vertex_id) == edge_key]
                if not adds:
                    incomplete = True
                    continue
                latest = max(adds, key=lambda event: event.ledger_offset)
                if not isinstance(latest.mutation_id, str) or not latest.mutation_id.strip():
                    incomplete = True
                    continue
                latest_row = next((row for row in ledger_rows if row.get("mutation_id") == latest.mutation_id and
                                   row.get("ledger_offset") == latest.ledger_offset), None)
                properties = latest_row.get("payload", {}).get("properties", {}) if latest_row else {}
                if not isinstance(properties, dict) or properties.get("membership_state") not in (None, "", "active"):
                    incomplete = True
                    continue
                accepted.append({"tenant_id": tenant_id, "population_id": population_id,
                                 "population_type": population_type, "entity_id": entity_id,
                                 "ledger_mutation_id": latest.mutation_id,
                                 "recorded_at": latest.recorded_at, "consent_receipt_id": receipt_id,
                                 "consent_purpose": purpose})
            return CampaignPopulationMembershipRead(
                tenant_id, population_id, population_type, tuple(accepted), True,
                truncated=incomplete, reason="campaign_population_membership_partial" if incomplete else None,
            )
        except Exception:  # noqa: BLE001 - authority and consent errors fail closed
            return unavailable("campaign_population_membership_authority_unavailable")
