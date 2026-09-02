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
import re
import signal
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
    resolve_dlq_url,
    resolve_queue_url,
    role_dlq_urls,
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
    ConsumerClientTornDown,
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
    monkeypatch.delenv("SQS_ROLE_DLQ_URLS", raising=False)


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


# The per-role queue map production-lean actually supplies.
#
# This used to carry five entries with a comment claiming it mirrored
# modules/sqs/main.tf. It did not. Terraform's var.consumer_role_queues default
# has FOUR entries — semantic-worker is absent — so every test built on the old
# map asserted a topology that has never been deployed. The map is now the four
# roles Terraform genuinely provisions a queue for, and
# ``test_queue_map_mirrors_the_terraform_module_default`` checks that claim
# against the .tf file instead of restating it in a comment.
_QUEUE_MAP = {
    "stream-worker": "https://sqs.test/stream",
    "identity-worker": "https://sqs.test/identity",
    "graph-writer": "https://sqs.test/graph",
    "measurement-worker": "https://sqs.test/measurement",
}

# The shared SNS-subscribed events queue (modules/sqs: aws_sqs_queue.events),
# which ECS passes as SQS_QUEUE_URL. Any hosted consumer role without a
# dedicated queue lands here through resolve_queue_url's documented fallback.
_FALLBACK_QUEUE_URL = "https://sqs.test/events"

# Consumer roles declared in consumer_specs.py that Terraform provisions NO
# dedicated queue for. Not an accident to be papered over in tests: it is the
# live topology, and it means semantic-worker consumes the shared events queue.
_ROLES_WITHOUT_DEDICATED_QUEUE = {"semantic-worker"}

# Per-role dead-letter queues. modules/sqs already creates one
# aws_sqs_queue.role_dlq per consumer role; it simply does not yet output the
# URLs or pass them to the task, so nothing sets SQS_ROLE_DLQ_URLS in the real
# deployment. These are the URLs the runtime expects once it does.
_DLQ_MAP = {role: f"{url}-dlq" for role, url in _QUEUE_MAP.items()}

_TERRAFORM_SQS_VARIABLES = (
    Path(__file__).parents[2]
    / "AWS Deployment" / "aether-aws" / "terraform" / "modules" / "sqs" / "variables.tf"
)


def _terraform_consumer_role_queues() -> dict[str, str]:
    """Parse ``var.consumer_role_queues``'s committed default out of the module.

    Read rather than duplicated so the "mirrors Terraform" claim is verified.
    A hand-copied map is exactly how the five-vs-four drift survived.
    """
    text = _TERRAFORM_SQS_VARIABLES.read_text(encoding="utf-8")
    block = re.search(
        r'variable\s+"consumer_role_queues"\s*\{.*?\bdefault\s*=\s*\{(.*?)\n\s*\}',
        text,
        re.DOTALL,
    )
    assert block, f"consumer_role_queues default not found in {_TERRAFORM_SQS_VARIABLES}"
    return dict(re.findall(r'"([^"]+)"\s*=\s*"([^"]+)"', block.group(1)))


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


def test_queue_map_mirrors_the_terraform_module_default():
    """The map used by every SQS test must be what Terraform really provisions.

    The old five-entry ``_QUEUE_MAP`` claimed this in a comment and was wrong,
    which is why two topology tests asserted a deployment that does not exist.
    Verify the claim instead of restating it.
    """
    terraform = _terraform_consumer_role_queues()
    assert set(_QUEUE_MAP) == set(terraform), (
        "_QUEUE_MAP has drifted from modules/sqs/variables.tf "
        f"(terraform-only: {sorted(set(terraform) - set(_QUEUE_MAP))}, "
        f"test-only: {sorted(set(_QUEUE_MAP) - set(terraform))}). "
        "Update _QUEUE_MAP and _ROLES_WITHOUT_DEDICATED_QUEUE together."
    )

    # And the gap itself, pinned so it cannot widen unnoticed: every consumer
    # role in the registry either owns a Terraform queue or is a known
    # fallback-bound role.
    declared_roles = {s.role for s in consumer_specs_for_role("lean-worker", _FakeSettings())}
    assert declared_roles - set(terraform) == _ROLES_WITHOUT_DEDICATED_QUEUE
    # Terraform must not provision a queue for a role no consumer spec claims.
    assert set(terraform) - declared_roles == set()


