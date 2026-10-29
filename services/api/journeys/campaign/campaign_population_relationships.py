"""Current observed FOLLOWS edges between members of linked populations.

The caller supplies already verified membership candidates. This reader checks
analytics consent again for both endpoints and never infers influence or roster
completeness from a bounded graph scan.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_RELATIONSHIP_MEMBERS = 100
MAX_RELATIONSHIP_EDGES = 500


@dataclass(frozen=True)
class CampaignPopulationRelationshipRead:
    tenant_id: str
    rows: tuple[dict[str, Any], ...]
    available: bool
    truncated: bool = False
    reason: str | None = None


class CampaignPopulationRelationshipAuthority:
    def __init__(self, *, graph: Any = None, consent: Any = None):
        self._graph = graph
        self._consent = consent

    async def read(self, tenant_id: str, memberships: dict[str, set[str]]) -> CampaignPopulationRelationshipRead:
        from governance.consent.authority import evaluate_consent_with_receipt
        from shared.graph.graph import Edge, get_graph_client, tenant_of
        from shared.relationship_spine.relationship_registry import live_graph_edge_type, predicate_entry
        from shared.temporal.instant import parse_instant_strict

        def unavailable(reason: str) -> CampaignPopulationRelationshipRead:
            return CampaignPopulationRelationshipRead(tenant_id, (), False, reason=reason)

        ids = {member for members in memberships.values() for member in members}
        if not tenant_id or len(ids) > MAX_RELATIONSHIP_MEMBERS or any(not isinstance(i, str) or not i for i in ids):
            return unavailable("campaign_relationship_member_scope_invalid")
        predicate = predicate_entry("FOLLOWS")
        edge_type = live_graph_edge_type("FOLLOWS")
        if (not predicate or predicate.get("family") != "SOCIAL"
                or predicate.get("graphRegistrationState") != "REGISTERED"
                or "NON_TRANSITIVE" not in predicate.get("transitivityClasses", []) or not edge_type):
            return unavailable("campaign_relationship_predicate_unavailable")
        graph = self._graph or get_graph_client()
        consent = self._consent or evaluate_consent_with_receipt
        try:
            receipts: dict[str, str] = {}
            for member in sorted(ids):
                result = await consent(tenant_id, member, None, "analytics")
                receipt = getattr(result, "receipt_id", None)
                if getattr(result, "allowed", False) is True and isinstance(receipt, str) and receipt.strip():
                    receipts[member] = receipt
            page = await graph.get_edges_for_tenant(tenant_id, limit=MAX_RELATIONSHIP_EDGES,
                                                    edge_types=[edge_type], include_revoked=False)
        except Exception:  # noqa: BLE001 - dependency errors do not admit relationships
            return unavailable("campaign_relationship_authority_unavailable")
        if (not isinstance(page, tuple) or len(page) != 2 or not isinstance(page[0], list)
                or not isinstance(page[1], bool) or len(page[0]) > MAX_RELATIONSHIP_EDGES):
            return unavailable("campaign_relationship_graph_read_invalid")
        incomplete = page[1] or len(receipts) != len(ids)
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        now = datetime.now(timezone.utc)
        for edge in page[0]:
            if not isinstance(edge, Edge) or not isinstance(edge.properties, dict):
                incomplete = True
                continue
            props = edge.properties
            a, b = edge.from_vertex_id, edge.to_vertex_id
            populations = [p for p, members in memberships.items() if a in members and b in members]
            if not populations or a == b:
                continue
            if (edge.edge_type != edge_type or tenant_of(props) != tenant_id
                    or (props.get("tenantId") and props.get("tenant_id") and props["tenantId"] != props["tenant_id"])
                    or props.get("relationship_predicate") != "FOLLOWS"
                    or props.get("revoked_at")
                    or str(props.get("revoked", "")).strip().lower() in {"true", "1", "yes", "revoked"}
                    or a not in receipts or b not in receipts):
                incomplete = True
                continue
            try:
                start = parse_instant_strict(props["valid_from"]) if props.get("valid_from") else None
                end = parse_instant_strict(props["valid_to"]) if props.get("valid_to") else None
                observed = parse_instant_strict(props["observed_at"]) if props.get("observed_at") else None
            except (TypeError, ValueError):
                incomplete = True
                continue
            if (start and start > now) or (end and end <= now) or (observed and observed > now):
                incomplete = True
                continue
            key, facts = props.get("idempotency_key"), props.get("evidence_refs")
            if (not isinstance(key, str) or not key.strip() or not isinstance(facts, (list, tuple))
                    or not facts or len(facts) > 20
                    or any(not isinstance(x, str) or not x.strip() or len(x) > 256 for x in facts)):
                incomplete = True
                continue
            for population_id in populations:
                if (population_id, key) in seen:
                    incomplete = True
                    continue
                seen.add((population_id, key))
                rows.append({"tenant_id": tenant_id, "population_id": population_id,
                             "source_entity_id": a, "target_entity_id": b,
                             "edge_id": key, "fact_ids": list(dict.fromkeys(facts)),
                             "source_receipt_id": receipts[a], "target_receipt_id": receipts[b],
                             "observed_at": observed.isoformat() if observed else None})
        return CampaignPopulationRelationshipRead(tenant_id, tuple(rows), True, incomplete,
                                                  "campaign_relationship_read_partial" if incomplete else None)
