"""Consolidated ``lean-worker`` execution group — behavioural guarantees.

``production-lean`` packs all eight logical worker roles into one task instead
of eight. These tests exist to prove that packing changed the *process
boundary* and nothing else: every logical role must keep its own queue,
consumer group, backpressure envelope, DLQ, retry policy, metrics label and
independent failure/restart behaviour, and the whole thing must stay
concurrent rather than degenerating into a serial loop.

Real machinery throughout — real ``EventConsumer`` instances, the real
``WorkerSupervisor``, the real ``ConsumerSpec`` registry. The only stubbed
boundary is the AWS SDK client factory, because binding an actual SQS queue is
not a unit test.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

BACKEND = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from config.settings import Environment  # noqa: E402
from services.runtime import run_role  # noqa: E402
from services.runtime.consumer_runner import (  # noqa: E402
    ConsumerLoopExited,
    ConsumerRunner,
    build_consumer_runners,
    consumer_runner_status,
    drain_consumer_runners,
    resolve_queue_url,
    role_queue_urls,
    start_consumer_runners,
)
from services.runtime.consumer_specs import (  # noqa: E402
    CONSUMER_SPECS,
    ConsumerSpec,
    attach_consumer_specs,
    consumer_specs_for_role,
)
from services.runtime.roles import (  # noqa: E402
    ALL_ROLES,
    EXECUTION_GROUPS,
    ROLE_TO_SPEC_NAMES,
    WORKER_ROLES,
    is_execution_group,
    is_valid_role,
    is_worker_role,
    owning_role,
    roles_in,
    should_start_consumers,
    should_start_workers,
    specs_for_role,
)
from services.runtime.supervisor import WorkerSpec, WorkerSupervisor  # noqa: E402
from shared.events.events import (  # noqa: E402
    DLQPublishError,
    Event,
    EventConsumer,
    Topic,
)
import services.runtime.supervisor as supervisor_mod  # noqa: E402
import shared.events.events as events_mod  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_event_env(monkeypatch):
    """Pin the broker environment so tests never inherit a real bus.

    Every test here starts from local/in-memory and opts *in* to a broker mode,
    rather than inheriting whatever KAFKA_BOOTSTRAP_SERVERS / EVENT_BROKER the
    developer's shell happens to export.
    """
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    monkeypatch.delenv("EVENT_BROKER", raising=False)
    monkeypatch.delenv("SQS_QUEUE_URL", raising=False)
    monkeypatch.delenv("SQS_DLQ_QUEUE_URL", raising=False)
    monkeypatch.delenv("SQS_ROLE_QUEUE_URLS", raising=False)


class _FakeRegistry:
    """Stand-in for ResourceRegistry: a real consumer, inert shared resources.

    The consumer runners never use ``self.consumer`` — proving that is part of
    the point — but handler factories reach for producer/cache/graph, so those
    have to resolve to something stable.
    """

    def __init__(self) -> None:
        self.consumer = EventConsumer()
        self.producer = object()
        self.cache = object()
        self.graph = object()


class _FakeSettings:
    """ConsumerSpec.enabled predicates only ever receive settings; none read it."""


class _MetricsRecorder:
    """Records metrics.increment calls so label content can be asserted."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def increment(self, name: str, value: int = 1, labels=None) -> None:
        self.calls.append((name, dict(labels or {})))

    def labels_for(self, name: str) -> list[dict]:
        return [labels for metric, labels in self.calls if metric == name]


# The per-role queue map production-lean supplies. Keyed by role and only by
# role, mirroring modules/sqs/main.tf, which provisions one aws_sqs_queue.role
# per entry of var.consumer_role_queues.
_QUEUE_MAP = {
    "stream-worker": "https://sqs.test/stream",
    "identity-worker": "https://sqs.test/identity",
    "graph-writer": "https://sqs.test/graph",
    "measurement-worker": "https://sqs.test/measurement",
    "semantic-worker": "https://sqs.test/semantic",
}


async def _forever() -> None:
    await asyncio.Event().wait()


async def _wait_for(predicate, timeout: float = 5.0, interval: float = 0.005) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    pytest.fail("condition not reached within timeout")


def _all_spec_names() -> list[str]:
    names: list[str] = []
    for spec_names in ROLE_TO_SPEC_NAMES.values():
        names.extend(spec_names)
    return sorted(names)


def _make_spec(
    name: str,
    role: str,
    group_id: str,
    topics: tuple,
    handler,
    *,
    concurrency: int = 10,
    max_handler_retries: int = 2,
    drain_timeout_s: float = 30.0,
) -> ConsumerSpec:
    """A ConsumerSpec whose factory really subscribes ``handler`` to ``topics``."""

    def _attach(registry) -> None:
        for topic in topics:
            registry.consumer.subscribe(topic, handler)

    return ConsumerSpec(
        name=name,
        role=role,
        topics=topics,
        group_id=group_id,
        handler_factory=_attach,
        concurrency=concurrency,
        max_handler_retries=max_handler_retries,
        drain_timeout_s=drain_timeout_s,
    )


def _event(topic: Topic = Topic.SDK_EVENTS_VALIDATED, **payload) -> Event:
    return Event(topic=topic, tenant_id="t1", source_service="test", payload=payload)


# ── role expansion: the pinned contract ──────────────────────────────────────


def test_lean_worker_is_a_valid_non_worker_execution_group():
    assert is_valid_role("lean-worker") is True
    assert is_execution_group("lean-worker") is True
    # It is a deployment token, not a class of work: it owns no specs itself.
    assert is_worker_role("lean-worker") is False
    assert "lean-worker" in ALL_ROLES
    assert ALL_ROLES == WORKER_ROLES | {"api", "all"} | frozenset(EXECUTION_GROUPS)


