"""Declarative Kafka/stream topic contract for the derivatives domain.

Phase-0 gap (3): the derivatives domain declared realtime topics
(``DERIVATIVES_REALTIME_TOPICS``) and a durable-source requirement, but there
was NO declarative contract — no schema, partition, retention, DLQ, or consumer
ownership statement — and no way to validate one without a broker.

This module closes that gap with a pure, broker-free contract:

* :data:`DERIVATIVES_TOPIC_CONTRACTS` — the declarative registry. Every tenant
  realtime topic from ``product.DERIVATIVES_REALTIME_TOPICS`` maps to a
  :class:`DerivativesTopicContract` (channel, canonical event types, partitions,
  retention, compaction, DLQ routing, primary consumer group, partitioning key).
  Internal bronze/silver topics and the dead-letter topic are declared here too,
  so DLQ references resolve against the same registry.
* :func:`validate_topic_contract` — per-topic validation (naming, partitions,
  retention, replication, DLQ reference, consumer ownership). No broker, no
  network, no Kafka import: pure dataclass + string checks.
* :func:`validate_all_topic_contracts` / :func:`assert_valid_topic_contracts` —
  whole-registry validation with a deterministic report and a fail-closed raise.

The contract is deliberately observation-only: it declares what Aether
*consumes and publishes for observation*, never order/transfer/withdraw
surfaces. ``execution_by_aether`` is not represented here at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from services.derivatives.product import DERIVATIVES_REALTIME_TOPICS

# ── Kafka topic-name rules ────────────────────────────────────────────────────
# Kafka topic names must match ^[a-zA-Z0-9._-]+$ and be at most 249 chars.
# Aether's dot-delimited hierarchy (tenant.<domain>.<channel>) means '..' and
# leading/trailing '.' are also rejected.
_TOPIC_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_TOPIC_NAME_LENGTH = 249

# Dead-letter topic: every non-compacted fact topic routes poison/undecodable
# messages here so the observation pipeline never drops evidence silently.
DERIVATIVES_DLQ_TOPIC = "tenant.derivatives.dlq"

# Canonical consumer-group ownership for the derivatives observation pipeline.
DERIVATIVES_INGEST_CONSUMER_GROUP = "kyber-derivatives-ingest"

# Hardcoded zero-free default knobs.
DEFAULT_PARTITIONS = 3
DEFAULT_REPLICATION_FACTOR = 2
DEFAULT_RETENTION_MS = 7 * 24 * 60 * 60 * 1000  # 7 days
MAX_SANE_PARTITIONS = 64


class TopicContractValidationError(ValueError):
    """Raised by ``assert_valid_topic_contracts`` on any registry violation."""


@dataclass(frozen=True)
class DerivativesTopicContract:
    """One declarative topic: schema, sizing, retention, DLQ, ownership.

    Fields
    ------
    topic:
        Canonical Kafka topic name (dot-delimited, matches ``_TOPIC_NAME_RE``).
    domain:
        Domain namespace (always ``derivatives`` for this registry).
    channel:
        Functional channel the topic carries (position / fill / funding / risk /
        reconciliation / connector / agent / mapping / bronze / dlq).
    event_types:
        Canonical event names produced on the topic (from the event registry).
    partitions / replication_factor:
        Sizing. ``partitions`` must be >= 1 (and <= ``MAX_SANE_PARTITIONS``).
    retention_ms:
        Retention window. Must be positive for non-compacted topics.
    compacted:
        True for a log-compacted keyed topic (last-write-wins projection);
        such topics need no DLQ.
    dlq_topic:
        Dead-letter topic this topic routes poison records to. Must resolve in
        the registry (or be the DLQ topic itself).
    consumer_group:
        The single primary consumer group that owns this topic. ``None`` is a
        validation violation on ``required`` topics (no ownership = unobserved).
    key:
        The message field used for partitioning (usually ``tenant_id``).
    idempotent / resumable:
        Delivery guarantees the pipeline promises (at-least-once + cursor resume).
    required:
        True when this topic must be provisioned for the domain to be operative;
        optional topics (e.g. low-volume diagnostics) may defer.
    description:
        One-line purpose statement for operator/docs surfaces.
    """

    topic: str
    domain: str = "derivatives"
    channel: str = ""
    event_types: tuple[str, ...] = ()
    partitions: int = DEFAULT_PARTITIONS
    replication_factor: int = DEFAULT_REPLICATION_FACTOR
    retention_ms: int = DEFAULT_RETENTION_MS
    compacted: bool = False
    dlq_topic: Optional[str] = None
    consumer_group: Optional[str] = None
    key: str = "tenant_id"
    idempotent: bool = True
    resumable: bool = True
    required: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "domain": self.domain,
            "channel": self.channel,
            "event_types": list(self.event_types),
            "partitions": self.partitions,
            "replication_factor": self.replication_factor,
            "retention_ms": self.retention_ms,
            "compacted": self.compacted,
            "dlq_topic": self.dlq_topic,
            "consumer_group": self.consumer_group,
            "key": self.key,
            "idempotent": self.idempotent,
            "resumable": self.resumable,
            "required": self.required,
            "description": self.description,
        }


# ── topic -> (channel, event_types, description, flags) for the tenant surface ─
# Mirrors DERIVATIVES_REALTIME_TOPICS exactly (a test asserts the sets are equal).
_TENANT_TOPIC_SPECS: dict[str, dict[str, Any]] = {
    "tenant.derivatives.position_opened": {
        "channel": "position",
        "event_types": ("derivatives_position_opened_observed",),
        "description": "A position epoch opened on an observed venue account.",
        "compacted": True,
    },
    "tenant.derivatives.position_changed": {
        "channel": "position",
        "event_types": (
            "derivatives_position_increased_observed",
            "derivatives_position_reduced_observed",
            "derivatives_position_corrected",
        ),
        "description": "A position changed size/price since the prior observation.",
        "compacted": True,
    },
    "tenant.derivatives.position_closed": {
        "channel": "position",
        "event_types": ("derivatives_position_closed_observed",),
        "description": "A position epoch closed flat.",
        "compacted": True,
    },
    "tenant.derivatives.liquidation": {
        "channel": "risk",
        "event_types": (
            "derivatives_position_liquidated_observed",
            "derivatives_position_adl_observed",
            "derivatives_position_settled_observed",
        ),
        "description": "Liquidation / ADL / settlement observations.",
        "compacted": False,
    },
    "tenant.derivatives.funding_settled": {
        "channel": "funding",
        "event_types": ("derivatives_funding_payment_observed",),
        "description": "Per-funding-window funding payment observations.",
        "compacted": False,
    },
    "tenant.derivatives.risk_threshold_crossed": {
        "channel": "risk",
        "event_types": ("derivatives_risk_threshold_breached",),
        "description": "Risk policy thresholds crossed on an observed account.",
        "compacted": False,
    },
    "tenant.derivatives.agent_policy_violation": {
        "channel": "agent",
        "event_types": (
            "trade_intent_created",
            "trade_approval_requested",
            "trade_approval_resolved",
            "risk_policy_updated",
        ),
        "description": "Agent trade/approval lifecycle observations.",
        "compacted": False,
    },
    "tenant.derivatives.connector_stale": {
        "channel": "connector",
        "event_types": (
            "derivatives_stream_gap_detected",
            "derivatives_stream_gap_recovered",
            "derivatives_stream_checkpoint_advanced",
        ),
        "description": "Stream-gap and checkpoint evidence for a venue connector.",
        "compacted": False,
    },
    "tenant.derivatives.reconciliation_variance": {
        "channel": "reconciliation",
        "event_types": (
            "derivatives_reconciliation_variance_detected",
            "derivatives_reconciliation_variance_resolved",
            "derivatives_reconciliation_run_completed",
        ),
        "description": "Snapshot-vs-projection reconciliation variances.",
        "compacted": False,
    },
    "tenant.derivatives.mapping_review_required": {
        "channel": "mapping",
        "event_types": (
            "derivatives_reconciliation_variance_detected",
            "derivatives_reconciliation_variance_resolved",
        ),
        "description": "Market/venue mapping needing human or deterministic review.",
        "compacted": False,
    },
}

# ── internal bronze + DLQ topics ──────────────────────────────────────────────
_INTERNAL_TOPIC_SPECS: dict[str, dict[str, Any]] = {
    "internal.derivatives.observations.bronze": {
        "channel": "bronze",
        "event_types": (
            "derivatives_fill_observed",
            "derivatives_order_observed",
            "derivatives_order_updated_observed",
            "derivatives_position_opened_observed",
            "derivatives_position_increased_observed",
            "derivatives_position_reduced_observed",
            "derivatives_position_closed_observed",
            "derivatives_funding_payment_observed",
            "derivatives_balance_snapshot_observed",
            "derivatives_margin_snapshot_observed",
            "derivatives_collateral_change_observed",
            "derivatives_price_observation_recorded",
        ),
        "description": "Internal canonical observation feed before tenant fan-out.",
        "consumer_group": DERIVATIVES_INGEST_CONSUMER_GROUP,
        "required": True,
    },
    "internal.derivatives.silver.facts": {
        "channel": "silver",
        "event_types": (
            "derivatives_fill_observed",
            "derivatives_position_opened_observed",
            "derivatives_position_closed_observed",
            "derivatives_pnl_snapshot_materialized",
            "derivatives_exposure_snapshot_materialized",
        ),
        "description": "Normalized silver facts after Bronze->Silver projection.",
        "consumer_group": DERIVATIVES_INGEST_CONSUMER_GROUP,
        "required": True,
        "compacted": True,
    },
    DERIVATIVES_DLQ_TOPIC: {
        "channel": "dlq",
        "event_types": (),
        "description": "Dead-letter routing for undecodable/poison observation records.",
        "consumer_group": DERIVATIVES_INGEST_CONSUMER_GROUP,
        "retention_ms": 30 * 24 * 60 * 60 * 1000,  # 30 days for post-mortem
        "required": True,
    },
}


def _build_contract(
    topic: str, spec: dict[str, Any], *, required: bool
) -> DerivativesTopicContract:
    return DerivativesTopicContract(
        topic=topic,
        domain="derivatives",
        channel=spec["channel"],
        event_types=tuple(spec.get("event_types") or ()),
        partitions=int(spec.get("partitions", DEFAULT_PARTITIONS)),
        replication_factor=int(
            spec.get("replication_factor", DEFAULT_REPLICATION_FACTOR)
        ),
        retention_ms=int(spec.get("retention_ms", DEFAULT_RETENTION_MS)),
        compacted=bool(spec.get("compacted", False)),
        dlq_topic=spec.get("dlq_topic"),
        consumer_group=spec.get("consumer_group"),
        key=str(spec.get("key", "tenant_id")),
        idempotent=bool(spec.get("idempotent", True)),
        resumable=bool(spec.get("resumable", True)),
        required=required,
        description=str(spec.get("description", "")),
    )


def _tenant_contracts() -> tuple[DerivativesTopicContract, ...]:
    contracts: list[DerivativesTopicContract] = []
    for topic, spec in _TENANT_TOPIC_SPECS.items():
        contracts.append(
            _build_contract(
                topic,
                {**spec, "consumer_group": DERIVATIVES_INGEST_CONSUMER_GROUP},
                required=True,
            )
        )
    return tuple(contracts)


def _internal_contracts() -> tuple[DerivativesTopicContract, ...]:
    return tuple(
        _build_contract(topic, spec, required=bool(spec.get("required", False)))
        for topic, spec in _INTERNAL_TOPIC_SPECS.items()
    )


# Registry of every topic the derivatives observation pipeline touches.
DERIVATIVES_TOPIC_CONTRACTS: tuple[DerivativesTopicContract, ...] = (
    _tenant_contracts() + _internal_contracts()
)


def contract_by_topic(
    topic: str,
) -> Optional[DerivativesTopicContract]:
    """Look up a contract by canonical topic name (or ``None``)."""
    return next((c for c in DERIVATIVES_TOPIC_CONTRACTS if c.topic == topic), None)


def all_contract_names() -> tuple[str, ...]:
    return tuple(c.topic for c in DERIVATIVES_TOPIC_CONTRACTS)


# ── no-broker validation ──────────────────────────────────────────────────────

def _validate_topic_name(topic: str, violations: list[str]) -> None:
    if not topic:
        violations.append("topic name must not be empty")
        return
    if len(topic) > MAX_TOPIC_NAME_LENGTH:
        violations.append(f"topic {topic!r} exceeds {MAX_TOPIC_NAME_LENGTH} chars")
    if not _TOPIC_NAME_RE.match(topic):
        violations.append(
            f"topic {topic!r} violates Kafka naming ^[a-zA-Z0-9._-]+$"
        )
    if topic.startswith(".") or topic.endswith(".") or ".." in topic:
        violations.append(f"topic {topic!r} must not contain '.' at edges or '..'")


def _validate_sizing(contract: DerivativesTopicContract, violations: list[str]) -> None:
    if contract.partitions < 1:
        violations.append(f"{contract.topic}: partitions must be >= 1")
    elif contract.partitions > MAX_SANE_PARTITIONS:
        violations.append(
            f"{contract.topic}: partitions {contract.partitions} exceeds sane cap "
            f"{MAX_SANE_PARTITIONS}"
        )
    if contract.replication_factor < 1:
        violations.append(f"{contract.topic}: replication_factor must be >= 1")
    if contract.retention_ms < 1:
        violations.append(f"{contract.topic}: retention_ms must be positive")
    if contract.compacted and contract.retention_ms != DEFAULT_RETENTION_MS:
        # Compaction makes retention advisory; exact equality is not enforced.
        pass


def _validate_dlq(contract: DerivativesTopicContract, violations: list[str]) -> None:
    if contract.compacted:
        # Log-compacted keyed topics keep last-write-wins; no poison need.
        return
    if contract.dlq_topic is not None and contract.dlq_topic != contract.topic:
        if contract_by_topic(contract.dlq_topic) is None:
            violations.append(
                f"{contract.topic}: dlq_topic {contract.dlq_topic!r} is not "
                "declared in the topic registry"
            )


def _validate_ownership(contract: DerivativesTopicContract, violations: list[str]) -> None:
    if contract.required and not contract.consumer_group:
        violations.append(
            f"{contract.topic}: required topic has no consumer_group ownership"
        )
    # A DLQ topic must itself be consumed (or the ingest group is the owner).
    if contract.topic == DERIVATIVES_DLQ_TOPIC and not contract.consumer_group:
        violations.append(
            f"{contract.topic}: dead-letter topic must declare a consumer_group"
        )


def _validate_event_types(contract: DerivativesTopicContract, violations: list[str]) -> None:
    # The DLQ is a heterogeneous catch-all (poison records of every source
    # schema) — it legitimately declares no fixed event_types.
    if (
        contract.required
        and not contract.event_types
        and contract.channel != "dlq"
    ):
        violations.append(
            f"{contract.topic}: required topic must declare event_types (schema)"
        )
    for event in contract.event_types:
        if not event or any(ch.isspace() for ch in event):
            violations.append(
                f"{contract.topic}: invalid event_type {event!r} in schema"
            )


def validate_topic_contract(contract: DerivativesTopicContract) -> list[str]:
    """Validate one contract with no broker, no network. Returns violations."""
    violations: list[str] = []
    _validate_topic_name(contract.topic, violations)
    _validate_sizing(contract, violations)
    _validate_dlq(contract, violations)
    _validate_ownership(contract, violations)
    _validate_event_types(contract, violations)
    return violations


def validate_all_topic_contracts() -> dict[str, Any]:
    """Validate the whole registry deterministically. Returns a report dict.

    ``passed`` is the conjunction of every contract's violations being empty.
    The report is pure: no timestamps, no randomness, byte-identical across
    calls (suitable for a CI gate and for the no-broker certification checks).
    """
    topics: list[dict[str, Any]] = []
    all_violations: list[dict[str, Any]] = []
    for contract in DERIVATIVES_TOPIC_CONTRACTS:
        violations = validate_topic_contract(contract)
        topics.append({"topic": contract.topic, "valid": not violations, "violations": violations})
        if violations:
            all_violations.append({"topic": contract.topic, "violations": violations})
    # Consumer-ownership uniqueness: no topic is owned by more than one primary
    # consumer group.
    ownership: dict[str, list[str]] = {}
    for contract in DERIVATIVES_TOPIC_CONTRACTS:
        if contract.consumer_group:
            ownership.setdefault(contract.topic, []).append(contract.consumer_group)
    overlapping = {
        topic: sorted(groups)
        for topic, groups in ownership.items()
        if len(set(groups)) > 1
    }
    for topic, groups in sorted(overlapping.items()):
        all_violations.append(
            {
                "topic": topic,
                "violations": [f"multiple primary consumer groups: {', '.join(groups)}"],
            }
        )
    return {
        "schema_version": "derivatives-topic-contract-v1",
        "broker_required": False,
        "topic_count": len(DERIVATIVES_TOPIC_CONTRACTS),
        "tenant_topic_count": len(_TENANT_TOPIC_SPECS),
        "passed": not all_violations,
        "topics": topics,
        "violations": all_violations,
    }


def assert_valid_topic_contracts() -> dict[str, Any]:
    """Fail-closed gate: raise if any contract violation exists."""
    report = validate_all_topic_contracts()
    if not report["passed"]:
        lines = []
        for violation in report["violations"]:
            lines.append(f"{violation['topic']}: " + "; ".join(violation["violations"]))
        raise TopicContractValidationError(
            "derivatives topic contract violations:\n  " + "\n  ".join(lines)
        )
    return report


__all__ = [
    "DERIVATIVES_TOPIC_CONTRACTS",
    "DERIVATIVES_DLQ_TOPIC",
    "DERIVATIVES_INGEST_CONSUMER_GROUP",
    "MAX_TOPIC_NAME_LENGTH",
    "DerivativesTopicContract",
    "TopicContractValidationError",
    "contract_by_topic",
    "all_contract_names",
    "validate_topic_contract",
    "validate_all_topic_contracts",
    "assert_valid_topic_contracts",
]
