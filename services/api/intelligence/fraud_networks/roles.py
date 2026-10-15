"""Fraud Network Intelligence — member role classification.

Pure functions: no I/O, no async. Operates on pre-fetched transfer adjacency dicts.
"""

from __future__ import annotations

from typing import Literal

MemberRole = Literal[
    "orchestrator",
    "controller",
    "mule",
    "beneficiary",
    "aggregator",
    "splitter",
    "recruiter",
    "facilitator",
    "synthetic_identity",
    "compromised_account",
    "cash_out_node",
    "injection_point",
    "relay",
    "dormant",
    "observer",
    "victim",
    "unknown",
]


def classify_member_role(
    entity_id: str,
    in_degree: int,
    out_degree: int,
    total_received_usd: float,
    total_sent_usd: float,
    is_anchor: bool,
    account_age_days: int,
    has_delegation: bool,
    agent_entity: bool,
) -> MemberRole:
    """Classify a single network member's role based on transfer graph topology.

    Rules applied in priority order (first match wins):

    1. Orchestrator: anchor node with both high in AND out degree and delegation
    2. Controller: has delegation to agents with high out-degree
    3. Synthetic identity: very new account (<7 days) with no real behavioral history
    4. Compromised account: high in-degree, sudden spike pattern (account_age > 60 days)
    5. Injection point: very high out-degree, low in-degree (primary sender)
    6. Aggregator: high in-degree, moderate out-degree (collect then redistribute)
    7. Splitter: low in-degree, high out-degree (break amounts into smaller pieces)
    8. Cash-out node: terminal out-degree=0 and high total received
    9. Mule: relay role with roughly equal in and out, low amounts
    10. Beneficiary: terminal with net positive received, not orchestrator
    11. Relay: passes funds through with ~equal in/out
    12. Recruiter: agent entity linking many human entities (delegated hub)
    13. Dormant: very low activity
    14. Victim: high in-degree from known-bad entities but low out-degree
    15. Observer: agent entity with no transfer involvement
    16. Facilitator: otherwise connected entities
    """
    total = in_degree + out_degree

    if total == 0:
        return "dormant"

    if is_anchor and has_delegation and in_degree >= 3 and out_degree >= 3:
        return "orchestrator"

    if has_delegation and agent_entity and out_degree >= 3:
        return "controller"

    if account_age_days < 7 and total > 0:
        return "synthetic_identity"

    if account_age_days > 60 and in_degree >= 5 and out_degree == 0:
        return "compromised_account"

    if out_degree >= 5 and in_degree <= 1:
        return "injection_point"

    if in_degree >= 4 and out_degree >= 2 and in_degree > out_degree * 1.5:
        return "aggregator"

    if in_degree <= 2 and out_degree >= 4 and out_degree > in_degree * 1.5:
        return "splitter"

    if out_degree == 0 and total_received_usd > 0:
        return "cash_out_node"

    if abs(in_degree - out_degree) <= 1 and total <= 6 and total_sent_usd < 10_000:
        return "mule"

    if out_degree == 0 and total_received_usd > total_sent_usd:
        return "beneficiary"

    if abs(in_degree - out_degree) <= 2 and total > 4:
        return "relay"

    if agent_entity and out_degree >= 3:
        return "recruiter"

    if total <= 2:
        return "facilitator"

    return "unknown"


def assign_roles_to_members(
    members: list[dict],
    transfers: list[dict],
) -> dict[str, MemberRole]:
    """Compute in/out degree from transfers and classify each member's role.

    Args:
        members: list of member dicts, each with 'entity_id' and optional metadata.
        transfers: list of transfer dicts with 'from_entity_id', 'to_entity_id',
                   'amount' (str), 'delegation_id' (optional).

    Returns:
        dict mapping entity_id → MemberRole
    """
    from decimal import Decimal, InvalidOperation

    entity_ids = {m["entity_id"] for m in members}

    # Build adjacency counters
    in_degree: dict[str, int] = {eid: 0 for eid in entity_ids}
    out_degree: dict[str, int] = {eid: 0 for eid in entity_ids}
    received_usd: dict[str, float] = {eid: 0.0 for eid in entity_ids}
    sent_usd: dict[str, float] = {eid: 0.0 for eid in entity_ids}
    has_delegation: dict[str, bool] = {eid: False for eid in entity_ids}

    for t in transfers:
        src = t.get("from_entity_id", "")
        dst = t.get("to_entity_id", "")
        try:
            amt = float(Decimal(str(t.get("amount", "0"))))
        except InvalidOperation:
            amt = 0.0
        has_del = bool(t.get("delegation_id"))

        if src in entity_ids:
            out_degree[src] += 1
            sent_usd[src] += amt
            if has_del:
                has_delegation[src] = True
        if dst in entity_ids:
            in_degree[dst] += 1
            received_usd[dst] += amt

    roles: dict[str, MemberRole] = {}
    for m in members:
        eid = m["entity_id"]
        is_anchor = m.get("is_anchor", False)
        account_age_days = m.get("account_age_days", 365)
        agent_entity = m.get("entity_type", "") in {"agent", "service"}
        roles[eid] = classify_member_role(
            entity_id=eid,
            in_degree=in_degree.get(eid, 0),
            out_degree=out_degree.get(eid, 0),
            total_received_usd=received_usd.get(eid, 0.0),
            total_sent_usd=sent_usd.get(eid, 0.0),
            is_anchor=is_anchor,
            account_age_days=account_age_days,
            has_delegation=has_delegation.get(eid, False),
            agent_entity=agent_entity,
        )
    return roles