def test_roles_in_expansion_matches_contract():
    assert roles_in("lean-worker") == WORKER_ROLES
    assert roles_in("all") == WORKER_ROLES
    assert roles_in("maintenance") == frozenset({"maintenance"})
    assert roles_in("api") == frozenset()
    assert roles_in("bogus") == frozenset()


def test_owning_role_reverse_lookup():
    assert owning_role("retention_sweep") == "maintenance"
    assert owning_role("event_replay") == "stream-worker"
    assert owning_role("kyber_graph_projector") == "graph-writer"
    assert owning_role("notification_outbox") == "outbox-relay"
    assert owning_role("not-a-spec") is None
    # Every declared spec resolves back to exactly the role that declared it.
    for role, spec_names in ROLE_TO_SPEC_NAMES.items():
        for spec_name in spec_names:
            assert owning_role(spec_name) == role


def test_lean_worker_owns_the_union_of_every_dedicated_role():
    names = _all_spec_names()
    lean = set(specs_for_role("lean-worker", names))
    dedicated = set()
    for role in WORKER_ROLES:
        dedicated |= set(specs_for_role(role, names))
    assert lean == dedicated == set(names)


def test_lean_worker_consumer_specs_equal_union_of_dedicated_roles():
    settings = _FakeSettings()
    lean = consumer_specs_for_role("lean-worker", settings)
    dedicated = []
    for role in sorted(WORKER_ROLES):
        dedicated.extend(consumer_specs_for_role(role, settings))
    assert {s.name for s in lean} == {s.name for s in dedicated}
    # All five consumer roles are represented; nothing was dropped by packing.
    assert {s.role for s in lean} == {
        "stream-worker",
        "identity-worker",
        "graph-writer",
        "measurement-worker",
        "semantic-worker",
    }


def test_execution_group_gates_match_a_dedicated_fleet():
    assert should_start_workers("lean-worker") is True
    assert should_start_consumers("lean-worker") is True
    # Unchanged for everything that existed before.
    assert should_start_workers("api") is False
    assert should_start_consumers("api") is False
    assert should_start_consumers("maintenance") is False
    assert should_start_consumers("all") is True


# ── queue / group / backpressure isolation ───────────────────────────────────


def test_queue_url_resolves_by_role_then_falls_back(monkeypatch):
    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.test/fallback")
    mapping = {"semantic-worker": "https://sqs.test/semantic"}
    assert resolve_queue_url("semantic-worker", mapping=mapping) == "https://sqs.test/semantic"
    # A role with no entry falls back to the single-queue variable, which is
    # still correct for a dedicated deployment.
    assert resolve_queue_url("maintenance", mapping=mapping) == "https://sqs.test/fallback"


def test_role_queue_urls_parses_env(monkeypatch):
    monkeypatch.setenv("SQS_ROLE_QUEUE_URLS", json.dumps(_QUEUE_MAP))
    assert role_queue_urls() == _QUEUE_MAP


def test_role_queue_urls_fails_closed_on_malformed_json(monkeypatch):
    # Degrading to the single-queue fallback would bind every role to one queue
    # — exactly the outage this map exists to prevent.
    monkeypatch.setenv("SQS_ROLE_QUEUE_URLS", "{not json")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        role_queue_urls()
    monkeypatch.setenv("SQS_ROLE_QUEUE_URLS", '["a", "b"]')
    with pytest.raises(RuntimeError, match="JSON object"):
        role_queue_urls()


def test_every_consumer_spec_declares_exactly_what_it_subscribes():
    """``ConsumerSpec.topics`` must be a truthful declaration, not a summary.

    It is the field anyone would use to build SNS filter policies or to reason
    about ownership, so an under-declaring spec is a latent delivery bug.
    """
    for spec in CONSUMER_SPECS:
        registry = _FakeRegistry()
        spec.handler_factory(registry)
        subscribed = set(registry.consumer._handlers)
        declared = set(spec.topics)
        assert declared == subscribed, (
            f"{spec.name} declares {sorted(t.value for t in declared - subscribed)} "
            f"it does not subscribe and subscribes "
            f"{sorted(t.value for t in subscribed - declared)} it does not declare"
        )


def test_sqs_mode_binds_one_consumer_per_role_queue():
    registry = _FakeRegistry()
    specs = consumer_specs_for_role("lean-worker", _FakeSettings())
    runners = build_consumer_runners(
        registry, specs, broker="sns_sqs", queue_urls=_QUEUE_MAP
    )

    # One runner per consumer role — five, matching the five provisioned queues.
    assert len(runners) == 5
    assert {r.role for r in runners} == set(_QUEUE_MAP)
    assert len({id(r.consumer) for r in runners}) == 5
    assert all(r.consumer is not registry.consumer for r in runners)

    for runner in runners:
        assert runner.queue_url == _QUEUE_MAP[runner.role]
        # A real group is pinned, never the env-default fallback group.
        assert runner.consumer.group_id == runner.group_id
        assert not runner.consumer.group_id.startswith("aether-backend-")
        # Every topic the role's specs declare is subscribed on that one
        # consumer, so nothing on the role queue arrives unhandled.
        declared = set()
        for spec in runner.specs:
            declared |= set(spec.topics)
        assert set(runner.consumer._handlers) == declared


def test_sqs_mode_gives_semantic_worker_one_consumer_carrying_both_groups():
    """Regression: two consumers on one SQS queue silently drop messages.

    SQS has no consumer groups — the two would compete for the queue, and
    whichever received a message it had no handler for would delete it.
    """
    specs = consumer_specs_for_role("semantic-worker", _FakeSettings())
    assert len({s.group_id for s in specs}) == 2

    runners = build_consumer_runners(
        _FakeRegistry(), specs, broker="sns_sqs", queue_urls=_QUEUE_MAP
    )
    assert len(runners) == 1
    runner = runners[0]
    assert runner.queue_url == "https://sqs.test/semantic"
    # Both group's handler sets live on the single queue-bound consumer, so
    # every event delivered to the role queue has a handler.
    assert set(runner.consumer._handlers) == {
        Topic.SDK_EVENTS_VALIDATED,
        Topic.CONSENT_UPDATED,
        Topic.IDENTITY_MERGED,
        Topic.IDENTITY_SPLIT,
    }
    # Both logical groups stay visible for observability.
    assert set(runner.group_ids) == {"aether-semantic", "aether-semantic-identity"}
    assert set(runner.spec_names) == {
        "semantic-classification", "semantic-identity-restatement"
    }