def test_sqs_mode_binds_one_consumer_per_role_queue(monkeypatch):
    # Model the real lean-worker task environment: SQS_ROLE_QUEUE_URLS carries
    # the roles Terraform gave a dedicated queue, SQS_QUEUE_URL carries the
    # shared events queue that everything else falls back to.
    monkeypatch.setenv("SQS_QUEUE_URL", _FALLBACK_QUEUE_URL)
    registry = _FakeRegistry()
    specs = consumer_specs_for_role("lean-worker", _FakeSettings())
    runners = build_consumer_runners(
        registry, specs, broker="sns_sqs", queue_urls=_QUEUE_MAP
    )

    # One runner per consumer role — five roles are declared in code.
    assert len(runners) == 5
    assert {r.role for r in runners} == set(_QUEUE_MAP) | _ROLES_WITHOUT_DEDICATED_QUEUE
    assert len({id(r.consumer) for r in runners}) == 5
    assert all(r.consumer is not registry.consumer for r in runners)

    for runner in runners:
        # Four bind their dedicated Terraform queue; semantic-worker has none,
        # so it binds the shared events queue via the documented fallback.
        expected = _QUEUE_MAP.get(runner.role, _FALLBACK_QUEUE_URL)
        assert runner.queue_url == expected
        # A real group is pinned, never the env-default fallback group.
        assert runner.consumer.group_id == runner.group_id
        assert not runner.consumer.group_id.startswith("aether-backend-")
        # Every topic the role's specs declare is subscribed on that one
        # consumer, so nothing on the role queue arrives unhandled.
        declared = set()
        for spec in runner.specs:
            declared |= set(spec.topics)
        assert set(runner.consumer._handlers) == declared


def test_sqs_mode_gives_semantic_worker_one_consumer_carrying_both_groups(monkeypatch):
    """Regression: two consumers on one SQS queue silently drop messages.

    SQS has no consumer groups — the two would compete for the queue, and
    whichever received a message it had no handler for would delete it.
    """
    monkeypatch.setenv("SQS_QUEUE_URL", _FALLBACK_QUEUE_URL)
    specs = consumer_specs_for_role("semantic-worker", _FakeSettings())
    assert len({s.group_id for s in specs}) == 2

    runners = build_consumer_runners(
        _FakeRegistry(), specs, broker="sns_sqs", queue_urls=_QUEUE_MAP
    )
    assert len(runners) == 1
    runner = runners[0]
    # Terraform provisions no semantic-worker queue, so this role really does
    # bind the shared events queue. Collapsing to one consumer matters more
    # here, not less: a second consumer on the shared queue would steal and
    # delete events every other role's queue also needs.
    assert runner.queue_url == _FALLBACK_QUEUE_URL
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


def test_no_two_consumers_in_a_process_ever_share_a_queue(monkeypatch):
    """The invariant the whole module exists to uphold.

    Exercised against the *real* binding, fallback included. Leaving
    SQS_QUEUE_URL unset would give the fallback-bound role an empty URL, which
    ``_assert_distinct_queues`` skips — so the test would have passed while
    checking nothing about the one role whose binding is not explicit.
    """
    monkeypatch.setenv("SQS_QUEUE_URL", _FALLBACK_QUEUE_URL)
    for broker in ("sns_sqs", "kafka"):
        runners = build_consumer_runners(
            _FakeRegistry(), consumer_specs_for_role("lean-worker", _FakeSettings()),
            broker=broker, queue_urls=_QUEUE_MAP,
        )
        bound = [r.queue_url for r in runners if r.queue_url]
        assert len(bound) == len(set(bound)), f"{broker}: consumers share a queue"
    # Under sns_sqs every role is bound to something — no role silently ends up
    # with no queue at all.
    runners = build_consumer_runners(
        _FakeRegistry(), consumer_specs_for_role("lean-worker", _FakeSettings()),
        broker="sns_sqs", queue_urls=_QUEUE_MAP,
    )
    assert all(r.queue_url for r in runners)


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

    # identity-worker co-hosts signal emission and the durable resolution-replay
    # consumer on its one SQS queue (separate Kafka groups; one queue under SQS).
    assert set(identity.consumer._handlers) == {
        Topic.SDK_EVENTS_VALIDATED,
        Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED,
    }
    assert set(measurement.consumer._handlers) == {Topic.IDENTITY_MERGED, Topic.IDENTITY_SPLIT}
    # Identity and measurement never see each other's traffic.
    assert Topic.IDENTITY_MERGED not in identity.consumer._handlers
    assert Topic.SDK_EVENTS_VALIDATED not in measurement.consumer._handlers
    # And each is bound to its own queue.
    assert identity.queue_url != measurement.queue_url


