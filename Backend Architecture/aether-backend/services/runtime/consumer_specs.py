"""Canonical ownership registry for long-running event consumers.

The registry is intentionally declarative: production role selection and local
``all`` mode consume the same entries, preventing lifespan wiring from drifting
away from the documented process boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from services.runtime.roles import roles_in
from shared.events.events import Topic


AttachFactory = Callable[[Any], None]
EnabledPredicate = Callable[[Any], bool]


@dataclass(frozen=True)
class ConsumerSpec:
    """A stable, role-owned stream-consumer declaration."""

    name: str
    role: str
    topics: tuple[Topic, ...]
    group_id: str
    handler_factory: AttachFactory
    required: bool = True
    concurrency: int = 10
    max_in_flight: int = 10
    drain_timeout_s: float = 30.0
    max_handler_retries: int = 2
    readiness_dependency: str = "event_broker"
    enabled: EnabledPredicate = lambda _settings: True


def _attach_stream_ingestion(registry: Any) -> None:
    from services.ingestion.workers import (
        sdk_bronze_writer,
        silver_fact_projector,
        silver_normalizer,
    )

    for handler in (sdk_bronze_writer, silver_normalizer, silver_fact_projector):
        registry.consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, handler)


def _attach_identity(registry: Any) -> None:
    from functools import partial
    from services.ingestion.workers import identity_signal_emitter

    registry.consumer.subscribe(
        Topic.SDK_EVENTS_VALIDATED,
        partial(identity_signal_emitter, producer=registry.producer),
    )


def _attach_graph(registry: Any) -> None:
    from services.profile360_workers import attach_profile360_workers

    attach_profile360_workers(registry.consumer, registry.graph)


def _attach_measurement(registry: Any) -> None:
    from services.measurement.identity_consumer import MeasurementIdentityConsumer

    MeasurementIdentityConsumer(producer=registry.producer).register(registry.consumer)


def _attach_semantic(registry: Any) -> None:
    from services.semantic_intelligence.consumer import SemanticEventConsumer

    SemanticEventConsumer(producer=registry.producer).register(registry.consumer)


def _attach_semantic_identity(registry: Any) -> None:
    from services.semantic_intelligence.identity_consumer import SemanticIdentityConsumer

    SemanticIdentityConsumer().register(registry.consumer)


def _attach_notifications(registry: Any) -> None:
    from services.notification_intelligence.consumer import attach_notification_consumers

    attach_notification_consumers(
        registry.consumer,
        producer=registry.producer,
        cache=registry.cache,
    )


# ``ConsumerSpec.topics`` is a *truthful declaration* of everything the spec's
# handler_factory subscribes: it is the field anyone reasoning about ownership —
# or later building SNS filter policies — will read. The tuples below are
# therefore enumerated in full rather than summarised, and
# tests/unit/test_runtime_execution_groups.py asserts equality between what a
# spec declares and what its factory actually subscribes, so a handler added to
# one of these pipelines cannot silently escape its declaration.

# Notification-intelligence alert fan-in. Previously subscribed as a side effect
# of _attach_stream_ingestion, which left "stream-ingestion-projection"
# declaring one topic while subscribing sixteen.
NOTIFICATION_TOPICS: tuple[Topic, ...] = (
    Topic.AGENT_ESCALATION_RAISED,
    Topic.ANOMALY_DETECTED,
    Topic.CIS_QUARANTINE_ESCALATED,
    Topic.CIS_REASONING_CONTRADICTION_DETECTED,
    Topic.COMMERCE_APPROVAL_REQUESTED,
    Topic.DERIVATIVES_STREAM_GAP_STALLED,
    Topic.DERIVATIVES_VARIANCE_DETECTED,
    Topic.GOVERNANCE_DECISION_EVALUATED,
    Topic.INTEROP_MESSAGE_STUCK,
    Topic.INTEROP_SECURITY_POLICY_CHANGED,
    Topic.ML_EXTRACTION_ALERT_OPENED,
    Topic.ML_EXTRACTION_CLUSTER_ESCALATED,
    Topic.STABLECOIN_DEPEG_DETECTED,
    Topic.SUGGESTION_APPROVED,
    Topic.SUGGESTION_CREATED,
)

# Everything services.profile360_workers.attach_profile360_workers subscribes.
GRAPH_PROJECTION_TOPICS: tuple[Topic, ...] = (
    Topic.AGENT_EXECUTION_COMPLETED,
    Topic.AGENT_EXECUTION_FAILED,
    Topic.AGENT_EXECUTION_STARTED,
    Topic.BEHAVIOR_EVENT_RECORDED,
    Topic.BEHAVIOR_PATTERN_DETECTED,
    Topic.BEHAVIOR_SESSION_ENDED,
    Topic.BEHAVIOR_SESSION_STARTED,
    Topic.DELEGATION_CREATED,
    Topic.DELEGATION_REJECTED,
    Topic.DELEGATION_REVOKED,
    Topic.DELEGATION_VALIDATED,
    Topic.ENTITY_UPDATED,
    Topic.FLOW_TRANSFER,
    Topic.FRAUD_DECISION_CREATED,
    Topic.FRAUD_EVALUATION_COMPLETED,
    Topic.JOURNEY_ABANDONED,
    Topic.JOURNEY_ACTOR_JOINED,
    Topic.JOURNEY_ACTOR_LEFT,
    Topic.JOURNEY_CONVERTED,
    Topic.JOURNEY_STARTED,
    Topic.PROFILE_UPDATED,
)


CONSUMER_SPECS: tuple[ConsumerSpec, ...] = (
    ConsumerSpec(
        name="stream-ingestion-projection",
        role="stream-worker",
        topics=(Topic.SDK_EVENTS_VALIDATED,),
        group_id="aether-stream-ingestion",
        handler_factory=_attach_stream_ingestion,
    ),
    ConsumerSpec(
        name="notification-intelligence",
        role="stream-worker",
        topics=NOTIFICATION_TOPICS,
        # Deliberately the *same* group as stream-ingestion-projection: this
        # split makes the declaration honest, it does not create a new
        # subscription. Both specs stay co-resident on one consumer under either
        # keying mode, so no broker-visible topology changed.
        group_id="aether-stream-ingestion",
        handler_factory=_attach_notifications,
    ),
    ConsumerSpec(
        name="identity-signal-emission",
        role="identity-worker",
        topics=(Topic.SDK_EVENTS_VALIDATED,),
        group_id="aether-identity",
        handler_factory=_attach_identity,
    ),
    ConsumerSpec(
        name="graph-profile-projection",
        role="graph-writer",
        # The Profile 360 workers subscribe well beyond the four profile/
        # delegation topics this spec used to declare; enumerate them all.
        topics=GRAPH_PROJECTION_TOPICS,
        group_id="aether-graph-writer",
        handler_factory=_attach_graph,
    ),
    ConsumerSpec(
        name="measurement-identity-restatement",
        role="measurement-worker",
        topics=(Topic.IDENTITY_MERGED, Topic.IDENTITY_SPLIT),
        group_id="aether-measurement",
        handler_factory=_attach_measurement,
    ),
    ConsumerSpec(
        name="semantic-classification",
        role="semantic-worker",
        topics=(Topic.SDK_EVENTS_VALIDATED, Topic.CONSENT_UPDATED),
        group_id="aether-semantic",
        handler_factory=_attach_semantic,
    ),
    ConsumerSpec(
        name="semantic-identity-restatement",
        role="semantic-worker",
        topics=(Topic.IDENTITY_MERGED, Topic.IDENTITY_SPLIT),
        group_id="aether-semantic-identity",
        handler_factory=_attach_semantic_identity,
    ),
)


def consumer_specs_for_role(role: str, settings: Any) -> list[ConsumerSpec]:
    """Return enabled specs owned by ``role``, in canonical CONSUMER_SPECS order.

    ``role`` may be a single worker role (dedicated deployment), an execution
    group (consolidated deployment — the union over its members), or ``all``
    (local aggregation). Expansion goes through ``roles.roles_in`` so a
    consolidated process selects exactly the same specs its dedicated
    counterparts would, no more and no less.
    """
    members = roles_in(role)
    if not members:
        return []
    return [
        spec for spec in CONSUMER_SPECS if spec.role in members and spec.enabled(settings)
    ]


def attach_consumer_specs(registry: Any, specs: list[ConsumerSpec]) -> None:
    """Attach a selected set to ``registry.consumer`` with bounded processing.

    This is the *single-consumer* path used by the FastAPI lifespan (``api``
    / ``all``). Multi-queue deployments — any role selection spanning more than
    one ``(role, group_id)`` pair — must use
    ``services.runtime.consumer_runner`` instead, which gives each pair its own
    ``EventConsumer``, queue binding and backpressure. See that module for why
    a single consumer cannot honour more than one group.
    """
    if not specs:
        return
    apply_consumer_limits(registry.consumer, specs)
    # Dedicated replicas of a role share its stable group. ``all`` combines
    # pipelines only for local/test execution, where no broker group is used.
    groups = {spec.group_id for spec in specs}
    if len(groups) == 1:
        registry.consumer._group_id = next(iter(groups))
    for spec in specs:
        spec.handler_factory(registry)


def apply_consumer_limits(consumer: Any, specs: Sequence[ConsumerSpec]) -> None:
    """Apply the backpressure/retry envelope of ``specs`` onto ``consumer``.

    ``EventConsumer`` sizes its concurrency semaphore in ``__init__`` from the
    *class* default, so assigning ``MAX_CONCURRENT`` afterwards used to change
    the advertised limit while the semaphore kept enforcing the old one. Route
    every limit change through here so the enforced value and the reported
    value cannot diverge — this is what makes per-group backpressure real
    rather than nominal.
    """
    if not specs:
        return
    consumer.MAX_CONCURRENT = max(spec.concurrency for spec in specs)
    consumer.MAX_HANDLER_RETRIES = max(spec.max_handler_retries for spec in specs)
    resize = getattr(consumer, "resize_concurrency", None)
    if callable(resize):
        resize(consumer.MAX_CONCURRENT)


def drain_timeout_for(specs: Sequence[ConsumerSpec]) -> float:
    """Longest drain budget declared by ``specs`` (0.0 when empty).

    A group drains as slowly as its most patient member: cutting in-flight work
    short at the shortest budget would drop exactly the events the longer
    budget exists to protect.
    """
    return max((spec.drain_timeout_s for spec in specs), default=0.0)
