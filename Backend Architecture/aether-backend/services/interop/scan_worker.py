"""Durable Interoperability scan-loop worker.

One governed cycle (``ScanWorker.run_cycle``) drives one provider adapter
through: load checkpoint -> supervised :meth:`scan` -> correlation ingest ->
dead-letter quarantine -> reconciliation evidence -> graph projection ->
policy snapshot -> event publish -> checkpoint persist -> metering.

Resume contract: the checkpoint (per-network cursors + ``runtime`` telemetry)
is persisted under ``interop_provider_checkpoints.evidence`` keyed
(tenant_id, provider_id, network_id='*'). A worker killed mid-cycle restarts
from the last persisted checkpoint — never from scratch — so the cursor never
moves backward and a re-run of the same checkpoint is idempotent (the
adapter's windowed scan returns no observations, the message repo's conflict
key dedups replays). ``runtime`` counters (decode_failures, reorg_count,
dead_letter_count, reconciliation_conflicts, last_success/last_failure)
survive restarts inside the checkpoint.

``build_interop_scan_coro`` is the poll loop the runtime worker spec imports
from ``services.interop.scan_worker`` (gated on
``settings.interop.adapters_enabled``).

This module also re-homes the branch-only scan wiring that main never carried:
:class:`InteropGraphProjector` (drives main's
``services.interop.graph_mutations.build_topology_mutations`` /
``build_message_mutations`` through ``foundation.persist_mutations``),
:class:`InteropEventPublisher` (converts ``make_event`` dicts to shared
:class:`Event` objects handed to the shared :class:`EventProducer`), and
:class:`RpcRateLimited` (the adapter rate-limit sentinel the cycle catches as a
``rate_limited`` resume).
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from config.settings import settings
from repositories.interop_repos import (
    InteropProviderCheckpointRepo,
    InteropMessageRepo,
    InteropMessageEventRepo,
)
from services.interop.correlation import CorrelationEngine
from services.interop.foundation import (
    GraphProjectionResult,
    deterministic_id,
    deterministic_idempotency_key,
    persist_mutations,
    utc_now_iso,
)
from services.interop.graph_mutations import (
    build_message_mutations,
    build_topology_mutations,
)
from services.interop.providers import INTEROP_PROVIDERS, get_provider
from services.interop.reconcile import InteropReconciler
from services.interop.security import SecurityPolicyService
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.interop.scan_worker")

POLL_INTERVAL_SECONDS = 30.0
SENTINEL_NETWORK = "*"

_SOURCE_SERVICE = "interoperability_intelligence"

# event_name -> Topic. Events not listed fall back to CANONICAL_ACTIVITY_INGESTED.
_TOPIC_MAP: dict[str, Topic] = {
    "interop_security_policy_changed": Topic.INTEROP_SECURITY_POLICY_CHANGED,
    "interop_message_stuck": Topic.INTEROP_MESSAGE_STUCK,
}


class RpcRateLimited(Exception):
    """Adapter rate-limit sentinel (HTTP 429 or protocol throttling).

    A scan that raises this reports a ``rate_limited`` cycle and does NOT
    advance the checkpoint — the worker resumes from the last fully-scanned
    window next poll. Adapters on main raise their own provider-native
    rate-limit exceptions; this sentinel is the cycle-level contract for
    adapters (fixture or live) that surface throttling out of ``scan``.
    """

    def __init__(self, message: str, *, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _topic_for(event_name: str) -> Topic:
    """The Topic a registry event should be published under."""
    return _TOPIC_MAP.get(event_name, Topic.CANONICAL_ACTIVITY_INGESTED)


class InteropEventPublisher:
    """Publish seam: ``make_event`` dicts -> :class:`Event` -> ``EventProducer``.

    The broker connection is owned by the injected :class:`EventProducer`
    (``connect()`` is a no-op re-entrancy guard on the producer). Publishing is
    a real call on every environment; local dev lands in the producer's
    in-memory list, staging/production lands on Kafka/SQS. A failed publish
    raises after the producer's own retries — the scan worker treats that as a
    cycle failure so checkpoints do not advance past an undelivered event batch.
    """

    def __init__(self, producer: Optional[EventProducer] = None) -> None:
        self._producer = producer or EventProducer()
        self._source_service = _SOURCE_SERVICE
        self._published: list[Event] = []

    async def connect(self) -> None:
        await self._producer.connect()

    async def publish(self, event_dict: dict[str, Any], correlation_id: str = "") -> Event:
        """Publish one ``make_event`` dict; returns the built :class:`Event`."""
        event = self._to_event(event_dict, correlation_id)
        await self._producer.publish(event)
        self._published.append(event)
        return event

    async def publish_batch(
        self, event_dicts: list[dict[str, Any]], correlation_id: str = "",
    ) -> list[Event]:
        """Publish many ``make_event`` dicts in one batch; returns built Events."""
        events = [self._to_event(ed, correlation_id) for ed in event_dicts]
        if not events:
            return []
        await self._producer.publish_batch(events)
        self._published.extend(events)
        return events

    @property
    def published(self) -> list[Event]:
        """Local mirror of everything published through this seam (tests)."""
        return list(self._published)

    def _to_event(self, event_dict: dict[str, Any], correlation_id: str) -> Event:
        event_name = event_dict.get("event_name") or "interop_observation"
        payload = dict(event_dict.get("payload") or {})
        payload.setdefault("event_name", event_name)
        return Event(
            topic=_topic_for(event_name),
            payload=payload,
            tenant_id=event_dict.get("tenant_id") or "",
            timestamp=event_dict.get("occurred_at") or utc_now_iso(),
            source_service=self._source_service,
            correlation_id=correlation_id,
        )


def _extract_topology(
    observations: list[dict[str, Any]], provider: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Derive the provider's gateways and paths from one cycle's observations.

    Deterministic and idempotent: gateways/paths are keyed by stable ids
    derived from the observation refs, so re-projecting a replayed cycle
    produces identical mutations (the graph outbox dedups on those ids).
    """
    gateways: dict[str, dict[str, Any]] = {}
    paths: dict[str, dict[str, Any]] = {}
    for observation in observations:
        endpoint = observation.get("endpoint_ref") or {}
        gateway_id = endpoint.get("gateway_id")
        if gateway_id:
            gateways[gateway_id] = {
                "gateway_id": gateway_id,
                "network_id": endpoint.get("network_id", ""),
                "native_chain_id": endpoint.get("native_chain_id", ""),
                "gateway_role": observation.get("phase", "unknown"),
            }
        source = observation.get("source_network_id")
        destination = observation.get("destination_network_id")
        if source and destination:
            path_id = observation.get(
                "path_id",
                f"{provider.get('provider_id', 'interop')}:{source}->{destination}",
            )
            paths[path_id] = {
                "path_id": path_id,
                "source_network_id": source,
                "destination_network_id": destination,
                "source_gateway_id": endpoint.get("gateway_id"),
                "destination_gateway_id": None,
            }
    return list(gateways.values()), list(paths.values())