def test_queue_url_reaches_the_event_consumer_constructor(monkeypatch):
    monkeypatch.setenv("SQS_QUEUE_URL", _FALLBACK_QUEUE_URL)
    registry = _FakeRegistry()
    seen: list[tuple[str, str, str]] = []

    def _recording_factory(*, group_id: str, queue_url: str, dlq_queue_url: str = "") -> EventConsumer:
        seen.append((group_id, queue_url, dlq_queue_url))
        return EventConsumer(
            group_id=group_id, queue_url=queue_url, dlq_queue_url=dlq_queue_url,
        )

    specs = consumer_specs_for_role("lean-worker", _FakeSettings())
    build_consumer_runners(
        registry, specs, broker="sns_sqs", queue_urls=_QUEUE_MAP, dlq_urls=_DLQ_MAP,
        consumer_factory=_recording_factory,
    )
    # Queue AND dead-letter binding both reach the consumer, per role. Without
    # the dead-letter binding a poison event has nowhere distinct to go.
    assert ("aether-identity", "https://sqs.test/identity", "https://sqs.test/identity-dlq") in seen
    # semantic-worker has no Terraform queue and therefore no Terraform DLQ:
    # it falls back to the shared queue and to no dead-letter destination.
    assert ("aether-semantic", _FALLBACK_QUEUE_URL, "") in seen


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


# ═════════════════════════════════════════════════════════════════════════════
# THE REAL RECEIVE LOOPS
#
# Everything above drives ``consumer.process()`` directly. That is a fine way to
# test handler semantics and a useless way to test delivery semantics, because
# every acknowledgement decision — SQS delete, Kafka commit — lives in the
# receive loop and never executed in a single test. Three separate data-loss
# defects lived in that blind spot: dead letters published onto the source
# queue, drains that tore the client down before acknowledging, and Kafka
# commits that walked straight past a failed offset.
#
# The tests below run the actual ``_sqs_receive_loop`` / ``consume_loop`` and
# assert on what was acknowledged, not on what was handled.
# ═════════════════════════════════════════════════════════════════════════════

_SOURCE_QUEUE = _QUEUE_MAP["identity-worker"]
_ROLE_DLQ = _DLQ_MAP["identity-worker"]


class _FakeSQSClient:
    """A boto3 SQS client stand-in that records acknowledgements.

    Exactly enough API for the real receive loop: each batch is handed out once,
    after which the queue reads empty. Deletes and sends are what the tests
    assert on — the handler being *called* was never the thing in doubt.
    """

    def __init__(self, batches=()) -> None:
        self._batches = [list(batch) for batch in batches]
        self.received: list[dict] = []
        self.deleted: list[str] = []
        self.sent: list[tuple[str, str]] = []
        self.closed = False

    def receive_message(self, **kwargs):
        if self._batches:
            batch = self._batches.pop(0)
            self.received.extend(batch)
            return {"Messages": batch}
        # Stands in for the 20s long poll: runs on an executor thread, so a
        # short sleep keeps the loop from spinning without blocking the loop.
        time.sleep(0.005)
        return {}

    def delete_message(self, QueueUrl, ReceiptHandle):  # noqa: N803 — boto3 casing
        self.deleted.append(ReceiptHandle)

    def send_message(self, QueueUrl, MessageBody):  # noqa: N803 — boto3 casing
        self.sent.append((QueueUrl, MessageBody))

    def close(self):
        self.closed = True


def _sqs_message(event: Event, receipt: str) -> dict:
    return {"ReceiptHandle": receipt, "Body": event.serialize(), "MessageId": event.event_id}


def _bind_sqs(monkeypatch, client: _FakeSQSClient) -> None:
    """Put the process in the SQS broker mode ``EventConsumer.start`` selects."""
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("EVENT_BROKER", "sns_sqs")

    class _StubBoto3:
        @staticmethod
        def client(name):
            return client

    monkeypatch.setattr(events_mod, "_boto3_events", _StubBoto3)
    monkeypatch.setattr(events_mod, "BOTO3_EVENTS_AVAILABLE", True)


async def _stop_loop(consumer: EventConsumer, task: asyncio.Task) -> None:
    consumer.pause()
    await asyncio.wait_for(task, 5)
    await consumer.stop()


# ── defect 1: a dead letter must never land on the queue it came from ────────


