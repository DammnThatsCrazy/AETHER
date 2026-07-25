"""Aether Runtime — per-role consumer runners.

Why this module exists
----------------------
``dependencies/providers.py`` gives the resource registry a *single*
``EventConsumer``, and ``EventConsumer.start()`` binds to exactly one queue.
That is sufficient while every logical role owns its own process, because there
is only ever one queue to bind. It stops being sufficient the moment a
consolidated execution group (``lean-worker``) hosts several logical roles in
one process: the process then has to consume from several queues at once, with
each role keeping its own consumer group, backpressure envelope, retry policy
and drain budget.

Consumers are therefore split into several independent runners rather than
multiplexed onto one. What they are split *by* is mode-dependent, because the
resource a consumer contends for is not the same on both brokers:

- **``sns_sqs`` → one consumer per role (per resolved queue).** Terraform
  provisions exactly one queue per role (``aws_sqs_queue.role``,
  ``for_each = var.consumer_role_queues``, keyed by role) and subscribes it to
  the SNS topic with **no filter policy**, so every role queue receives every
  event. SQS has no consumer-group concept: two consumers polling one queue
  *compete* for messages instead of each receiving a copy, and
  ``_sqs_receive_loop`` deletes a message once its receiving consumer finishes.
  Splitting one role's handlers across two consumers on one queue would drop
  every message that happened to land on the consumer without a handler for it
  — silent data loss. So all of a role's specs share one consumer here, exactly
  as ``attach_consumer_specs`` does today.
- **``kafka`` → one consumer per ``(role, group_id)``.** A Kafka consumer group
  genuinely is an independent subscription — each group receives a full copy of
  the topic — so groups are the correct split and give each pipeline its own
  offsets and its own lag.

Either way the guarantees that matter hold:

- **Queue isolation.** Each consumer binds its own queue URL, resolved by role
  from the ``SQS_ROLE_QUEUE_URLS`` map. :func:`build_consumer_runners` enforces
  that no two consumers in one process ever share a queue.
- **Group isolation.** Each consumer pins a real ``group_id`` rather than the
  fallback ``aether-backend-<env>`` group that ``attach_consumer_specs`` leaves
  in place whenever the selected specs disagree on one.
- **Backpressure isolation.** Each consumer sizes its own semaphore from the max
  ``concurrency`` across *its own* specs, so a slow role cannot consume another
  role's in-flight budget. A single shared consumer could only enforce one
  global max.
- **Failure isolation.** Each receive loop is an independent supervised task
  (see :meth:`ConsumerRunner.worker_spec`), so one role's crash is surfaced and
  restarted without disturbing the others. Nothing here is a serial loop.
- **Drain isolation.** Each consumer drains against its own longest declared
  ``drain_timeout_s`` and reports its own per-role result. A drain quiesces the
  consumer *before* releasing its client, so work that completes mid-shutdown is
  still acknowledged rather than redelivered.
- **Dead-letter isolation.** Each consumer binds its own dead-letter queue,
  resolved by role from ``SQS_ROLE_DLQ_URLS``. A dead letter is never published
  onto a queue this process consumes from — doing so deletes the event, because
  nothing subscribes ``Topic.DEAD_LETTER`` and an unhandled message is acked.

In a dedicated deployment the selection collapses to exactly one runner, so
``production-scale`` / ``enterprise-isolated`` behaviour is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Callable, Optional, Sequence

from services.runtime.consumer_specs import (
    ConsumerSpec,
    apply_consumer_limits,
    drain_timeout_for,
)
from services.runtime.supervisor import WorkerSpec
from shared.events.events import EventConsumer, _event_broker
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.runtime.consumer_runner")

# JSON object mapping a role (or the more specific "<role>:<group_id>") onto the
# queue that role consumes from. Introduced because SQS_QUEUE_URL can only name
# one queue, which a consolidated process cannot work with.
ROLE_QUEUE_URLS_ENV = "SQS_ROLE_QUEUE_URLS"
# Single-queue fallback: the dedicated-deployment configuration, still correct
# when the process hosts exactly one queue-bound role.
DEFAULT_QUEUE_URL_ENV = "SQS_QUEUE_URL"

# The dead-letter mirror of the two variables above. A dead letter must reach a
# destination this process does not consume from — publishing one back onto the
# source queue destroys it (see EventConsumer._resolve_dlq_target) — and a
# consolidated process dead-letters on behalf of several roles that each own a
# separate dead-letter queue, so one process-wide URL cannot express it.
ROLE_DLQ_URLS_ENV = "SQS_ROLE_DLQ_URLS"
DEFAULT_DLQ_URL_ENV = "SQS_DLQ_QUEUE_URL"

# Runner lifecycle states surfaced by ConsumerRunner.status().
STATE_CREATED = "created"
STATE_RUNNING = "running"
STATE_DRAINING = "draining"
STATE_STOPPED = "stopped"

# Modes in which a receive loop is expected to keep pulling from a broker. In
# any other mode ("in-memory") events arrive via direct process() calls.
_BROKER_MODES = ("kafka", "sqs")

# Poll interval while waiting for in-flight handlers to finish during a drain.
_DRAIN_POLL_S = 0.02


class ConsumerLoopExited(RuntimeError):
    """A broker receive loop returned while the runner was still meant to run.

    ``EventConsumer.consume_loop`` / ``_sqs_receive_loop`` catch their own
    exceptions and return normally, which a supervisor would otherwise read as
    clean completion and never restart. Converting an unexpected return into a
    raise is what lets the shared :class:`WorkerSupervisor` apply its existing
    crash → metric → backoff-restart policy to consumer pipelines too.
    """


def _parse_url_map(env_var: str, raw: Optional[str]) -> dict[str, str]:
    """Parse a ``{role: url}`` JSON object from ``env_var``.

    Malformed JSON fails closed rather than degrading to the single-URL
    fallback: silently binding every role to one queue is precisely the outage
    these maps exist to prevent.
    """
    payload = os.getenv(env_var, "") if raw is None else raw
    payload = payload.strip()
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{env_var} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"{env_var} must be a JSON object mapping role -> queue url, "
            f"got {type(parsed).__name__}"
        )
    return {str(key): str(value) for key, value in parsed.items()}


def role_queue_urls(raw: Optional[str] = None) -> dict[str, str]:
    """Parse ``SQS_ROLE_QUEUE_URLS`` into a ``{role: queue_url}`` mapping."""
    return _parse_url_map(ROLE_QUEUE_URLS_ENV, raw)


def role_dlq_urls(raw: Optional[str] = None) -> dict[str, str]:
    """Parse ``SQS_ROLE_DLQ_URLS`` into a ``{role: dlq_queue_url}`` mapping."""
    return _parse_url_map(ROLE_DLQ_URLS_ENV, raw)


def resolve_queue_url(role: str, *, mapping: Optional[dict[str, str]] = None) -> str:
    """Resolve the queue ``role`` consumes from.

    Keyed by role and only by role, because that is what the infrastructure
    provisions: ``modules/sqs/main.tf`` creates one ``aws_sqs_queue.role`` per
    entry of ``var.consumer_role_queues``. There is deliberately no per-group
    key — inventing one would imply queues Terraform does not create, and the
    ``sns_sqs`` keying in :func:`build_consumer_runners` means a role never
    needs more than one.

    Falls back to ``SQS_QUEUE_URL``, which is still correct for a dedicated
    deployment hosting exactly one queue-bound role.
    """
    table = role_queue_urls() if mapping is None else mapping
    return table.get(role) or os.getenv(DEFAULT_QUEUE_URL_ENV, "")


def resolve_dlq_url(role: str, *, mapping: Optional[dict[str, str]] = None) -> str:
    """Resolve the dead-letter queue ``role`` publishes poison events to.

    Keyed by role for the same reason as :func:`resolve_queue_url`:
    ``modules/sqs/main.tf`` already creates one ``aws_sqs_queue.role_dlq`` per
    entry of ``var.consumer_role_queues``, so a per-role destination genuinely
    exists — it is simply not yet passed to the process.

    Returns ``""`` when nothing is configured. That is not a silent fallback:
    :meth:`EventConsumer._resolve_dlq_target` refuses to publish without a
    target, leaving the poison message unacknowledged so SQS's own redrive
    policy quarantines it. An unconfigured DLQ costs redeliveries, never the
    event.
    """
    table = role_dlq_urls() if mapping is None else mapping
    return table.get(role) or os.getenv(DEFAULT_DLQ_URL_ENV, "")


class _RegistryConsumerView:
    """The real registry with ``.consumer`` swapped for one runner's consumer.

    ``ConsumerSpec.handler_factory`` subscribes through ``registry.consumer``
    and also reaches for ``registry.producer`` / ``.cache`` / ``.graph``. This
    view lets each runner attach *only its own* group's handlers to *its own*
    consumer while every other shared resource still resolves to the single
    real registry — no handler code changes, no duplicated connections.
    """

    def __init__(self, registry: Any, consumer: EventConsumer) -> None:
        self._registry = registry
        self._consumer = consumer

    @property
    def consumer(self) -> EventConsumer:
        return self._consumer

    def __getattr__(self, name: str) -> Any:
        # Only reached for attributes this view does not define itself.
        return getattr(self._registry, name)


class ConsumerRunner:
    """One ``EventConsumer`` and everything it owns.

    Covers one role's queue under ``sns_sqs`` and one ``(role, group_id)``
    subscription under ``kafka`` — see the module docstring for why the split
    differs. Owns that unit's queue binding, handler set, backpressure envelope,
    receive loop and drain. Construction attaches handlers (so ``start()`` can
    see the subscribed topics); ``start()`` binds the broker; the receive loop
    runs as an independent supervised task obtained from :meth:`worker_spec`.
    """

    def __init__(
        self,
        *,
        role: str,
        group_id: str,
        specs: Sequence[ConsumerSpec],
        registry: Any,
        queue_url: str = "",
        dlq_queue_url: str = "",
        consumer_factory: Optional[Callable[..., EventConsumer]] = None,
    ) -> None:
        if not specs:
            raise ValueError(f"ConsumerRunner for {role}/{group_id} needs at least one spec")
        if dlq_queue_url and dlq_queue_url == queue_url:
            # Fail at construction rather than at the first poison event: a
            # dead letter published onto its own source queue is consumed as an
            # unhandled topic and deleted, destroying the event.
            raise RuntimeError(
                f"dead-letter queue for role {role} is its own source queue "
                f"({queue_url}). Give the role a distinct entry in "
                f"{ROLE_DLQ_URLS_ENV}."
            )
        self.role = role
        # The group pinned onto the EventConsumer. Under sns_sqs a role's specs
        # may declare several groups; the pin is then cosmetic (SQS has no
        # groups) and ``group_ids`` records the full set for observability.
        self.group_id = group_id
        self.specs: tuple[ConsumerSpec, ...] = tuple(specs)
        self.group_ids: tuple[str, ...] = tuple(
            dict.fromkeys(spec.group_id for spec in self.specs)
        )
        self.queue_url = queue_url
        self.dlq_queue_url = dlq_queue_url

        factory = consumer_factory or EventConsumer
        self._consumer = factory(
            group_id=group_id, queue_url=queue_url, dlq_queue_url=dlq_queue_url,
        )
        # Per-group backpressure and retry envelope — never a process-wide max.
        apply_consumer_limits(self._consumer, self.specs)

        # Attach only this group's handlers to this group's consumer.
        view = _RegistryConsumerView(registry, self._consumer)
        for spec in self.specs:
            spec.handler_factory(view)

        self._drain_timeout_s = drain_timeout_for(self.specs)
        self._required = any(spec.required for spec in self.specs)
        self._stopping = False
        self._state = STATE_CREATED
        self._last_error: Optional[str] = None

    # ── accessors ─────────────────────────────────────────────────────────

    @property
    def consumer(self) -> EventConsumer:
        return self._consumer

    @property
    def name(self) -> str:
        """Stable identity used for the supervised worker name and log lines."""
        return f"consumer:{self.role}:{self.group_id}"

    @property
    def spec_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.specs)

    @property
    def drain_timeout_s(self) -> float:
        return self._drain_timeout_s

    @property
    def required(self) -> bool:
        return self._required

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Bind this runner's consumer to its broker/queue."""
        await self._consumer.start()
        self._state = STATE_RUNNING
        logger.info(
            "consumer_runner_started role=%s group=%s mode=%s queue=%s "
            "max_concurrent=%d max_handler_retries=%d specs=%s",
            self.role,
            self.group_id,
            self._consumer.mode,
            self._consumer.queue_url or "(none)",
            self._consumer.MAX_CONCURRENT,
            self._consumer.MAX_HANDLER_RETRIES,
            ",".join(self.spec_names),
        )

    def worker_spec(self, *, max_restarts: int = 5, backoff_base_s: float = 2.0) -> WorkerSpec:
        """Describe this runner's receive loop as a supervised worker.

        Registering consumer pipelines with the same :class:`WorkerSupervisor`
        that runs loop workers is what gives them independent crash isolation,
        exponential-backoff restart and per-role state for free, instead of
        reimplementing that machinery here.
        """
        return WorkerSpec(
            name=self.name,
            factory=self._supervised_receive_loop,
            required=self._required,
            role=self.role,
            max_restarts=max_restarts,
            backoff_base_s=backoff_base_s,
        )

    async def _supervised_receive_loop(self) -> None:
        """Fresh coroutine per supervised (re)start of this runner's loop."""
        if self._stopping:
            # Shutdown raced the restart: complete cleanly rather than rebinding
            # a broker connection we are in the middle of tearing down.
            self._state = STATE_STOPPED
            return

        if not self._consumer.is_running and self._consumer.mode in _BROKER_MODES:
            # Restart path: the crashed loop left the broker binding torn down.
            await self._consumer.start()

        self._state = STATE_RUNNING
        await self._consumer.receive_loop()

        if self._stopping:
            self._state = STATE_STOPPED
            return
        if self._consumer.mode not in _BROKER_MODES:
            # In-memory mode has no poll loop; events arrive through direct
            # process() calls. Park so the supervised task stays alive (and
            # cancellable) instead of "completing" and never running again.
            self._state = STATE_RUNNING
            await asyncio.Event().wait()
            return

        # A broker loop that returns on its own has stopped consuming. Raise so
        # the supervisor counts it, labels it with this role, and restarts it.
        self._last_error = (
            f"receive loop exited unexpectedly (mode={self._consumer.mode})"
        )
        raise ConsumerLoopExited(
            f"consumer receive loop for role={self.role} group={self.group_id} "
            f"exited unexpectedly (mode={self._consumer.mode})"
        )

    async def drain(self, timeout: Optional[float] = None) -> dict[str, Any]:
        """Quiesce this consumer, then release its broker client.

        Order is the whole point, and the previous order was backwards. It
        called ``consumer.stop()`` first — which sets ``_sqs_client = None`` —
        and only then waited for in-flight handlers. Every handler that
        completed during that wait had its ``delete_message`` fail with
        ``AttributeError`` against the ``None`` client, the receive loop
        swallowed it, and SQS redelivered the message once its visibility
        timeout expired. Not an edge case: every message in the batch being
        processed, on every consumer, on every deploy.

        The correct sequence, and the one implemented here:

        1. :meth:`EventConsumer.pause` — stop pulling *new* work. The client
           stays bound, so acknowledgements still work.
        2. Wait for the consumer to be genuinely quiesced: no handler running
           **and** nothing unacknowledged. Waiting on handlers alone is not
           enough, because ``in_flight`` returns to zero the moment a handler
           returns, while the delete/commit for that same message is still
           outstanding — the tear-down would land in exactly that window.
        3. Only then :meth:`EventConsumer.stop`, releasing the clients.

        Returns a per-role drain report. Idempotent. Never raises: a shutdown
        path that fails to stop one role must still drain the rest.
        """
        self._stopping = True
        self._state = STATE_DRAINING
        budget = self._drain_timeout_s if timeout is None else timeout

        # Step 1 — stop acquiring. Handlers already running are unaffected, and
        # the client they need to acknowledge through is still bound.
        self._consumer.pause()

        # Step 2 — wait for both quiescence conditions within the budget.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(budget, 0.0)
        while (
            self._consumer.in_flight > 0 or self._consumer.unacked > 0
        ) and loop.time() < deadline:
            await asyncio.sleep(_DRAIN_POLL_S)

        remaining = self._consumer.in_flight
        unacked = self._consumer.unacked

        # Step 3 — release the clients. Anything still outstanding at this point
        # is already reported as an incomplete drain below.
        try:
            await self._consumer.stop()
        except Exception as exc:  # pragma: no cover — defensive
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.error(
                "consumer_runner_stop_failed role=%s group=%s error=%s",
                self.role, self.group_id, self._last_error,
            )

        self._state = STATE_STOPPED
        report = {
            "role": self.role,
            "group_id": self.group_id,
            "specs": list(self.spec_names),
            "drained": remaining == 0 and unacked == 0,
            "in_flight_remaining": remaining,
            "unacked_remaining": unacked,
            "timeout_s": budget,
        }
        if remaining or unacked:
            metrics.increment(
                "consumer_drain_incomplete",
                labels={"role": self.role, "group": self.group_id},
            )
            logger.error(
                "consumer_drain_incomplete role=%s group=%s in_flight=%d "
                "unacked=%d timeout_s=%.3f — unacknowledged messages will be "
                "redelivered",
                self.role, self.group_id, remaining, unacked, budget,
            )
        else:
            logger.info(
                "consumer_drained role=%s group=%s timeout_s=%.3f",
                self.role, self.group_id, budget,
            )
        return report

    # ── introspection ─────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Per-runner status, always carrying the owning logical role."""
        return {
            "role": self.role,
            "group_id": self.group_id,
            "group_ids": list(self.group_ids),
            "state": self._state,
            "specs": list(self.spec_names),
            "mode": self._consumer.mode,
            "queue_url": self._consumer.queue_url or self.queue_url,
            # Empty means no dead-letter destination is configured for this
            # role, which is a real operational state worth seeing in status:
            # poison events will be redelivered until SQS's redrive policy
            # quarantines them, rather than being published on the first failure.
            "dlq_queue_url": self.dlq_queue_url,
            "max_concurrent": self._consumer.MAX_CONCURRENT,
            "max_handler_retries": self._consumer.MAX_HANDLER_RETRIES,
            "in_flight": self._consumer.in_flight,
            "unacked": self._consumer.unacked,
            "dlq_depth": self._consumer.dlq_depth,
            "required": self._required,
            "last_error": self._last_error,
        }