def _policy_from_observation(
    provider: Any, observation: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Derive a deterministic, offline security policy for one observation.

    Uses the adapter's structural ``security_model()`` (available without
    credentials) plus the observation's network confirmations. The content
    hash changes when the provider's structural verification model changes —
    the drift surface the SecurityPolicyService exists to detect.
    """
    model = getattr(provider, "security_model", None)
    if not callable(model):
        return None
    try:
        sm = model() or {}
    except Exception:  # noqa: BLE001 — structural model unavailable
        return None
    if not sm:
        return None
    endpoint = observation.get("endpoint_ref") or {}
    confirmations = endpoint.get("confirmations_required")
    return {
        "verification_model": sm.get("verification_model", "unknown"),
        "required_verifier_ids": sm.get("required_verifier_ids", []),
        "optional_verifier_ids": sm.get("optional_verifier_ids", []),
        "optional_threshold": sm.get("optional_threshold"),
        "confirmations_required": confirmations
        if confirmations is not None else sm.get("confirmations_required"),
        "delivery_actor_ids": sm.get("delivery_actor_ids", []),
        "module_addresses": sm.get("module_addresses", {}),
        "effective_block_number": endpoint.get("block_number"),
    }


async def scan_security_policy_snapshots(
    tenant_id: str,
    observations: list[dict[str, Any]],
    service: Optional[SecurityPolicyService] = None,
) -> list[dict[str, Any]]:
    """Snapshot-time caller for ``SecurityPolicyService.snapshot_policy``.

    Re-homed from the branch's security.py (main carries only the service
    class). Wired into the ScanWorker (gated on its own flag). For every
    observation that references a path and a provider whose structural
    security model is available offline, snapshots the derived policy and
    collects the emitted events (snapshot recorded / policy changed). Paths
    whose provider exposes no structural model are skipped — a snapshot is
    never fabricated.
    """
    service = service or SecurityPolicyService()
    emitted: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for observation in observations:
        provider_id = observation.get("provider_id") or observation.get("provider_kind")
        path_id = observation.get("path_id")
        if not provider_id or not path_id:
            continue
        if (provider_id, path_id) in seen:
            continue
        seen.add((provider_id, path_id))
        provider = get_provider(provider_id)
        if provider is None:
            continue
        policy = _policy_from_observation(provider, observation)
        if not policy:
            continue
        result = await service.snapshot_policy(
            tenant_id, provider_id, path_id, policy,
        )
        emitted.extend(result.get("emitted_events", []))
    return emitted


class InteropGraphProjector:
    """Projects one scan cycle into the graph; no-op when disabled.

    Wires main's ``graph_mutations`` builders (provider/gateway/path topology,
    public scope + SENT_VIA_PATH / SECURED_BY_POLICY message edges) into the
    scan pipeline. Mutations persist through ``foundation.persist_mutations`` —
    the canonical graph outbox path. A disabled projector never constructs a
    GraphClient, so the disabled path has zero runtime cost.
    """

    def __init__(self, enabled: bool, message_repo: Optional[InteropMessageRepo] = None) -> None:
        self.enabled = enabled
        self.messages = message_repo or InteropMessageRepo()

    async def project(
        self,
        tenant_id: str,
        observations: list[dict[str, Any]],
        correlation_results: list[dict[str, Any]],
        *,
        provider: dict[str, Any],
        trace_id: str = "",
    ) -> GraphProjectionResult:
        """Persist topology + message mutations for one scan cycle."""
        if not self.enabled:
            return GraphProjectionResult(graph_mutations_built=0)

        gateways, paths = _extract_topology(observations, provider)
        mutations: list[Any] = []
        vertices, edges = build_topology_mutations(provider, gateways, paths)
        mutations.extend(vertices)
        mutations.extend(edges)

        seen: set[str] = set()
        for result in correlation_results:
            message_id = result.get("interop_message_id")
            if not message_id or message_id in seen:
                continue
            seen.add(message_id)
            message = await self.messages.find_one({
                "tenant_id": tenant_id,
                "interop_message_id": message_id,
            })
            if not message:
                continue
            vertices, edges = build_message_mutations(message)
            mutations.extend(vertices)
            mutations.extend(edges)

        return await persist_mutations(mutations, tenant_id=tenant_id, trace_id=trace_id)


class ScanWorker:
    """One durable scan-loop worker over the registered interop adapters."""

    def __init__(
        self,
        tenant_id: str = "public",
        checkpoint_repo: Optional[InteropProviderCheckpointRepo] = None,
        message_repo: Optional[InteropMessageRepo] = None,
        event_repo: Optional[InteropMessageEventRepo] = None,
        publisher: Optional[InteropEventPublisher] = None,
        reconciler: Optional[InteropReconciler] = None,
        graph_projector: Optional[InteropGraphProjector] = None,
        graph_enabled: Optional[bool] = None,
        security_snapshots_enabled: bool = False,
        adapters: Optional[dict[str, Any]] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.checkpoints = checkpoint_repo or InteropProviderCheckpointRepo()
        self.engine = CorrelationEngine(
            message_repo=message_repo or InteropMessageRepo(),
            event_repo=event_repo or InteropMessageEventRepo(),
        )
        self.publisher = publisher or InteropEventPublisher()
        self.reconciler = reconciler or InteropReconciler()
        if graph_enabled is None:
            graph_enabled = bool(settings.interop.graph_enabled)
        self.graph_projector = graph_projector or InteropGraphProjector(enabled=graph_enabled)
        self.security_snapshots_enabled = security_snapshots_enabled
        # Provider override for tests (injected RPC client without mutating the
        # global registry); production uses the canonical registry.
        self._adapters = adapters or {}

    async def run_cycle(self, provider_id: str) -> dict[str, Any]:
        """Run one governed scan cycle for one provider. Returns a summary dict.

        Never raises on a provider's own failure modes: ``NotImplementedError``
        (credential-gated guard) returns ``skipped``, ``RpcRateLimited`` returns
        ``rate_limited``, and other scan exceptions are caught, telemetry is
        recorded by the mixin, and the cycle reports ``error``. The checkpoint
        is only advanced after the cycle fully succeeds, so a failed cycle
        restarts from the same cursor.
        """
        adapter = self._adapters.get(provider_id) or get_provider(provider_id)
        if adapter is None:
            return {"provider_id": provider_id, "status": "unknown_provider"}

        stored = await self.checkpoints.find_one({
            "tenant_id": self.tenant_id,
            "provider_id": provider_id,
            "network_id": SENTINEL_NETWORK,
        })
        checkpoint = (stored or {}).get("evidence") or None

        try:
            observations, new_checkpoint = await adapter.scan(checkpoint)
        except NotImplementedError as exc:
            return {
                "provider_id": provider_id,
                "status": "skipped",
                "reason": str(exc),
            }
        except RpcRateLimited as exc:
            logger.warning(
                "interop scan rate-limited for %s (retry_after=%s)",
                provider_id, exc.retry_after,
            )
            return {
                "provider_id": provider_id,
                "status": "rate_limited",
                "reason": str(exc),
                "retry_after": exc.retry_after,
            }
        except Exception as exc:  # noqa: BLE001 — cycle failure, resume next poll
            logger.warning("interop scan cycle failed for %s: %s", provider_id, exc)
            return {
                "provider_id": provider_id,
                "status": "error",
                "reason": str(exc),
            }
        new_checkpoint = new_checkpoint or {}
        new_checkpoint.setdefault("runtime", {})
        new_checkpoint.setdefault("networks", {})
        runtime = new_checkpoint["runtime"]

        # ── operational telemetry (the base adapter contract is pure on main;
        # the worker owns the checkpoint, so it stamps success telemetry here,
        # surviving restarts inside the durable evidence) ─────────────────────
        runtime["reachable"] = True
        runtime["last_success"] = utc_now_iso()
        reorgs = sum(1 for o in observations if o.get("phase") == "reorged")
        if reorgs:
            runtime["reorg_count"] = runtime.get("reorg_count", 0) + reorgs
        stamped_at = [
            o.get("observed_at") for o in observations if o.get("observed_at")
        ]
        if stamped_at:
            runtime["latest_observation_at"] = max(stamped_at)

        # ── correlate ────────────────────────────────────────────────────────
        results = []
        for observation in observations:
            results.append(await self.engine.ingest_observation(self.tenant_id, observation))

        emitted: list[dict] = []
        for result in results:
            emitted.extend(result.get("emitted_events", []))

        # ── dead-letter quarantine ───────────────────────────────────────────
        dead_lettered = 0
        for observation, result in zip(observations, results):
            if not result.get("accepted") and observation.get("phase") != "reorged":
                dead_lettered += 1
        if dead_lettered:
            runtime["dead_letter_count"] = runtime.get("dead_letter_count", 0) + dead_lettered

        # ── reconciliation evidence ──────────────────────────────────────────
        conflicts, reconcile_events = await self.reconciler.run(self.tenant_id, results)
        if conflicts:
            runtime["reconciliation_conflicts"] = (
                runtime.get("reconciliation_conflicts", 0) + conflicts
            )
        emitted.extend(reconcile_events)

        # ── persist per-adapter reconciliation STATE (durable write path) ────
        # Record the adapter's current reconciliation state (operational fields
        # + source-vs-delivered snapshot) as an idempotent
        # interop_reconciliation_records row. Best-effort: a state-write failure
        # must never fail the cycle — the checkpoint itself is the resume anchor.
        try:
            operational = (
                adapter.operational_state(new_checkpoint)
                if hasattr(adapter, "operational_state")
                else {}
            )
            await self.reconciler.persist_reconciliation_state(
                tenant_id=self.tenant_id,
                provider_id=provider_id,
                operational=operational,
                reconciliation_conflicts=runtime.get("reconciliation_conflicts", 0) if isinstance(runtime, dict) else 0,
            )
        except Exception as exc:  # noqa: BLE001 — telemetry, not a cycle failure
            logger.warning(
                "interop reconciliation-state persist failed for %s: %s",
                provider_id, exc,
            )

        # ── graph projection (gated) ─────────────────────────────────────────
        if self.graph_projector.enabled:
            await self.graph_projector.project(
                self.tenant_id, observations, results,
                provider=adapter.descriptor(), trace_id=provider_id,
            )

        # ── security policy snapshot (gated) ────────────────────────────────
        security_snapshot_count = 0
        if self.security_snapshots_enabled:
            snapshot_events = await scan_security_policy_snapshots(
                self.tenant_id, observations,
            )
            security_snapshot_count = sum(
                1 for event in snapshot_events
                if event.get("event_name") == "interop_security_policy_snapshot_recorded"
            )
            emitted.extend(snapshot_events)

        # ── event publish (broker external; fails loud after retries) ────────
        # Publish BEFORE persisting the checkpoint: a failed publish raises and
        # the advanced checkpoint is NOT persisted, so the next pass resumes
        # from the old cursor and re-publishes the same observations
        # (at-least-once) — events are never skipped past an undelivered batch.
        if emitted:
            await self.publisher.publish_batch(emitted, correlation_id=provider_id)

        # ── persist checkpoint (durable resume; only after publish succeeds) ─
        basis = f"{self.tenant_id}|{provider_id}|{SENTINEL_NETWORK}"
        if stored is None:
            await self.checkpoints.insert({
                "tenant_id": self.tenant_id,
                "checkpoint_id": deterministic_id("iocp_", basis),
                "provider_id": provider_id,
                "network_id": SENTINEL_NETWORK,
                "last_scanned_block": 0,
                "confirmed_block": 0,
                "advanced_at": utc_now_iso(),
                "idempotency_key": deterministic_idempotency_key(basis),
                "evidence": new_checkpoint,
                "execution_by_aether": False,
            })
        else:
            await self.checkpoints.update_by_key(
                {"tenant_id": self.tenant_id, "provider_id": provider_id,
                 "network_id": SENTINEL_NETWORK},
                {"evidence": new_checkpoint, "advanced_at": utc_now_iso()},
            )

        # ── metering (canonical interop meter names only) ────────────────────
        if observations:
            metrics.increment("interop_observation_ingested", value=len(observations))
        correlated = sum(
            1 for result in results
            if any(e.get("event_name") == "interop_message_correlated"
                   for e in result.get("emitted_events", []))
        )
        if correlated:
            metrics.increment("interop_message_correlated", value=correlated)
        metrics.increment("interop_reconciliation_run")

        # ── billable usage metering (dedupe-safe; a restart replay of this same
        # checkpoint reproduces the same dedupe keys and cannot double-bill) ──
        try:
            from services.interop.metering import record_cycle_usage
            await record_cycle_usage(
                self.tenant_id, provider_id,
                checkpoint=new_checkpoint,
                observations=len(observations),
                correlated=correlated,
                reconciliation_runs=1,
                security_snapshots=security_snapshot_count,
            )
        except Exception as exc:  # noqa: BLE001 — metering never breaks the cycle
            logger.warning(
                "interop cycle metering failed for %s: %s", provider_id, exc,
            )

        return {
            "provider_id": provider_id,
            "status": "ok",
            "observations": len(observations),
            "ingested": sum(1 for r in results if r.get("accepted")),
            "dead_lettered": dead_lettered,
            "reconciliation_conflicts": conflicts,
            "events_published": len(emitted),
            "checkpoint_advanced": True,
        }


def build_interop_scan_coro(
    tenant_id: str = "public",
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
) -> Any:
    """Poll-loop coroutine over every registered interop adapter.

    Consumed by the runtime worker registry (``services/runtime/specs.py``),
    gated on ``settings.interop.adapters_enabled``. Runs until cancelled;
    a failed provider cycle is logged and never aborts the loop.
    """

    async def _loop() -> None:
        worker = ScanWorker(tenant_id=tenant_id)
        logger.info("Interop scan loop started (tenant=%s)", tenant_id)
        while True:
            try:
                for provider_id in list(INTEROP_PROVIDERS):
                    summary = await worker.run_cycle(provider_id)
                    if summary.get("status") == "ok":
                        logger.info(
                            "interop scan %s: %s obs, %s dead-lettered",
                            provider_id, summary["observations"], summary["dead_lettered"],
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 — supervisor keeps polling
                logger.error("interop scan loop tick error: %s", exc)
            await asyncio.sleep(poll_interval_seconds)
        logger.info("Interop scan loop stopped")

    return _loop()