async def test_sqs_receive_loop_deletes_only_what_it_successfully_processed(monkeypatch):
    """Regression: the DLQ target fell back to the SOURCE queue, destroying events.

    With ``SQS_DLQ_QUEUE_URL`` unset — which is every real deployment, because
    nothing sets it — the poison event's ``aether.dlq`` copy was published onto
    this consumer's own queue and the original deleted. The copy was then
    received once, found no ``Topic.DEAD_LETTER`` subscriber, and was deleted as
    an unhandled message. Redrive never fired (it counts receives *without*
    deletion) and ``events_dead_lettered`` had already ticked, so the event
    vanished while the metrics read healthy.
    """
    good = _event(Topic.SDK_EVENTS_VALIDATED, ok=True)
    poison = _event(Topic.SDK_EVENTS_VALIDATED, ok=False)
    client = _FakeSQSClient([[_sqs_message(good, "rh-good"), _sqs_message(poison, "rh-poison")]])
    _bind_sqs(monkeypatch, client)

    async def _handler(event):
        if not event.payload["ok"]:
            raise ValueError("poison payload")

    consumer = EventConsumer(group_id="aether-identity", queue_url=_SOURCE_QUEUE)
    consumer.MAX_HANDLER_RETRIES = 0
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)
    await consumer.start()
    assert consumer.mode == "sqs"

    task = asyncio.create_task(consumer.receive_loop())
    # dlq_depth ticks only after the poison message has been fully attempted,
    # and the good message precedes it in the batch.
    await _wait_for(lambda: consumer.dlq_depth == 1)
    await _stop_loop(consumer, task)

    # The one that succeeded is acknowledged; the poison one is NOT, so its
    # receipt expires and SQS's redrive policy quarantines it after
    # maxReceiveCount. That is the only recoverable outcome available.
    assert client.deleted == ["rh-good"]
    # And nothing was pushed back onto the source queue.
    assert client.sent == [], "a dead letter was published onto the source queue"


async def test_dead_letter_is_never_published_onto_the_source_queue(monkeypatch):
    """Impossible, not merely discouraged — including when explicitly misconfigured."""
    monkeypatch.setenv("AETHER_ENV", "staging")
    client = _FakeSQSClient()

    async def _always_fails(event):
        raise ValueError("handler boom")

    consumer = EventConsumer(group_id="g", queue_url=_SOURCE_QUEUE)
    consumer._mode = "sqs"
    consumer._sqs_client = client
    consumer._sqs_queue_url = _SOURCE_QUEUE
    consumer.MAX_HANDLER_RETRIES = 0
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _always_fails)

    # (a) Nothing configured: refuse rather than fall back to the source queue.
    with pytest.raises(DLQPublishError):
        await consumer.process(_event())
    assert client.sent == []

    # (b) Explicitly pointed at the source queue: still refused. An operator
    # cannot configure their way into destroying events.
    monkeypatch.setenv("SQS_DLQ_QUEUE_URL", _SOURCE_QUEUE)
    with pytest.raises(DLQPublishError):
        await consumer.process(_event())
    assert client.sent == []


async def test_sqs_dead_letter_reaches_the_configured_role_dlq(monkeypatch):
    """The happy path: a distinct destination, so the source CAN be acknowledged."""
    poison = _event(Topic.SDK_EVENTS_VALIDATED, ok=False)
    client = _FakeSQSClient([[_sqs_message(poison, "rh-poison")]])
    _bind_sqs(monkeypatch, client)

    async def _always_fails(event):
        raise ValueError("handler boom")

    consumer = EventConsumer(
        group_id="aether-identity", queue_url=_SOURCE_QUEUE, dlq_queue_url=_ROLE_DLQ,
    )
    consumer.MAX_HANDLER_RETRIES = 0
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _always_fails)
    await consumer.start()

    task = asyncio.create_task(consumer.receive_loop())
    await _wait_for(lambda: client.deleted == ["rh-poison"])
    await _stop_loop(consumer, task)

    # Quarantined on a queue this process does not consume, so deleting the
    # original is now genuinely safe rather than a disguised drop.
    assert [queue for queue, _ in client.sent] == [_ROLE_DLQ]
    assert "handler boom" in client.sent[0][1]
    # Durably published, so nothing was parked in the volatile in-memory list.
    assert consumer.dlq_depth == 0


def test_runner_refuses_a_dead_letter_queue_that_is_its_own_source():
    async def _handler(event):
        return None

    spec = _make_spec("x", "identity-worker", "g", (Topic.SDK_EVENTS_VALIDATED,), _handler)
    with pytest.raises(RuntimeError, match="its own source queue"):
        ConsumerRunner(
            role="identity-worker", group_id="g", specs=[spec],
            registry=_FakeRegistry(),
            queue_url=_SOURCE_QUEUE, dlq_queue_url=_SOURCE_QUEUE,
        )


def test_dlq_urls_resolve_by_role_then_fall_back(monkeypatch):
    monkeypatch.setenv("SQS_DLQ_QUEUE_URL", "https://sqs.test/shared-dlq")
    assert resolve_dlq_url("identity-worker", mapping=_DLQ_MAP) == _ROLE_DLQ
    assert resolve_dlq_url("semantic-worker", mapping=_DLQ_MAP) == "https://sqs.test/shared-dlq"
    # Unconfigured is a real state and must not raise here: the consumer refuses
    # at publish time, leaving the message for SQS redrive.
    monkeypatch.delenv("SQS_DLQ_QUEUE_URL")
    assert resolve_dlq_url("semantic-worker", mapping={}) == ""