def is_queue_keyed(broker: Optional[str] = None) -> bool:
    """True when consumers must be keyed by queue (role) rather than by group.

    ``sns_sqs`` is queue-keyed because an SQS queue is the contended resource
    and has no group semantics; ``kafka`` is group-keyed because a consumer
    group is a real independent subscription.
    """
    resolved = (broker if broker is not None else _event_broker()).lower()
    return resolved == "sns_sqs"


def build_consumer_runners(
    registry: Any,
    specs: Sequence[ConsumerSpec],
    *,
    broker: Optional[str] = None,
    queue_urls: Optional[dict[str, str]] = None,
    dlq_urls: Optional[dict[str, str]] = None,
    consumer_factory: Optional[Callable[..., EventConsumer]] = None,
) -> list[ConsumerRunner]:
    """Build the consumer runners for ``specs`` under the active broker.

    Keying is mode-dependent (see the module docstring): one runner per **role**
    under ``sns_sqs``, one per **(role, group_id)** under ``kafka``. Grouping
    preserves ``CONSUMER_SPECS`` order so runner order is deterministic across
    boots. A single-role selection yields exactly one runner under either mode,
    which is why dedicated deployments are unchanged.
    """
    if not specs:
        return []

    queue_keyed = is_queue_keyed(broker)

    grouped: dict[tuple[str, str], list[ConsumerSpec]] = {}
    for spec in specs:
        # Under sns_sqs every spec of a role shares that role's single queue, so
        # they must share one consumer: two consumers on one queue would compete
        # for messages and delete the ones they cannot handle.
        key = (spec.role, "") if queue_keyed else (spec.role, spec.group_id)
        grouped.setdefault(key, []).append(spec)

    mapping = role_queue_urls() if queue_urls is None else queue_urls
    dlq_mapping = role_dlq_urls() if dlq_urls is None else dlq_urls
    runners: list[ConsumerRunner] = []
    for (role, _key_group), group_specs in grouped.items():
        runners.append(
            ConsumerRunner(
                role=role,
                # Representative pin: the first declared group in canonical
                # order, which is the only group under kafka keying.
                group_id=group_specs[0].group_id,
                specs=group_specs,
                registry=registry,
                # Queue URLs are an SQS concern; under kafka the binding is the
                # bootstrap + group, so resolving a queue would be meaningless
                # (and would make every runner look like it shares one queue).
                queue_url=resolve_queue_url(role, mapping=mapping) if queue_keyed else "",
                # Same reasoning: dead-letter queues are an SQS concern. Under
                # kafka the durable dead-letter destination is the DEAD_LETTER
                # topic, which needs no per-role binding.
                dlq_queue_url=resolve_dlq_url(role, mapping=dlq_mapping) if queue_keyed else "",
                consumer_factory=consumer_factory,
            )
        )

    _assert_distinct_queues(runners)
    return runners