def test_kafka_mode_gives_semantic_worker_two_independent_consumers():
    """A Kafka consumer group IS an independent subscription, so split there."""
    specs = consumer_specs_for_role("semantic-worker", _FakeSettings())
    runners = build_consumer_runners(_FakeRegistry(), specs, broker="kafka", queue_urls={})

    assert len(runners) == 2
    assert {r.group_id for r in runners} == {"aether-semantic", "aether-semantic-identity"}
    assert {r.role for r in runners} == {"semantic-worker"}
    by_group = {r.group_id: r for r in runners}
    # Each group receives a full copy of its topics, so the sets stay disjoint.
    assert set(by_group["aether-semantic"].consumer._handlers) == {
        Topic.SDK_EVENTS_VALIDATED, Topic.CONSENT_UPDATED
    }
    assert set(by_group["aether-semantic-identity"].consumer._handlers) == {
        Topic.IDENTITY_MERGED, Topic.IDENTITY_SPLIT
    }
    # No queue binding under kafka; the binding is bootstrap + group.
    assert all(r.queue_url == "" for r in runners)


def test_no_two_consumers_in_a_process_ever_share_a_queue():
    """The invariant the whole module exists to uphold."""
    for broker in ("sns_sqs", "kafka"):
        runners = build_consumer_runners(
            _FakeRegistry(), consumer_specs_for_role("lean-worker", _FakeSettings()),
            broker=broker, queue_urls=_QUEUE_MAP,
        )
        bound = [r.queue_url for r in runners if r.queue_url]
        assert len(bound) == len(set(bound)), f"{broker}: consumers share a queue"


def test_colliding_queue_configuration_fails_closed(monkeypatch):
    # Two roles, no per-role map: both fall back to the one SQS_QUEUE_URL.
    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.test/only-one")
    specs = consumer_specs_for_role("lean-worker", _FakeSettings())
    with pytest.raises(RuntimeError, match="consumer queue collision"):
        build_consumer_runners(_FakeRegistry(), specs, broker="sns_sqs", queue_urls={})


def test_co_hosting_does_not_cross_contaminate_handler_sets():
    """A role's consumer must carry exactly the handlers it would run alone.

    The real isolation property: building every pipeline in one process must
    produce identical handler sets to building each in its own process.
    """
    settings = _FakeSettings()
    for broker in ("sns_sqs", "kafka"):
        together = {
            (r.role, r.group_id): set(r.consumer._handlers)
            for r in build_consumer_runners(
                _FakeRegistry(), consumer_specs_for_role("lean-worker", settings),
                broker=broker, queue_urls=_QUEUE_MAP,
            )
        }
        alone: dict[tuple[str, str], set] = {}
        for role in sorted(WORKER_ROLES):
            for runner in build_consumer_runners(
                _FakeRegistry(), consumer_specs_for_role(role, settings),
                broker=broker, queue_urls=_QUEUE_MAP,
            ):
                alone[(runner.role, runner.group_id)] = set(runner.consumer._handlers)

        assert set(together) == set(alone), broker
        for key, topics in together.items():
            assert topics == alone[key], f"{broker}: {key} changed under consolidation"


def test_distinct_roles_do_not_share_topic_handlers():
    runners = {
        r.role: r
        for r in build_consumer_runners(
            _FakeRegistry(), consumer_specs_for_role("lean-worker", _FakeSettings()),
            broker="sns_sqs", queue_urls=_QUEUE_MAP,
        )
    }
    identity = runners["identity-worker"]
    measurement = runners["measurement-worker"]

    assert set(identity.consumer._handlers) == {Topic.SDK_EVENTS_VALIDATED}
    assert set(measurement.consumer._handlers) == {Topic.IDENTITY_MERGED, Topic.IDENTITY_SPLIT}
    # Identity and measurement never see each other's traffic.
    assert Topic.IDENTITY_MERGED not in identity.consumer._handlers
    assert Topic.SDK_EVENTS_VALIDATED not in measurement.consumer._handlers
    # And each is bound to its own queue.
    assert identity.queue_url != measurement.queue_url


def test_queue_url_reaches_the_event_consumer_constructor():
    registry = _FakeRegistry()
    seen: list[tuple[str, str]] = []

    def _recording_factory(*, group_id: str, queue_url: str) -> EventConsumer:
        seen.append((group_id, queue_url))
        return EventConsumer(group_id=group_id, queue_url=queue_url)

    specs = consumer_specs_for_role("lean-worker", _FakeSettings())
    build_consumer_runners(
        registry, specs, broker="sns_sqs", queue_urls=_QUEUE_MAP,
        consumer_factory=_recording_factory,
    )
    assert ("aether-identity", "https://sqs.test/identity") in seen
    assert ("aether-semantic", "https://sqs.test/semantic") in seen


def test_semantic_worker_group_no_longer_falls_back_to_the_default_group():
    """Regression: the shared-consumer path left both groups unpinned."""
    settings = _FakeSettings()
    specs = consumer_specs_for_role("semantic-worker", settings)
    assert len({s.group_id for s in specs}) == 2

    # Old path: attach_consumer_specs refuses to pin when specs disagree, so the
    # consumer silently keeps the env-default aether-backend-<env> group.
    shared = _FakeRegistry()
    attach_consumer_specs(shared, specs)
    assert shared.consumer.group_id.startswith("aether-backend-")

    # New path: a real group is pinned under either keying mode.
    for broker in ("sns_sqs", "kafka"):
        for runner in build_consumer_runners(
            _FakeRegistry(), specs, broker=broker, queue_urls=_QUEUE_MAP
        ):
            assert not runner.consumer.group_id.startswith("aether-backend-")
            assert runner.consumer.group_id in {
                "aether-semantic", "aether-semantic-identity"
            }


