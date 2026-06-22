"""Fraud Network Intelligence — pure risk scoring functions.

All functions are stateless and take only primitive Python types.
No I/O, no async, no side effects. Scores are in range [0, 100] for
risk_score and [0, 1] for confidence_score.
"""

from __future__ import annotations


def score_entity_risk(
    fraud_score: float,
    transfer_volume_usd: float,
    shared_device_count: int,
    shared_ip_count: int,
    velocity_flag: bool,
    account_age_days: int,
) -> float:
    """Score an individual entity's fraud risk on a 0-100 scale.

    Weights:
        fraud_score (0-100)         → 35%
        transfer_volume (log-scaled) → 20%
        device sharing              → 15%
        ip sharing                  → 10%
        velocity flag               → 10%
        new account (<30 days)      → 10%
    """
    import math

    base = min(fraud_score, 100.0) * 0.35

    vol_norm = min(math.log1p(max(transfer_volume_usd, 0)) / math.log1p(1_000_000), 1.0)
    vol_contrib = vol_norm * 100.0 * 0.20

    device_contrib = min(shared_device_count, 10) / 10.0 * 100.0 * 0.15
    ip_contrib = min(shared_ip_count, 10) / 10.0 * 100.0 * 0.10
    velocity_contrib = 100.0 * 0.10 if velocity_flag else 0.0
    new_account_contrib = 100.0 * 0.10 if account_age_days < 30 else 0.0

    total = base + vol_contrib + device_contrib + ip_contrib + velocity_contrib + new_account_contrib
    return round(min(total, 100.0), 4)


def score_edge_risk(
    from_risk: float,
    to_risk: float,
    transfer_count: int,
    total_amount_usd: float,
    is_circular: bool,
    link_type: str,
) -> float:
    """Score a directed edge (transfer arc) in the fraud network on a 0-100 scale.

    Weights:
        endpoint risk average       → 30%
        transfer frequency          → 25%
        amount (log-scaled)         → 25%
        circularity bonus           → 10%
        link type severity          → 10%
    """
    import math

    endpoint_avg = (from_risk + to_risk) / 2.0
    endpoint_contrib = endpoint_avg * 0.30

    freq_norm = min(transfer_count / 100.0, 1.0)
    freq_contrib = freq_norm * 100.0 * 0.25

    amt_norm = min(math.log1p(max(total_amount_usd, 0)) / math.log1p(1_000_000), 1.0)
    amt_contrib = amt_norm * 100.0 * 0.25

    circular_contrib = 100.0 * 0.10 if is_circular else 0.0

    high_risk_links = {"LINKED_BY_DEVICE", "LINKED_BY_IP", "MEMBER_OF_FRAUD_NETWORK", "USES_MULE"}
    link_contrib = 100.0 * 0.10 if link_type in high_risk_links else 50.0 * 0.10

    total = endpoint_contrib + freq_contrib + amt_contrib + circular_contrib + link_contrib
    return round(min(total, 100.0), 4)


def score_path_risk(
    hop_count: int,
    path_entity_risk_scores: list[float],
    contains_cycle: bool,
    passes_through_mule: bool,
    total_amount_usd: float,
) -> float:
    """Score a multi-hop transfer path on a 0-100 scale.

    Weights:
        average entity risk         → 35%
        path length (more hops = more risk for layering) → 20%
        cycle detection             → 20%
        mule node presence          → 15%
        amount (log-scaled)         → 10%
    """
    import math

    avg_entity_risk = (
        sum(path_entity_risk_scores) / len(path_entity_risk_scores)
        if path_entity_risk_scores else 50.0
    )
    entity_contrib = avg_entity_risk * 0.35

    depth_norm = min(hop_count / 10.0, 1.0)
    depth_contrib = depth_norm * 100.0 * 0.20

    cycle_contrib = 100.0 * 0.20 if contains_cycle else 0.0
    mule_contrib = 100.0 * 0.15 if passes_through_mule else 0.0

    amt_norm = min(math.log1p(max(total_amount_usd, 0)) / math.log1p(1_000_000), 1.0)
    amt_contrib = amt_norm * 100.0 * 0.10

    total = entity_contrib + depth_contrib + cycle_contrib + mule_contrib + amt_contrib
    return round(min(total, 100.0), 4)


def score_cluster_risk(
    member_risk_scores: list[float],
    edge_risk_scores: list[float],
    cycle_count: int,
    signal_count: int,
    network_type: str,
) -> float:
    """Score an entire fraud cluster on a 0-100 scale.

    Weights:
        average member risk         → 30%
        average edge risk           → 25%
        cycle density               → 20%
        signal breadth              → 15%
        network type severity       → 10%
    """
    avg_member = (
        sum(member_risk_scores) / len(member_risk_scores) if member_risk_scores else 50.0
    )
    member_contrib = avg_member * 0.30

    avg_edge = (
        sum(edge_risk_scores) / len(edge_risk_scores) if edge_risk_scores else 50.0
    )
    edge_contrib = avg_edge * 0.25

    cycle_norm = min(cycle_count / 10.0, 1.0)
    cycle_contrib = cycle_norm * 100.0 * 0.20

    signal_norm = min(signal_count / 8.0, 1.0)
    signal_contrib = signal_norm * 100.0 * 0.15

    high_severity_types = {
        "mule_network",
        "layering_network",
        "smurfing_network",
        "delegation_abuse_cluster",
        "account_takeover_cluster",
        "synthetic_identity_ring",
    }
    type_contrib = 100.0 * 0.10 if network_type in high_severity_types else 60.0 * 0.10

    total = member_contrib + edge_contrib + cycle_contrib + signal_contrib + type_contrib
    return round(min(total, 100.0), 4)


def score_confidence(
    evidence_count: int,
    signal_overlap: int,
    member_count: int,
    has_circular_transfer: bool,
    has_shared_device: bool,
) -> float:
    """Compute a confidence score in [0, 1] for a fraud cluster hypothesis.

    Higher confidence when more independent signals corroborate each other.

    Weights:
        evidence breadth (0-20 items) → 30%
        signal overlap (independent signals)→ 25%
        member count (2-50)           → 20%
        circular transfer present     → 15%
        device sharing present        → 10%
    """
    evidence_norm = min(evidence_count / 20.0, 1.0)
    evidence_contrib = evidence_norm * 0.30

    signal_norm = min(signal_overlap / 5.0, 1.0)
    signal_contrib = signal_norm * 0.25

    member_norm = min(max(member_count - 1, 0) / 49.0, 1.0)
    member_contrib = member_norm * 0.20

    circular_contrib = 0.15 if has_circular_transfer else 0.0
    device_contrib = 0.10 if has_shared_device else 0.0

    total = evidence_contrib + signal_contrib + member_contrib + circular_contrib + device_contrib
    return round(min(total, 1.0), 4)