def test_role_dlq_urls_fails_closed_on_malformed_json(monkeypatch):
    monkeypatch.setenv("SQS_ROLE_DLQ_URLS", "{not json")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        role_dlq_urls()
    monkeypatch.setenv("SQS_ROLE_DLQ_URLS", json.dumps(_DLQ_MAP))
    assert role_dlq_urls() == _DLQ_MAP


# ── defect 3: a drain must acknowledge before it tears the client down ───────


async def test_drain_acknowledges_in_flight_work_before_releasing_the_client(monkeypatch):
    """Regression: ``drain()`` called ``stop()`` first, guaranteeing duplicates.

    ``stop()`` sets ``_sqs_client = None``. Waiting for in-flight handlers only
    *after* that meant every handler that completed during the drain hit
    ``AttributeError`` on ``delete_message``, which the receive loop swallowed —
    so the message reappeared once its visibility timeout expired. Every message
    in the current batch, times every consumer, on every deploy.
    """
    gate = asyncio.Event()
    event = _event(Topic.SDK_EVENTS_VALIDATED)
    client = _FakeSQSClient([[_sqs_message(event, "rh-1")]])
    _bind_sqs(monkeypatch, client)

    async def _handler(_event_):
        await gate.wait()

    spec = _make_spec(
        "drainable", "identity-worker", "aether-identity",
        (Topic.SDK_EVENTS_VALIDATED,), _handler, drain_timeout_s=5.0,
    )
    runner = build_consumer_runners(
        _FakeRegistry(), [spec], broker="sns_sqs",
        queue_urls={"identity-worker": _SOURCE_QUEUE},
        dlq_urls={"identity-worker": _ROLE_DLQ},
    )[0]
    await runner.start()
    task = asyncio.create_task(runner.consumer.receive_loop())
    await _wait_for(lambda: runner.consumer.in_flight == 1)

    drain = asyncio.create_task(runner.drain())
    await asyncio.sleep(0.05)
    assert not drain.done(), "drain must wait for the in-flight handler"

    gate.set()
    report = await asyncio.wait_for(drain, 5)
    await asyncio.wait_for(task, 5)

    # The message completed during the drain and was acknowledged. Before the
    # reorder this list was empty and the event was redelivered.
    assert client.deleted == ["rh-1"], "in-flight work completed but was never acknowledged"
    assert report["drained"] is True
    assert report["unacked_remaining"] == 0
    # And only then was the client released.
    assert client.closed is True


async def test_drain_waits_for_the_acknowledgement_not_just_the_handler():
    """``in_flight`` alone is not quiescence — the ack outlives the handler.

    ``in_flight`` drops to zero the instant a handler returns, while the delete
    for that same message is still outstanding. A drain that only watched
    ``in_flight`` tore the client down inside exactly that window.
    """

    async def _handler(event):
        return None

    spec = _make_spec("s", "identity-worker", "g", (Topic.SDK_EVENTS_VALIDATED,), _handler)
    runner = build_consumer_runners(_FakeRegistry(), [spec], queue_urls={})[0]
    # The window: handler finished, acknowledgement not yet issued.
    runner.consumer._unacked = 1

    report = await runner.drain(timeout=0.05)
    assert report["in_flight_remaining"] == 0
    assert report["unacked_remaining"] == 1
    assert report["drained"] is False, "an unacknowledged message is not drained"


async def test_a_torn_down_client_is_raised_not_swallowed():
    """The ``AttributeError`` that used to be silently absorbed one frame up."""
    consumer = EventConsumer(group_id="g")
    loop = asyncio.get_running_loop()
    with pytest.raises(ConsumerClientTornDown):
        await consumer._delete_message(loop, None, "rh-1")


# ── defect 4: Kafka must not commit past a message it could not handle ───────


class _FakeKafkaMessage:
    __slots__ = ("topic", "partition", "offset", "value")

    def __init__(self, topic: str, partition: int, offset: int, value: str) -> None:
        self.topic = topic
        self.partition = partition
        self.offset = offset
        self.value = value


class _FakeKafkaConsumer:
    """Async-iterable stand-in recording commits, seeks and tear-down."""

    def __init__(self, messages=(), **kwargs) -> None:
        self._pending = list(messages)
        self.kwargs = kwargs
        self.commits = 0
        self.seeks: list[tuple[str, int, int]] = []
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._pending:
            raise StopAsyncIteration
        return self._pending.pop(0)

    async def commit(self) -> None:
        self.commits += 1

    def seek(self, partition, offset) -> None:
        self.seeks.append((partition.topic, partition.partition, offset))