def _assert_distinct_queues(runners: Sequence[ConsumerRunner]) -> None:
    """Fail closed if two consumers in this process resolve to the same queue.

    This is the invariant the whole module exists to uphold. Two consumers on
    one SQS queue split its messages rather than each receiving a copy, so
    whichever consumer receives a message it has no handler for will do nothing
    and then delete it — silent, unrecoverable data loss. An empty URL just
    means in-memory mode and is not a binding, so it is not checked.
    """
    by_url: dict[str, list[ConsumerRunner]] = {}
    for runner in runners:
        if runner.queue_url:
            by_url.setdefault(runner.queue_url, []).append(runner)
    collisions = {url: sharing for url, sharing in by_url.items() if len(sharing) > 1}
    if not collisions:
        return
    detail = "; ".join(
        f"{url} <- {', '.join(f'{r.role}/{r.group_id}' for r in sharing)}"
        for url, sharing in sorted(collisions.items())
    )
    raise RuntimeError(
        "consumer queue collision: distinct consumers resolved to the same queue "
        f"({detail}). Under SQS they would compete for messages and delete the "
        f"ones they cannot handle. Give each role its own entry in "
        f"{ROLE_QUEUE_URLS_ENV}."
    )


async def start_consumer_runners(runners: Sequence[ConsumerRunner]) -> None:
    """Bind every runner's broker connection, concurrently.

    Concurrent because binding is I/O-bound and a consolidated process may hold
    six of them; a serial boot would multiply broker connect latency by the
    number of hosted roles. A failure is re-raised with the owning role named,
    so a failed bind is attributable rather than anonymous.
    """
    if not runners:
        return
    results = await asyncio.gather(
        *(runner.start() for runner in runners), return_exceptions=True
    )
    failures = [
        (runner, result)
        for runner, result in zip(runners, results)
        if isinstance(result, BaseException)
    ]
    if failures:
        for runner, exc in failures:
            metrics.increment(
                "consumer_runner_start_failed",
                labels={"role": runner.role, "group": runner.group_id},
            )
            logger.error(
                "consumer_runner_start_failed role=%s group=%s error=%s: %s",
                runner.role, runner.group_id, type(exc).__name__, exc,
            )
        first_runner, first_exc = failures[0]
        raise RuntimeError(
            f"consumer runner(s) failed to start: "
            f"{', '.join(f'{r.role}/{r.group_id}' for r, _ in failures)}"
        ) from first_exc


async def drain_consumer_runners(
    runners: Sequence[ConsumerRunner],
) -> list[dict[str, Any]]:
    """Drain every runner concurrently and return their per-role reports.

    Concurrent so the shutdown budget is the *longest* role's drain rather than
    the sum of them — a serial drain would exceed the orchestrator's stop
    timeout and turn a graceful shutdown into a kill.
    """
    if not runners:
        return []
    return list(await asyncio.gather(*(runner.drain() for runner in runners)))


def consumer_runner_status(runners: Sequence[ConsumerRunner]) -> dict[str, dict[str, Any]]:
    """Status map keyed by runner name, for readiness and diagnostics."""
    return {runner.name: runner.status() for runner in runners}
