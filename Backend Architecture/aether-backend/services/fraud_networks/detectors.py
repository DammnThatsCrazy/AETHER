"""Fraud Network Intelligence — cluster signal detectors.

All functions are pure: they accept pre-fetched plain dicts, perform no I/O,
and return lists of evidence tuples: (signal_name, entity_ids, detail_dict).
No async, no database access, no side effects.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

EvidenceTuple = tuple[str, list[str], dict[str, Any]]


def detect_shared_device(
    sessions: list[dict],
) -> list[EvidenceTuple]:
    """Detect entities sharing the same device fingerprint.

    Args:
        sessions: list of session dicts with 'entity_id' and 'device_fingerprint'.

    Returns:
        Evidence tuples for each device fingerprint shared by 2+ entities.
    """
    device_to_entities: dict[str, set[str]] = defaultdict(set)
    for session in sessions:
        fp = session.get("device_fingerprint")
        eid = session.get("entity_id")
        if fp and eid:
            device_to_entities[fp].add(eid)

    results: list[EvidenceTuple] = []
    for fp, entities in device_to_entities.items():
        if len(entities) >= 2:
            results.append((
                "shared_device",
                sorted(entities),
                {"device_fingerprint": fp, "entity_count": len(entities)},
            ))
    return results


def detect_shared_ip(
    sessions: list[dict],
) -> list[EvidenceTuple]:
    """Detect entities using the same IP address across sessions.

    Args:
        sessions: list of session dicts with 'entity_id' and 'ip_address'.

    Returns:
        Evidence tuples for each IP shared by 2+ entities.
    """
    ip_to_entities: dict[str, set[str]] = defaultdict(set)
    for session in sessions:
        ip = session.get("ip_address")
        eid = session.get("entity_id")
        if ip and eid:
            ip_to_entities[ip].add(eid)

    results: list[EvidenceTuple] = []
    for ip, entities in ip_to_entities.items():
        if len(entities) >= 2:
            results.append((
                "shared_ip",
                sorted(entities),
                {"ip_address": ip, "entity_count": len(entities)},
            ))
    return results


def detect_wallet_cluster(
    wallet_links: list[dict],
) -> list[EvidenceTuple]:
    """Detect entities linked to the same wallet address or wallet cluster.

    Args:
        wallet_links: list of dicts with 'entity_id', 'wallet_address', 'chain'.

    Returns:
        Evidence tuples for wallets linked to 2+ entities.
    """
    wallet_to_entities: dict[str, set[str]] = defaultdict(set)
    wallet_chains: dict[str, str] = {}
    for link in wallet_links:
        addr = link.get("wallet_address")
        eid = link.get("entity_id")
        chain = link.get("chain", "unknown")
        if addr and eid:
            key = f"{chain}:{addr}"
            wallet_to_entities[key].add(eid)
            wallet_chains[key] = chain

    results: list[EvidenceTuple] = []
    for key, entities in wallet_to_entities.items():
        if len(entities) >= 2:
            chain, addr = key.split(":", 1)
            results.append((
                "shared_wallet",
                sorted(entities),
                {"wallet_address": addr, "chain": chain, "entity_count": len(entities)},
            ))
    return results


def detect_circular_transfers(
    transfers: list[dict],
    max_depth: int = 6,
) -> list[EvidenceTuple]:
    """Detect circular money flows using iterative DFS cycle detection.

    Args:
        transfers: list of dicts with 'from_entity_id', 'to_entity_id', 'amount'.
        max_depth: maximum path length to search for cycles.

    Returns:
        Evidence tuples for each detected cycle (unique by sorted entity set).
    """
    # Build adjacency list
    adjacency: dict[str, list[str]] = defaultdict(list)
    for t in transfers:
        src = t.get("from_entity_id")
        dst = t.get("to_entity_id")
        if src and dst and src != dst:
            adjacency[src].append(dst)

    visited_cycles: set[frozenset[str]] = set()
    results: list[EvidenceTuple] = []

    def _dfs(start: str, current: str, path: list[str], depth: int) -> None:
        if depth > max_depth:
            return
        for neighbor in adjacency.get(current, []):
            if neighbor == start and len(path) >= 2:
                cycle_key = frozenset(path)
                if cycle_key not in visited_cycles:
                    visited_cycles.add(cycle_key)
                    results.append((
                        "circular_transfer",
                        sorted(path),
                        {"cycle_length": len(path), "cycle_nodes": list(path)},
                    ))
            elif neighbor not in path:
                _dfs(start, neighbor, path + [neighbor], depth + 1)

    all_nodes = set(adjacency.keys())
    for node in all_nodes:
        _dfs(node, node, [node], 1)

    return results


def detect_split_merge(
    transfers: list[dict],
    split_threshold: int = 3,
    merge_threshold: int = 3,
) -> list[EvidenceTuple]:
    """Detect split-then-merge layering patterns: one → many → one.

    Args:
        transfers: list of dicts with 'from_entity_id', 'to_entity_id'.
        split_threshold: min fan-out to consider a split node.
        merge_threshold: min fan-in to consider a merge node.

    Returns:
        Evidence tuples for (splitter, merge_target) pairs connected through intermediaries.
    """
    # Count outbound (split) and inbound (merge) degrees
    out_count: dict[str, int] = defaultdict(int)
    in_count: dict[str, int] = defaultdict(int)
    out_to: dict[str, set[str]] = defaultdict(set)
    in_from: dict[str, set[str]] = defaultdict(set)

    for t in transfers:
        src = t.get("from_entity_id")
        dst = t.get("to_entity_id")
        if src and dst:
            out_count[src] += 1
            in_count[dst] += 1
            out_to[src].add(dst)
            in_from[dst].add(src)

    splitters = {eid for eid, cnt in out_count.items() if cnt >= split_threshold}
    mergers = {eid for eid, cnt in in_count.items() if cnt >= merge_threshold}

    results: list[EvidenceTuple] = []
    for splitter in splitters:
        intermediaries = out_to[splitter]
        for merger in mergers:
            shared = intermediaries & in_from[merger]
            if len(shared) >= 2 and splitter != merger:
                all_entities = {splitter, merger} | shared
                results.append((
                    "split_merge",
                    sorted(all_entities),
                    {
                        "splitter": splitter,
                        "merger": merger,
                        "intermediary_count": len(shared),
                        "intermediaries": sorted(shared),
                    },
                ))
    return results


def detect_reward_farming(
    reward_events: list[dict],
    min_cluster_size: int = 3,
) -> list[EvidenceTuple]:
    """Detect coordinated reward/referral farming: clusters of accounts with identical referral patterns.

    Args:
        reward_events: list of dicts with 'entity_id', 'referrer_id', 'reward_type', 'campaign_id'.
        min_cluster_size: minimum number of entities with same referrer to flag.

    Returns:
        Evidence tuples for referrer → cluster group pairs.
    """
    referrer_to_referred: dict[str, set[str]] = defaultdict(set)
    campaign_by_referrer: dict[str, set[str]] = defaultdict(set)

    for event in reward_events:
        eid = event.get("entity_id")
        ref = event.get("referrer_id")
        campaign = event.get("campaign_id")
        if eid and ref and eid != ref:
            referrer_to_referred[ref].add(eid)
            if campaign:
                campaign_by_referrer[ref].add(campaign)

    results: list[EvidenceTuple] = []
    for referrer, referred in referrer_to_referred.items():
        if len(referred) >= min_cluster_size:
            all_entities = {referrer} | referred
            results.append((
                "reward_farming",
                sorted(all_entities),
                {
                    "referrer_id": referrer,
                    "referred_count": len(referred),
                    "campaigns": sorted(campaign_by_referrer.get(referrer, set())),
                },
            ))
    return results


def detect_agentic_delegation_abuse(
    delegations: list[dict],
    transfers: list[dict],
    min_agent_out_degree: int = 5,
) -> list[EvidenceTuple]:
    """Detect agents being used to fan out transfers across many target accounts.

    An agent with many delegations and high transfer out-degree is a potential
    hub for coordinated fund movement hidden behind AI delegation.

    Args:
        delegations: list of dicts with 'agent_id', 'principal_id', 'scope'.
        transfers: list of dicts with 'from_entity_id', 'to_entity_id', 'attributed_agent_id'.
        min_agent_out_degree: min distinct targets to flag.

    Returns:
        Evidence tuples for each abusive agent hub.
    """
    agent_principals: dict[str, set[str]] = defaultdict(set)
    for d in delegations:
        agent = d.get("agent_id")
        principal = d.get("principal_id")
        if agent and principal:
            agent_principals[agent].add(principal)

    agent_targets: dict[str, set[str]] = defaultdict(set)
    for t in transfers:
        agent = t.get("attributed_agent_id")
        dst = t.get("to_entity_id")
        if agent and dst:
            agent_targets[agent].add(dst)

    results: list[EvidenceTuple] = []
    for agent, targets in agent_targets.items():
        if len(targets) >= min_agent_out_degree:
            principals = agent_principals.get(agent, set())
            all_entities = {agent} | principals | targets
            results.append((
                "agentic_delegation_abuse",
                sorted(all_entities),
                {
                    "agent_id": agent,
                    "principal_count": len(principals),
                    "target_count": len(targets),
                    "principals": sorted(principals),
                },
            ))
    return results


def detect_commerce_abuse(
    orders: list[dict],
    refunds: list[dict],
    min_refund_rate: float = 0.6,
    min_order_count: int = 5,
) -> list[EvidenceTuple]:
    """Detect abuse patterns in agentic commerce: excessive refunds, chargeback rings.

    Args:
        orders: list of dicts with 'entity_id', 'order_id', 'amount'.
        refunds: list of dicts with 'entity_id', 'order_id', 'amount'.
        min_refund_rate: fraction of orders refunded to flag entity.
        min_order_count: minimum order count before evaluating refund rate.

    Returns:
        Evidence tuples for each entity with abusive refund rate.
    """
    entity_orders: dict[str, list[str]] = defaultdict(list)
    entity_refund_orders: dict[str, set[str]] = defaultdict(set)

    for o in orders:
        eid = o.get("entity_id")
        oid = o.get("order_id")
        if eid and oid:
            entity_orders[eid].append(oid)

    for r in refunds:
        eid = r.get("entity_id")
        oid = r.get("order_id")
        if eid and oid:
            entity_refund_orders[eid].add(oid)

    results: list[EvidenceTuple] = []
    for eid, order_ids in entity_orders.items():
        if len(order_ids) < min_order_count:
            continue
        refunded = entity_refund_orders.get(eid, set())
        rate = len(refunded & set(order_ids)) / len(order_ids)
        if rate >= min_refund_rate:
            results.append((
                "commerce_abuse",
                [eid],
                {
                    "entity_id": eid,
                    "order_count": len(order_ids),
                    "refund_count": len(refunded & set(order_ids)),
                    "refund_rate": round(rate, 4),
                },
            ))
    return results
