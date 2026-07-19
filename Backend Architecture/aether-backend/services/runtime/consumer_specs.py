"""Canonical ownership registry for long-running event consumers.

The registry is intentionally declarative: production role selection and local
``all`` mode consume the same entries, preventing lifespan wiring from drifting
away from the documented process boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

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
    _attach_notifications(registry)


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


def _attach_notifications(registry: Any) -> None:
    from services.notification_intelligence.consumer import attach_notification_consumers

    attach_notification_consumers(
        registry.consumer,
        producer=registry.producer,
        cache=registry.cache,
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
        name="identity-signal-emission",
        role="identity-worker",
        topics=(Topic.SDK_EVENTS_VALIDATED,),
        group_id="aether-identity",
        handler_factory=_attach_identity,
    ),
    ConsumerSpec(
        name="graph-profile-projection",
        role="graph-writer",
        topics=(
            Topic.PROFILE_UPDATED,
            Topic.ENTITY_UPDATED,
            Topic.DELEGATION_CREATED,
            Topic.DELEGATION_REVOKED,
        ),
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
        topics=(Topic.SDK_EVENTS_VALIDATED,),
        group_id="aether-semantic",
        handler_factory=_attach_semantic,
    ),
)


def consumer_specs_for_role(role: str, settings: Any) -> list[ConsumerSpec]:
    """Return enabled specs owned by ``role``; ``all`` is local aggregation."""
    if role == "api":
        return []
    return [
        spec
        for spec in CONSUMER_SPECS
        if (role == "all" or spec.role == role) and spec.enabled(settings)
    ]


def attach_consumer_specs(registry: Any, specs: list[ConsumerSpec]) -> None:
    """Attach a selected set and configure bounded consumer processing."""
    if not specs:
        return
    registry.consumer.MAX_CONCURRENT = max(spec.concurrency for spec in specs)
    registry.consumer.MAX_HANDLER_RETRIES = max(spec.max_handler_retries for spec in specs)
    # Dedicated replicas of a role share its stable group. ``all`` combines
    # pipelines only for local/test execution, where no broker group is used.
    groups = {spec.group_id for spec in specs}
    if len(groups) == 1:
        registry.consumer._group_id = next(iter(groups))
    for spec in specs:
        spec.handler_factory(registry)