async def test_kafka_loop_never_commits_past_a_message_it_could_not_handle(monkeypatch):
    """Regression: a per-message failure was logged and the loop carried on.

    ``commit()`` with no arguments commits ``position()`` — where the fetcher
    has got to, not the message just handled — so the very next success
    committed straight past the failed offset. The event was gone, permanently,
    while the code above it documented "redelivery rather than silent loss".
    """
    monkeypatch.setenv("AETHER_ENV", "staging")
    # No bootstrap: the durable DLQ transport is unavailable, which is exactly
    # when a message genuinely cannot be acknowledged.
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    handled: list[int] = []

    async def _handler(event):
        handled.append(event.payload["n"])
        if event.payload["n"] == 1:
            raise ValueError("undeliverable")

    consumer = EventConsumer(group_id="g")
    consumer.MAX_HANDLER_RETRIES = 0
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)
    fake = _FakeKafkaConsumer([
        _FakeKafkaMessage("aether.sdk.events.validated", 0, n, _event(n=n).serialize())
        for n in range(3)
    ])
    consumer._kafka_consumer = fake
    consumer._mode = "kafka"
    consumer._running = True

    await consumer.consume_loop()

    # The loop stopped AT the failure rather than stepping over it.
    assert handled == [0, 1]
    # Exactly one commit: message 0. Message 1's offset stays uncommitted, so a
    # restart or rebalance re-delivers it.
    assert fake.commits == 1
    if events_mod.TopicPartition is not None:
        # Rewound in-process too, so redelivery does not depend on a rebalance.
        assert fake.seeks == [("aether.sdk.events.validated", 0, 1)]
    assert consumer.is_running is False
    assert consumer.unacked == 0


async def test_kafka_loop_commits_every_message_it_did_handle(monkeypatch):
    """The other half of the contract: success is acknowledged, one per message."""
    monkeypatch.setenv("AETHER_ENV", "staging")
    handled: list[int] = []

    async def _handler(event):
        handled.append(event.payload["n"])

    consumer = EventConsumer(group_id="g")
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)
    fake = _FakeKafkaConsumer([
        _FakeKafkaMessage("aether.sdk.events.validated", 0, n, _event(n=n).serialize())
        for n in range(3)
    ])
    consumer._kafka_consumer = fake
    consumer._mode = "kafka"
    consumer._running = True

    await consumer.consume_loop()

    assert handled == [0, 1, 2]
    assert fake.commits == 3
    assert fake.seeks == []


# ── defect 5: a restart must not leave the previous client alive ─────────────


async def test_restart_tears_down_the_previous_kafka_consumer(monkeypatch):
    """Regression: the zombie kept its group membership and stalled partitions.

    ``consume_loop``'s ``finally`` clears ``_running`` but leaves
    ``_kafka_consumer`` bound, and the supervised restart re-entered ``start()``
    on exactly that state, overwriting the attribute. The old consumer kept
    heartbeating, so the group retained a member that owned partitions it would
    never fetch from — those partitions stalled indefinitely, because the zombie
    kept renewing the session that would otherwise have evicted it.
    """
    monkeypatch.setenv("AETHER_ENV", "staging")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka.test:9092")
    created: list[_FakeKafkaConsumer] = []

    def _factory(*topics, **kwargs):
        consumer = _FakeKafkaConsumer((), **kwargs)
        created.append(consumer)
        return consumer

    monkeypatch.setattr(events_mod, "AIOKafkaConsumer", _factory)
    monkeypatch.setattr(events_mod, "KAFKA_AVAILABLE", True)

    async def _handler(event):
        return None

    consumer = EventConsumer(group_id="g")
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)
    await consumer.start()
    # The crash shape: the loop returns, leaving the binding in place.
    await consumer.consume_loop()
    assert consumer.is_running is False
    assert created[0].stopped is False

    await consumer.start()  # the supervised restart path

    assert len(created) == 2
    assert created[0].stopped is True, "previous consumer left holding partitions"
    assert consumer._kafka_consumer is created[1]


async def test_restart_releases_the_previous_sqs_client(monkeypatch):
    """Same leak in SQS mode: benign, unbounded across restarts, still wrong."""
    first, second = _FakeSQSClient(), _FakeSQSClient()
    pending = [first, second]
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("EVENT_BROKER", "sns_sqs")

    class _StubBoto3:
        @staticmethod
        def client(name):
            return pending.pop(0)

    monkeypatch.setattr(events_mod, "_boto3_events", _StubBoto3)
    monkeypatch.setattr(events_mod, "BOTO3_EVENTS_AVAILABLE", True)

    async def _handler(event):
        return None

    consumer = EventConsumer(group_id="g", queue_url=_SOURCE_QUEUE)
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)
    await consumer.start()
    await consumer.start()

    assert first.closed is True
    assert consumer._sqs_client is second