def test_dedicated_role_still_produces_exactly_one_runner(monkeypatch):
    """production-scale / enterprise-isolated behaviour must be unchanged."""
    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.test/only")
    for role in ("stream-worker", "identity-worker", "graph-writer",
                 "measurement-worker", "semantic-worker"):
        runners = build_consumer_runners(
            _FakeRegistry(), consumer_specs_for_role(role, _FakeSettings()),
            broker="sns_sqs",
        )
        # One process, one role, one queue — no collision, no split.
        assert len(runners) == 1
        assert runners[0].role == role
        assert runners[0].queue_url == "https://sqs.test/only"


def test_each_group_gets_its_own_backpressure_budget():
    """A global max would hand every co-hosted role the same budget."""

    async def _handler(event):
        return None

    specs = [
        _make_spec(
            "slow", "measurement-worker", "g-slow",
            (Topic.SDK_EVENTS_VALIDATED,), _handler, concurrency=2,
            max_handler_retries=1,
        ),
        _make_spec(
            "fast", "stream-worker", "g-fast",
            (Topic.SDK_EVENTS_VALIDATED,), _handler, concurrency=7,
            max_handler_retries=4,
        ),
    ]
    by_role = {
        r.role: r for r in build_consumer_runners(_FakeRegistry(), specs, queue_urls={})
    }
    slow, fast = by_role["measurement-worker"], by_role["stream-worker"]

    assert slow.consumer.MAX_CONCURRENT == 2
    assert fast.consumer.MAX_CONCURRENT == 7
    # Retry policy is per-group too, not a process-wide maximum.
    assert slow.consumer.MAX_HANDLER_RETRIES == 1
    assert fast.consumer.MAX_HANDLER_RETRIES == 4
    assert slow.status()["max_concurrent"] == 2
    assert fast.status()["max_concurrent"] == 7


async def test_per_group_backpressure_bounds_concurrent_handlers():
    registry = _FakeRegistry()
    peak = {"n": 0}
    live = {"n": 0}

    async def _handler(event):
        live["n"] += 1
        peak["n"] = max(peak["n"], live["n"])
        await asyncio.sleep(0.02)
        live["n"] -= 1

    spec = _make_spec(
        "bounded", "measurement-worker", "g-bounded",
        (Topic.SDK_EVENTS_VALIDATED,), _handler, concurrency=3,
    )
    runner = build_consumer_runners(registry, [spec], queue_urls={})[0]

    await asyncio.gather(*(runner.consumer.process(_event(i=i)) for i in range(12)))
    # Enforced by the resized semaphore. Before the fix the semaphore kept the
    # class default of 10 while MAX_CONCURRENT advertised 3.
    assert peak["n"] <= 3
    assert peak["n"] > 1, "handlers must run concurrently, not serially"


async def test_roles_process_concurrently_not_as_a_serial_loop():
    """Two logical roles must make progress at the same time."""
    registry = _FakeRegistry()
    order: list[str] = []

    def _handler(tag):
        async def _run(event):
            order.append(f"{tag}-start")
            await asyncio.sleep(0.05)
            order.append(f"{tag}-end")

        return _run

    specs = [
        _make_spec("a", "stream-worker", "g-a", (Topic.SDK_EVENTS_VALIDATED,), _handler("a")),
        _make_spec("b", "graph-writer", "g-b", (Topic.PROFILE_UPDATED,), _handler("b")),
    ]
    runners = build_consumer_runners(registry, specs, queue_urls={})
    a, b = runners[0], runners[1]

    await asyncio.gather(
        a.consumer.process(_event(Topic.SDK_EVENTS_VALIDATED)),
        b.consumer.process(_event(Topic.PROFILE_UPDATED)),
    )
    # Interleaved: both started before either finished. A serial loop would give
    # a-start, a-end, b-start, b-end.
    assert order[:2] == ["a-start", "b-start"] or order[:2] == ["b-start", "a-start"]
    assert set(order[2:]) == {"a-end", "b-end"}


# ── every logical role starts under lean-worker ──────────────────────────────


async def test_every_logical_role_starts_under_lean_worker():
    registry = _FakeRegistry()
    raw_specs = [WorkerSpec(name=name, factory=_forever) for name in _all_spec_names()]
    specs = run_role._stamp_owning_roles(raw_specs, "lean-worker")
    runners = build_consumer_runners(
        registry, consumer_specs_for_role("lean-worker", _FakeSettings()),
        queue_urls=_QUEUE_MAP,
    )

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    for spec in specs:
        supervisor.register(spec)
    for runner in runners:
        supervisor.register(runner.worker_spec())

    await start_consumer_runners(runners)
    await supervisor.start_all()
    try:
        by_role = supervisor.status_by_role()
        # All eight logical roles are represented and healthy in one process.
        assert set(by_role) == set(WORKER_ROLES)
        for role, health in by_role.items():
            assert health["healthy"] is True, f"{role} unhealthy: {health}"
            assert health["workers"], f"{role} has no workers"
        # Each supervised entry is attributed to a real role, never the token.
        for info in supervisor.status().values():
            assert info["role"] in WORKER_ROLES
    finally:
        await drain_consumer_runners(runners)
        await supervisor.stop_all()


