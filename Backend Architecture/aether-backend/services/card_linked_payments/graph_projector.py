from __future__ import annotations
from typing import Any

CARD_LINKED_EDGE_TYPES = [
    "CAME_FROM", "PARTICIPATED_IN", "USED_PROVIDER", "FUNDED", "ATTRIBUTED_TO",
    "OCCURRED_ON", "USED_ASSET", "ISSUED_BY", "RUNS_ON", "FOLLOWED_BY",
    "MEMBER_OF", "INITIATED_OR_INFLUENCED",
]

def project_card_linked_graph(tenant_id: str, flows: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    def node(node_id: str, node_type: str, label: str, **props: Any) -> None:
        nodes.setdefault(node_id, {"id": node_id, "type": node_type, "label": label, "tenant_id": tenant_id, **props})
    def edge(src: str, dst: str, etype: str, flow: dict[str, Any]) -> None:
        eid = f"{tenant_id}:{src}:{etype}:{dst}:{flow.get('id')}"
        edges[eid] = {"id": eid, "source": src, "target": dst, "type": etype, "tenant_id": tenant_id, "basis": flow.get("basis", "unknown"), "confidence": flow.get("confidence"), "evidence_refs": flow.get("evidence_refs", []), "identity_merge_evidence": False}
    previous_by_actor: dict[str, str] = {}
    for f in flows:
        fid = f"card_flow:{f['id']}"; node(fid, "CardLinkedFlow", f"{f.get('basis', 'unknown')} flow", **f)
        actor = f.get("canonical_entity_id") or f.get("user_id") or f.get("wallet_address_hash")
        if actor:
            node(str(actor), "UserOrWallet", str(actor)); edge(str(actor), fid, "FUNDED" if f.get("rail") == "onchain" else "USED_PROVIDER", f)
            if actor in previous_by_actor: edge(previous_by_actor[actor], fid, "FOLLOWED_BY", f)
            previous_by_actor[str(actor)] = fid
        for key, ntype, etype in (("campaign_id", "Campaign", "ATTRIBUTED_TO"), ("journey_id", "Journey", "PARTICIPATED_IN"), ("chain", "Chain", "OCCURRED_ON"), ("asset", "Token", "USED_ASSET")):
            if f.get(key):
                node(f"{ntype.lower()}:{f[key]}", ntype, str(f[key])); edge(fid, f"{ntype.lower()}:{f[key]}", etype, f)
        if f.get("card_program_id"):
            pid = f"card_program:{f['card_program_id']}"; node(pid, "CardProgram", str(f["card_program_id"])); edge(fid, pid, "USED_PROVIDER", f)
            if f.get("issuer_id"):
                iid = f"issuer:{f['issuer_id']}"; node(iid, "CardIssuer", str(f["issuer_id"])); edge(pid, iid, "ISSUED_BY", f)
            if f.get("payment_network"):
                nid = f"payment_network:{f['payment_network']}"; node(nid, "PaymentNetwork", str(f["payment_network"])); edge(pid, nid, "RUNS_ON", f)
    return {"tenant_id": tenant_id, "nodes": list(nodes.values()), "edges": list(edges.values()), "edge_types": CARD_LINKED_EDGE_TYPES}