async def test_kafka_dlq_producer_is_created_lazily_and_reused(monkeypatch):
    """``_ensure_dlq_producer`` had no happy-path coverage at all.

    Every DLQ test injected ``_kafka_producer`` directly, so the function that
    is the actual fix for the original ``AttributeError`` was never executed.
    """
    monkeypatch.setenv("AETHER_ENV", "staging")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka.test:9092")
    created: list = []

    class _Producer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.started = False
            self.sent: list[tuple[str, str]] = []
            created.append(self)

        async def start(self):
            self.started = True

        async def stop(self):
            self.started = False

        async def send_and_wait(self, topic, value):
            self.sent.append((topic, value))

    monkeypatch.setattr(events_mod, "AIOKafkaProducer", _Producer)
    monkeypatch.setattr(events_mod, "KAFKA_AVAILABLE", True)

    async def _always_fails(event):
        raise ValueError("handler boom")

    consumer = EventConsumer(group_id="g")
    consumer._mode = "kafka"
    consumer.MAX_HANDLER_RETRIES = 0
    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _always_fails)

    await consumer.process(_event())
    await consumer.process(_event())

    assert len(created) == 1, "a producer per dead letter would leak connections"
    producer = created[0]
    assert producer.started is True
    # A dead letter that is not durably replicated reads as safely quarantined
    # while being nothing of the sort.
    assert producer.kwargs["acks"] == "all"
    assert [topic for topic, _ in producer.sent] == [Topic.DEAD_LETTER.value] * 2
    assert consumer.dlq_depth == 0

    await consumer.stop()
    assert producer.started is False, "buffered dead letters were not flushed"


# ── defect 6: the restart budget is a rate limit, not a lifetime quota ───────


async def test_restart_budget_resets_after_a_sustained_healthy_run(monkeypatch):
    """Regression: six transient crashes over weeks failed a role permanently.

    ``attempt`` was a ``_guard`` local that only ever grew, so ``max_restarts``
    counted crashes across the whole life of the process rather than the life of
    an incident.
    """
    recorder = _MetricsRecorder()
    monkeypatch.setattr(supervisor_mod, "metrics", recorder)
    runs = {"n": 0}

    async def _occasionally_flaky():
        runs["n"] += 1
        if runs["n"] == 1:
            raise RuntimeError("transient blip")
        if runs["n"] == 2:
            # Recovered and ran normally, then an unrelated failure much later.
            await asyncio.sleep(0.08)
            raise RuntimeError("second, unrelated blip")
        await asyncio.Event().wait()

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(
        WorkerSpec(
            name="flaky_relay", factory=_occasionally_flaky, role="outbox-relay",
            max_restarts=1, backoff_base_s=0.001, healthy_run_s=0.05,
        )
    )
    await supervisor.start_all()
    try:
        await _wait_for(lambda: runs["n"] == 3)
        await _wait_for(
            lambda: supervisor.status()["flaky_relay"]["state"] == "running"
        )
        info = supervisor.status()["flaky_relay"]
        # With a lifetime quota the second crash exhausted max_restarts=1 and
        # the role was marked failed forever.
        assert info["state"] == "running"
        assert info["restarts"] == 1, "budget consumed once since the reset"
        # The reset must not erase the evidence that this worker flaps. Kept off
        # status(), whose key set is a pinned contract.
        assert supervisor.restart_totals()["flaky_relay"] == 2
        assert supervisor.status_by_role()["outbox-relay"]["healthy"] is True
        assert supervisor.unhealthy_roles() == {}
        assert {"worker": "flaky_relay", "role": "outbox-relay"} in recorder.labels_for(
            "worker_supervisor_restart_budget_reset"
        )
    finally:
        await supervisor.stop_all()


async def test_budget_reset_does_not_rescue_a_crash_loop(monkeypatch):
    """The budget still has to stop something — a tight loop never earns it back."""
    recorder = _MetricsRecorder()
    monkeypatch.setattr(supervisor_mod, "metrics", recorder)

    async def _always_crashes():
        raise RuntimeError("hard down")

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(
        WorkerSpec(
            name="doomed_projector", factory=_always_crashes, role="graph-writer",
            max_restarts=2, backoff_base_s=0.001, healthy_run_s=0.05,
        )
    )
    await supervisor.start_all()
    try:
        await _wait_for(
            lambda: supervisor.status()["doomed_projector"]["state"] == "failed"
        )
        assert recorder.labels_for("worker_supervisor_restart_budget_reset") == []
        # And the degradation is announced the moment it happens, not only at
        # shutdown — status_by_role() was previously read in exactly one place.
        assert {"worker": "doomed_projector", "role": "graph-writer"} in recorder.labels_for(
            "worker_supervisor_role_unhealthy"
        )
        assert set(supervisor.unhealthy_roles()) == {"graph-writer"}
    finally:
        await supervisor.stop_all()