def test_stamping_attributes_specs_to_owners_not_the_boot_token():
    raw = [
        WorkerSpec(name="retention_sweep", factory=_forever),
        WorkerSpec(name="event_replay", factory=_forever),
        WorkerSpec(name="unclaimed_spec", factory=_forever),
    ]
    stamped = {s.name: s.role for s in run_role._stamp_owning_roles(raw, "lean-worker")}
    assert stamped["retention_sweep"] == "maintenance"
    assert stamped["event_replay"] == "stream-worker"
    # A spec no role claims falls back to the boot token rather than being
    # silently misattributed to some role that does not own it.
    assert stamped["unclaimed_spec"] == "lean-worker"


# ── duplicate registration ───────────────────────────────────────────────────


def test_duplicate_runner_registration_raises():
    registry = _FakeRegistry()
    runner = build_consumer_runners(
        registry, consumer_specs_for_role("identity-worker", _FakeSettings()),
        queue_urls=_QUEUE_MAP,
    )[0]
    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(runner.worker_spec())
    with pytest.raises(ValueError, match="duplicate worker name"):
        supervisor.register(runner.worker_spec())


def test_runner_names_are_unique_across_the_whole_group():
    """Packing 8 roles into one supervisor must not collide any worker name."""
    registry = _FakeRegistry()
    runners = build_consumer_runners(
        registry, consumer_specs_for_role("lean-worker", _FakeSettings()),
        queue_urls=_QUEUE_MAP,
    )
    specs = run_role._stamp_owning_roles(
        [WorkerSpec(name=n, factory=_forever) for n in _all_spec_names()], "lean-worker"
    )
    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    for spec in specs:
        supervisor.register(spec)
    for runner in runners:
        supervisor.register(runner.worker_spec())
    assert len(supervisor.status()) == len(specs) + len(runners)


def test_runner_rejects_empty_spec_set():
    with pytest.raises(ValueError, match="at least one spec"):
        ConsumerRunner(role="maintenance", group_id="g", specs=[], registry=_FakeRegistry())


# ── failure isolation ────────────────────────────────────────────────────────