# ── defect 2: the drain path has to be reachable in ECS ──────────────────────


async def test_shutdown_signals_release_the_wait():
    """Regression: nothing ever set the stop event, so ``_shutdown`` was dead code.

    ECS sends SIGTERM then SIGKILL at ``stopTimeout``. With no handler a
    default-disposition process dies before ``finally``; at PID 1 — the normal
    container case — the kernel refuses to deliver SIGTERM at all unless a
    handler is installed. Either way the drain never ran.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        stop = asyncio.Event()
        uninstall = run_role._install_shutdown_signals(stop, "lean-worker")
        try:
            signal.raise_signal(sig)
            await asyncio.wait_for(stop.wait(), 5)
        finally:
            uninstall()
        assert stop.is_set(), f"{sig.name} did not release the shutdown wait"
        # Uninstalled cleanly: handlers are process-global, and a stale one
        # bound to a closed loop breaks the next asyncio.run in this process.
        assert loop.remove_signal_handler(sig) is False


async def test_run_workers_drains_and_shuts_down_on_sigterm(monkeypatch):
    """End-to-end: the signal really does drive ``_shutdown`` to completion."""
    import dependencies.providers as providers_mod
    import services.runtime as runtime_pkg

    class _FakeRuntimeRegistry:
        def __init__(self) -> None:
            self.started = 0
            self.stopped = 0

        async def startup(self) -> None:
            self.started += 1

        async def shutdown(self) -> None:
            self.stopped += 1

    registry = _FakeRuntimeRegistry()
    monkeypatch.setattr(providers_mod, "get_registry", lambda: registry)
    monkeypatch.setattr(runtime_pkg, "build_worker_specs", lambda **kwargs: [])
    monkeypatch.setattr(runtime_pkg, "specs_for_role", lambda role, specs: [])
    monkeypatch.setattr(runtime_pkg, "consumer_specs_for_role", lambda role, settings: [])

    # Signalling before the handler is installed would kill the test process, so
    # wait for the real installer to run rather than guessing at a sleep.
    installed = asyncio.Event()
    real_install = run_role._install_shutdown_signals

    def _spy(stop, role):
        uninstall = real_install(stop, role)
        installed.set()
        return uninstall

    monkeypatch.setattr(run_role, "_install_shutdown_signals", _spy)

    task = asyncio.create_task(run_role._run_workers("maintenance"))
    await asyncio.wait_for(installed.wait(), 5)
    signal.raise_signal(signal.SIGTERM)
    rc = await asyncio.wait_for(task, 5)

    assert rc == 0
    assert registry.started == 1
    # The ``finally`` ran: registry.shutdown() is the last step of _shutdown, so
    # reaching it proves the whole drain path executed. Without a signal handler
    # this await never returns and the process is SIGKILLed instead.
    assert registry.stopped == 1


async def test_health_watch_announces_a_permanently_failed_role(monkeypatch, capsys):
    """A failed role must be loud while the task is alive, not only at exit."""
    recorder = _MetricsRecorder()
    monkeypatch.setattr(supervisor_mod, "metrics", recorder)
    watch_metrics = _MetricsRecorder()
    import shared.logger.logger as logger_mod

    async def _always_crashes():
        raise RuntimeError("hard down")

    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    supervisor.register(
        WorkerSpec(
            name="doomed", factory=_always_crashes, role="measurement-worker",
            max_restarts=0,
        )
    )
    await supervisor.start_all()
    try:
        await _wait_for(lambda: supervisor.status()["doomed"]["state"] == "failed")
        monkeypatch.setattr(logger_mod, "metrics", watch_metrics)
        watch = asyncio.create_task(
            run_role._watch_role_health(supervisor, "lean-worker", 0.01)
        )
        await _wait_for(lambda: watch_metrics.labels_for("runtime_role_unhealthy"))
        watch.cancel()
        try:
            await watch
        except asyncio.CancelledError:
            pass
    finally:
        await supervisor.stop_all()

    assert {"role": "measurement-worker", "booted_as": "lean-worker"} in (
        watch_metrics.labels_for("runtime_role_unhealthy")
    )
    out = capsys.readouterr().out
    assert "role=measurement-worker UNHEALTHY" in out