async def test_one_role_terminal_failure_does_not_kill_the_others(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(supervisor_mod, "metrics", recorder)

    async def _doomed():
        raise RuntimeError("measurement pipeline exploded")

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(
        WorkerSpec(
            name="measurement_loop", factory=_doomed, role="measurement-worker",
            max_restarts=0,
        )
    )
    supervisor.register(WorkerSpec(name="retention_sweep", factory=_forever, role="maintenance"))
    supervisor.register(WorkerSpec(name="event_replay", factory=_forever, role="stream-worker"))

    await supervisor.start_all()
    try:
        await _wait_for(
            lambda: supervisor.status()["measurement_loop"]["state"] == "failed"
        )
        by_role = supervisor.status_by_role()
        # The crashed role is surfaced as unhealthy...
        assert by_role["measurement-worker"]["healthy"] is False
        assert by_role["measurement-worker"]["failed"] == ["measurement_loop"]
        # ...and the co-hosted roles are untouched and still running.
        assert by_role["maintenance"]["healthy"] is True
        assert by_role["stream-worker"]["healthy"] is True
        assert supervisor.status()["retention_sweep"]["state"] == "running"
        assert supervisor.status()["event_replay"]["state"] == "running"

        # Surfaced as a metric and carrying the owning role, not the boot token.
        crash_labels = recorder.labels_for("worker_supervisor_crash")
        assert {"worker": "measurement_loop", "role": "measurement-worker"} in crash_labels
        failed_labels = recorder.labels_for("worker_supervisor_failed")
        assert {"worker": "measurement_loop", "role": "measurement-worker"} in failed_labels
        # No crash was attributed to the healthy roles.
        assert all(lbl["role"] == "measurement-worker" for lbl in crash_labels)
    finally:
        await supervisor.stop_all()


async def test_crashed_role_is_restarted_with_backoff(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(supervisor_mod, "metrics", recorder)
    attempts = {"n": 0}

    async def _flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        await asyncio.Event().wait()

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(
        WorkerSpec(
            name="graph_projector", factory=_flaky, role="graph-writer",
            max_restarts=5, backoff_base_s=0.001,
        )
    )
    await supervisor.start_all()
    try:
        await _wait_for(lambda: supervisor.status()["graph_projector"]["state"] == "running")
        assert attempts["n"] == 3
        assert supervisor.status()["graph_projector"]["restarts"] == 2
        # Recovered, so the role reads healthy again.
        assert supervisor.status_by_role()["graph-writer"]["healthy"] is True
        restart_labels = recorder.labels_for("worker_supervisor_restart")
        assert all(lbl["role"] == "graph-writer" for lbl in restart_labels)
    finally:
        await supervisor.stop_all()


class _CollapsingConsumer(EventConsumer):
    """A real EventConsumer whose broker receive loop returns instead of blocking.

    Models the concrete failure the runner has to catch: ``consume_loop`` and
    ``_sqs_receive_loop`` swallow their own exceptions and return normally, so
    an unsupervised process would sit there with a dead pipeline looking fine.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.loop_entries = 0

    async def start(self) -> None:
        self._mode = "kafka"
        self._running = True

    async def receive_loop(self) -> None:
        self.loop_entries += 1
        self._running = False  # what the real loop's finally block does

    async def stop(self) -> None:
        self._running = False


async def test_consumer_loop_exit_is_surfaced_and_restarted(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(supervisor_mod, "metrics", recorder)

    async def _handler(event):
        return None

    registry = _FakeRegistry()
    collapsing = _make_spec(
        "collapsing", "measurement-worker", "g-collapse",
        (Topic.IDENTITY_MERGED,), _handler,
    )
    healthy = _make_spec(
        "healthy", "identity-worker", "g-healthy",
        (Topic.SDK_EVENTS_VALIDATED,), _handler,
    )

    bad = ConsumerRunner(
        role="measurement-worker", group_id="g-collapse", specs=[collapsing],
        registry=registry, consumer_factory=_CollapsingConsumer,
    )
    good = build_consumer_runners(registry, [healthy], queue_urls={})[0]

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(bad.worker_spec(max_restarts=2, backoff_base_s=0.001))
    supervisor.register(good.worker_spec())

    await start_consumer_runners([bad, good])
    await supervisor.start_all()
    try:
        await _wait_for(lambda: supervisor.status()[bad.name]["state"] == "failed")
        # It really was retried, not silently accepted as "completed".
        assert bad.consumer.loop_entries == 3  # first start + 2 restarts
        by_role = supervisor.status_by_role()
        assert by_role["measurement-worker"]["healthy"] is False
        # The co-hosted role is unaffected.
        assert by_role["identity-worker"]["healthy"] is True
        assert supervisor.status()[good.name]["state"] == "running"
        # Metric carries the failing logical role.
        assert {"worker": bad.name, "role": "measurement-worker"} in recorder.labels_for(
            "worker_supervisor_crash"
        )
        assert bad.status()["last_error"]
    finally:
        await drain_consumer_runners([bad, good])
        await supervisor.stop_all()


async def test_collapsing_loop_raises_rather_than_returning_cleanly():
    registry = _FakeRegistry()

    async def _handler(event):
        return None

    spec = _make_spec(
        "x", "stream-worker", "g-x", (Topic.SDK_EVENTS_VALIDATED,), _handler
    )
    runner = ConsumerRunner(
        role="stream-worker", group_id="g-x", specs=[spec],
        registry=registry, consumer_factory=_CollapsingConsumer,
    )
    await runner.start()
    with pytest.raises(ConsumerLoopExited):
        await runner._supervised_receive_loop()


async def test_start_failure_names_the_owning_role():
    class _RefusingConsumer(EventConsumer):
        async def start(self) -> None:
            raise RuntimeError("broker unreachable")

    async def _handler(event):
        return None

    spec = _make_spec("s", "graph-writer", "g", (Topic.PROFILE_UPDATED,), _handler)
    runner = ConsumerRunner(
        role="graph-writer", group_id="g", specs=[spec],
        registry=_FakeRegistry(), consumer_factory=_RefusingConsumer,
    )
    with pytest.raises(RuntimeError, match="graph-writer/g"):
        await start_consumer_runners([runner])


# ── graceful shutdown drains in-flight work ──────────────────────────────────


async def test_drain_waits_for_in_flight_handlers():
    registry = _FakeRegistry()
    finished = {"n": 0}
    gate = asyncio.Event()

    async def _handler(event):
        await gate.wait()
        finished["n"] += 1

    spec = _make_spec(
        "drainable", "materializer", "g-drain",
        (Topic.SDK_EVENTS_VALIDATED,), _handler, drain_timeout_s=5.0,
    )
    runner = build_consumer_runners(registry, [spec], queue_urls={})[0]
    await runner.start()

    task = asyncio.create_task(runner.consumer.process(_event()))
    await _wait_for(lambda: runner.consumer.in_flight == 1)

    drain = asyncio.create_task(runner.drain())
    await asyncio.sleep(0.05)
    assert not drain.done(), "drain must wait for the in-flight handler"

    gate.set()
    report = await drain
    await task

    assert finished["n"] == 1, "in-flight work was dropped instead of drained"
    assert report["drained"] is True
    assert report["in_flight_remaining"] == 0
    assert report["role"] == "materializer"
    assert runner.consumer.in_flight == 0


async def test_drain_reports_incomplete_when_budget_is_exceeded(monkeypatch):
    recorder = _MetricsRecorder()
    # Patch the module dict ConsumerRunner.drain actually closes over rather
    # than re-importing by name: other suites use backend_on_path(), which pops
    # and reimports the backend packages, so sys.modules can hold a *different*
    # module object than the one the imported ConsumerRunner came from.
    monkeypatch.setitem(ConsumerRunner.drain.__globals__, "metrics", recorder)
    registry = _FakeRegistry()
    gate = asyncio.Event()

    async def _handler(event):
        await gate.wait()

    spec = _make_spec(
        "slow", "semantic-worker", "g-slow", (Topic.SDK_EVENTS_VALIDATED,), _handler
    )
    runner = build_consumer_runners(registry, [spec], queue_urls={})[0]
    await runner.start()

    task = asyncio.create_task(runner.consumer.process(_event()))
    await _wait_for(lambda: runner.consumer.in_flight == 1)

    report = await runner.drain(timeout=0.05)
    # Reported loudly, never silently declared clean.
    assert report["drained"] is False
    assert report["in_flight_remaining"] == 1
    assert {"role": "semantic-worker", "group": "g-slow"} in recorder.labels_for(
        "consumer_drain_incomplete"
    )

    gate.set()
    await task


async def test_drain_reports_every_role_in_the_group():
    registry = _FakeRegistry()
    runners = build_consumer_runners(
        registry, consumer_specs_for_role("lean-worker", _FakeSettings()),
        queue_urls=_QUEUE_MAP,
    )
    await start_consumer_runners(runners)
    reports = await drain_consumer_runners(runners)

    assert len(reports) == len(runners)
    assert all(r["drained"] for r in reports)
    # Per-role drain results, not one aggregate verdict.
    assert {r["role"] for r in reports} == {
        "stream-worker", "identity-worker", "graph-writer",
        "measurement-worker", "semantic-worker",
    }
    assert {(r["role"], r["group_id"]) for r in reports} == {
        (r.role, r.group_id) for r in runners
    }


async def test_drain_uses_the_longest_budget_declared_by_the_group():
    registry = _FakeRegistry()

    async def _handler(event):
        return None

    specs = [
        _make_spec("a", "maintenance", "g", (Topic.SDK_EVENTS_VALIDATED,), _handler,
                   drain_timeout_s=5.0),
        _make_spec("b", "maintenance", "g", (Topic.CONSENT_UPDATED,), _handler,
                   drain_timeout_s=45.0),
    ]
    runner = build_consumer_runners(registry, specs, queue_urls={})[0]
    # Cutting at the shortest budget would drop the work the longer one protects.
    assert runner.drain_timeout_s == 45.0
    report = await runner.drain()
    assert report["timeout_s"] == 45.0


async def test_drain_is_idempotent():
    registry = _FakeRegistry()

    async def _handler(event):
        return None

    spec = _make_spec("x", "outbox-relay", "g", (Topic.SDK_EVENTS_VALIDATED,), _handler)
    runner = build_consumer_runners(registry, [spec], queue_urls={})[0]
    await runner.start()
    first = await runner.drain()
    second = await runner.drain()
    assert first["drained"] is True and second["drained"] is True


# ── status carries the role label ────────────────────────────────────────────


def test_runner_status_carries_the_owning_role():
    registry = _FakeRegistry()
    runners = build_consumer_runners(
        registry, consumer_specs_for_role("lean-worker", _FakeSettings()),
        queue_urls=_QUEUE_MAP,
    )
    status = consumer_runner_status(runners)
    assert len(status) == len(runners)
    for name, info in status.items():
        assert name.startswith("consumer:")
        assert info["role"] in WORKER_ROLES
        assert info["group_id"]
        assert name == f"consumer:{info['role']}:{info['group_id']}"
        for key in ("state", "mode", "queue_url", "max_concurrent", "in_flight",
                    "dlq_depth", "required", "specs", "last_error"):
            assert key in info


async def test_registration_metrics_carry_the_role(monkeypatch, capsys):
    recorder = _MetricsRecorder()
    import shared.logger.logger as logger_mod

    monkeypatch.setattr(logger_mod, "metrics", recorder)
    registry = _FakeRegistry()
    specs = run_role._stamp_owning_roles(
        [WorkerSpec(name=n, factory=_forever) for n in _all_spec_names()], "lean-worker"
    )
    runners = build_consumer_runners(
        registry, consumer_specs_for_role("lean-worker", _FakeSettings()),
        queue_urls=_QUEUE_MAP,
    )
    run_role._log_role_topology("lean-worker", specs, runners)

    worker_labels = recorder.labels_for("runtime_worker_registered")
    assert worker_labels, "no per-spec registration metrics emitted"
    # Every registration is attributed to a logical role, and records the token
    # the process actually booted as so consolidation stays visible.
    assert all(lbl["role"] in WORKER_ROLES for lbl in worker_labels)
    assert all(lbl["booted_as"] == "lean-worker" for lbl in worker_labels)
    consumer_labels = recorder.labels_for("runtime_consumer_registered")
    assert {lbl["role"] for lbl in consumer_labels} == {
        "stream-worker", "identity-worker", "graph-writer",
        "measurement-worker", "semantic-worker",
    }

    # The startup banner is per-role, so a consolidated process can still answer
    # "is measurement-worker running here?" from its own logs.
    out = capsys.readouterr().out
    assert "booted_as=lean-worker consolidated" in out
    for role in WORKER_ROLES:
        assert f"role={role} " in out


# ── DLQ routing must never silently degrade ──────────────────────────────────


async def test_dlq_keeps_events_in_memory_in_local_mode(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    consumer = EventConsumer(group_id="g")

    async def _always_fails(event):
        raise ValueError("handler boom")

    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _always_fails)
    event = _event()
    await consumer.process(event)

    assert consumer.dlq_depth == 1
    dead = consumer._dlq[0]
    assert dead.topic is Topic.DEAD_LETTER
    assert dead.payload["original_event_id"] == event.event_id
    assert dead.payload["original_topic"] == Topic.SDK_EVENTS_VALIDATED.value
    assert "handler boom" in dead.payload["error"]


async def test_dlq_publishes_durably_in_kafka_mode(monkeypatch):
    """Regression: _kafka_producer was never assigned, so this path raised
    AttributeError, got swallowed, and degraded to the in-memory list."""
    monkeypatch.setenv("AETHER_ENV", "staging")
    sent: list[tuple[str, str]] = []

    class _Producer:
        async def send_and_wait(self, topic, value):
            sent.append((topic, value))

    consumer = EventConsumer(group_id="g")
    consumer._mode = "kafka"
    consumer._kafka_producer = _Producer()

    async def _always_fails(event):
        raise ValueError("handler boom")

    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _always_fails)
    await consumer.process(_event())

    assert len(sent) == 1
    topic, body = sent[0]
    assert topic == Topic.DEAD_LETTER.value
    assert "handler boom" in body
    # Durably published, so nothing was parked in the volatile list.
    assert consumer.dlq_depth == 0


async def test_dlq_publish_failure_raises_instead_of_degrading(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "staging")
    recorder = _MetricsRecorder()
    monkeypatch.setattr(events_mod, "metrics", recorder)

    class _BrokenProducer:
        async def send_and_wait(self, topic, value):
            raise ConnectionError("kafka down")

    consumer = EventConsumer(group_id="g")
    consumer._mode = "kafka"
    consumer._kafka_producer = _BrokenProducer()

    async def _always_fails(event):
        raise ValueError("handler boom")

    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _always_fails)

    # Must propagate: the caller leaves the offset uncommitted / the receipt
    # undeleted, so the event is redelivered rather than acknowledged as safely
    # dead-lettered. Silently appending to the in-memory list would lose it.
    with pytest.raises(DLQPublishError):
        await consumer.process(_event())

    assert recorder.labels_for("events_dlq_publish_failed")
    # A recovery copy is kept in addition to the raise, never instead of it.
    assert consumer.dlq_depth == 1
    # And the in-flight counter is still released.
    assert consumer.in_flight == 0


async def test_dlq_without_any_durable_transport_fails_loudly(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "staging")
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    consumer = EventConsumer(group_id="g")
    consumer._mode = "kafka"  # kafka mode but no producer and no bootstrap

    async def _always_fails(event):
        raise ValueError("handler boom")

    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _always_fails)
    with pytest.raises(DLQPublishError):
        await consumer.process(_event())


async def test_dlq_is_per_role_and_does_not_leak_across_roles():
    """Each logical role dead-letters into its own consumer, not a shared one."""
    registry = _FakeRegistry()

    async def _fails(event):
        raise ValueError("boom")

    async def _ok(event):
        return None

    specs = [
        _make_spec("bad", "measurement-worker", "g-bad",
                   (Topic.IDENTITY_MERGED,), _fails, max_handler_retries=0),
        _make_spec("good", "identity-worker", "g-good",
                   (Topic.SDK_EVENTS_VALIDATED,), _ok),
    ]
    runners = build_consumer_runners(registry, specs, queue_urls={})
    by_role = {r.role: r for r in runners}

    await by_role["measurement-worker"].consumer.process(_event(Topic.IDENTITY_MERGED))
    await by_role["identity-worker"].consumer.process(_event(Topic.SDK_EVENTS_VALIDATED))

    assert by_role["measurement-worker"].consumer.dlq_depth == 1
    assert by_role["identity-worker"].consumer.dlq_depth == 0
    assert by_role["measurement-worker"].status()["dlq_depth"] == 1
    # The registry's shared consumer is not in the path at all.
    assert registry.consumer.dlq_depth == 0


# ── retry / idempotency ──────────────────────────────────────────────────────


async def test_retry_is_bounded_by_the_group_policy():
    registry = _FakeRegistry()
    attempts = {"n": 0}

    async def _flaky(event):
        attempts["n"] += 1
        raise ValueError("still failing")

    spec = _make_spec(
        "retrying", "stream-worker", "g-retry",
        (Topic.SDK_EVENTS_VALIDATED,), _flaky, max_handler_retries=3,
    )
    runner = build_consumer_runners(registry, [spec], queue_urls={})[0]
    assert runner.consumer.MAX_HANDLER_RETRIES == 3

    await runner.consumer.process(_event())
    # Initial attempt plus three retries, then dead-lettered.
    assert attempts["n"] == 4
    assert runner.consumer.dlq_depth == 1


async def test_idempotent_reprocessing_holds_under_retry():
    """Retries and redelivery must not double-apply a handler's side effect."""
    registry = _FakeRegistry()
    applied: set[str] = set()
    invocations = {"n": 0}
    transient = {"n": 2}

    async def _idempotent(event):
        invocations["n"] += 1
        if transient["n"] > 0:
            transient["n"] -= 1
            raise ConnectionError("transient downstream failure")
        # Keyed on event_id: the same event applied twice is a no-op.
        applied.add(event.event_id)

    spec = _make_spec(
        "idempotent", "graph-writer", "g-idem",
        (Topic.PROFILE_UPDATED,), _idempotent, max_handler_retries=5,
    )
    runner = build_consumer_runners(registry, [spec], queue_urls={})[0]

    event = _event(Topic.PROFILE_UPDATED, entity="e1")
    await runner.consumer.process(event)

    # It really did retry, and it really did eventually succeed.
    assert invocations["n"] == 3
    assert applied == {event.event_id}
    assert runner.consumer.dlq_depth == 0

    # Broker redelivery of the very same event: handled again, applied once.
    await runner.consumer.process(event)
    assert invocations["n"] == 4
    assert applied == {event.event_id}


# ── broker selection must fail closed ────────────────────────────────────────


async def test_sns_sqs_without_queue_url_fails_closed_in_non_local(monkeypatch):
    """Regression: an empty SQS_QUEUE_URL silently fell through to Kafka."""
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("EVENT_BROKER", "sns_sqs")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka.internal:9092")

    async def _handler(event):
        return None

    consumer = EventConsumer(group_id="g")
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)

    with pytest.raises(RuntimeError, match="EVENT_BROKER=sns_sqs"):
        await consumer.start()
    # Critically, it did NOT quietly bind the other broker.
    assert consumer.mode != "kafka"


async def test_sns_sqs_without_queue_url_stays_permissive_in_local(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("EVENT_BROKER", "sns_sqs")

    async def _handler(event):
        return None

    consumer = EventConsumer(group_id="g")
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)
    await consumer.start()
    assert consumer.mode == "in-memory"


async def test_explicit_queue_url_wins_over_the_env_var(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("EVENT_BROKER", "sns_sqs")
    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.test/process-wide")

    class _StubBoto3:
        @staticmethod
        def client(name):
            return object()

    monkeypatch.setattr(events_mod, "_boto3_events", _StubBoto3)
    monkeypatch.setattr(events_mod, "BOTO3_EVENTS_AVAILABLE", True)

    async def _handler(event):
        return None

    consumer = EventConsumer(group_id="aether-identity", queue_url="https://sqs.test/identity")
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)
    await consumer.start()

    assert consumer.mode == "sqs"
    # The per-role binding wins; otherwise every co-hosted role would compete
    # for one process-wide queue.
    assert consumer.queue_url == "https://sqs.test/identity"


async def test_env_queue_url_still_used_when_no_explicit_binding(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("EVENT_BROKER", "sns_sqs")
    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.test/dedicated")

    class _StubBoto3:
        @staticmethod
        def client(name):
            return object()

    monkeypatch.setattr(events_mod, "_boto3_events", _StubBoto3)
    monkeypatch.setattr(events_mod, "BOTO3_EVENTS_AVAILABLE", True)

    async def _handler(event):
        return None

    consumer = EventConsumer(group_id="g")
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)
    await consumer.start()
    assert consumer.queue_url == "https://sqs.test/dedicated"


def test_resize_concurrency_rejects_unsafe_values():
    consumer = EventConsumer(group_id="g")
    with pytest.raises(ValueError):
        consumer.resize_concurrency(0)
    consumer._in_flight = 1
    with pytest.raises(RuntimeError, match="in flight"):
        consumer.resize_concurrency(5)
