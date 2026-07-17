"""
Aether Shared — Canonical Graph Mutation Gateway (WP2.5)

Every historically material graph write routes through
:class:`GraphMutationGateway.apply`. The pipeline is:

    1. shape + consent validation   → delegates to GraphWriteValidator
    2. optional CIS risk stage      → shared/cis/mutation_gateway (CIS_ENABLED)
    3. idempotency                  → make_edge_idempotency_key
    4. bitemporal close-and-append  → graph_fact_versions (canonical
                                      BITEMPORAL_EDGE_PROPERTIES names)
    5. append-only ledger write     → graph_mutation_ledger (Postgres)
    6. current projection           → existing GraphClient methods
    7. graph.mutated bus event      → Topic.GRAPH_MUTATED (best-effort)
    8. metrics

Mode ladder (``settings.temporal_observatory.mutation_gateway_mode``):

    off     → delegate straight to GraphClient. Zero behavior change,
              zero added cost — no validation, no ledger, no event.
    shadow  → delegate exactly as today AND append the mutation to the
              ledger. A ledger failure never fails the write (log + meter).
    enforce → the ledger append is transactional with the decision:
              validation failures and ledger failures propagate, and a
              deduplicated mutation short-circuits before projection.

Determinism substrate: :func:`replay_ledger` applies ledger rows to a fresh
``_InMemoryGraphBackend`` and returns a stable sha256 digest;
:func:`current_graph_digest` computes the same digest over a live
GraphClient for ledger-vs-projection parity checks (``graph_checkpoints``).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from shared.common.common import utc_now
from shared.graph.edge_properties import make_edge_idempotency_key
from shared.graph.generated_mutation_taxonomy import GRAPH_MUTATION_TYPES
from shared.graph.graph import Edge, Vertex, _InMemoryGraphBackend, get_graph_client
from shared.graph.mutation_models import MutationRecord
from shared.graph.write_validator import GraphWriteValidationError, GraphWriteValidator
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.graph.mutation_gateway")

GATEWAY_SCHEMA_VERSION = "1"

_MODES = ("off", "shadow", "enforce")

# Operations that soft-revoke an existing edge instead of writing a new one.
_REVOKE_OPERATIONS = frozenset({"edge_expired", "edge_tombstoned", "identity_split"})

# Node-aggregate operations projected via vertex writes.
_NODE_OPERATIONS = frozenset(
    {"node_created", "node_versioned", "node_tombstoned", "node_restored"}
)


def _gateway_mode() -> str:
    """Resolve the mode ladder lazily so tests/env changes take effect per call."""
    try:
        from config.settings import settings

        mode = settings.temporal_observatory.mutation_gateway_mode
    except Exception:  # pragma: no cover — settings unavailable in stubs
        return "off"
    return mode if mode in _MODES else "off"


def _cis_enabled() -> bool:
    import os

    return os.getenv("CIS_ENABLED", "false").lower() in ("true", "1")


# ═══════════════════════════════════════════════════════════════════════════
# INTENT / OUTCOME
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EdgeRevocation:
    """Soft-revoke request for one (from, to, edge_type) edge tuple."""

    from_vertex_id: str
    to_vertex_id: str
    edge_type: str
    reason: str


@dataclass
class MutationIntent:
    """One graph mutation: the target write plus its ledger metadata.

    Exactly one of ``edge`` / ``vertex`` / ``revocation`` must be set.
    ``operation`` must be a value from the generated mutation taxonomy
    (``GRAPH_MUTATION_TYPES``).
    """

    operation: str
    tenant_id: str
    edge: Optional[Edge] = None
    vertex: Optional[Vertex] = None
    revocation: Optional[EdgeRevocation] = None

    actor_kind: Optional[str] = None
    actor_id: Optional[str] = None
    subject_kind: Optional[str] = None
    subject_id: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    source_event_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    reason_code: Optional[str] = None
    causality_class: Optional[str] = None
    confidence: Optional[float] = None
    evidence_refs: Optional[list[str]] = None
    model_refs: Optional[list[str]] = None
    policy_refs: Optional[list[str]] = None
    consent_refs: Optional[list[str]] = None
    change_set_id: Optional[str] = None


@dataclass
class MutationOutcome:
    """What the gateway did for one intent."""

    mode: str
    applied: bool
    mutation_id: str = ""
    deduplicated: bool = False
    ledger_recorded: bool = False
    blocked: bool = False
    violations: list[str] = field(default_factory=list)
    record: Optional[MutationRecord] = None
    before_version_id: Optional[str] = None
    after_version_id: Optional[str] = None
    projection_result: Any = None


# ═══════════════════════════════════════════════════════════════════════════
# GATEWAY
# ═══════════════════════════════════════════════════════════════════════════

class GraphMutationGateway:
    """Single choke point for graph mutations (validation → ledger → projection)."""

    def __init__(
        self,
        graph_client: Optional[Any] = None,
        ledger: Optional[Any] = None,
    ) -> None:
        self._graph = graph_client
        self._ledger = ledger

    # ── Lazy collaborators (zero cost until a mutation is applied) ──────────

    def _client(self) -> Any:
        if self._graph is None:
            self._graph = get_graph_client()
        return self._graph

    def _ledger_repo(self) -> Any:
        if self._ledger is None:
            from repositories.graph_mutation_ledger import GraphMutationLedgerRepository

            self._ledger = GraphMutationLedgerRepository()
        return self._ledger

    # ── Public API ──────────────────────────────────────────────────────────

    async def apply(self, intent: MutationIntent) -> MutationOutcome:
        """Apply one graph mutation through the gateway pipeline."""
        mode = _gateway_mode()
        if mode == "off":
            # Zero behavior change: exactly what a direct writer does today.
            result = await self._project(intent)
            return MutationOutcome(mode="off", applied=True, projection_result=result)

        started = time.monotonic()
        self._check_shape(intent)

        # 1. Shape/consent validation (delegated — never duplicated here).
        violations = self._validate(intent)
        if violations and mode == "enforce":
            self._meter(intent, mode, "rejected_validation", started)
            raise GraphWriteValidationError(violations)

        # 2. Optional CIS risk stage (composed, never modified).
        blocked = await self._cis_stage(intent, mode)
        if blocked and mode == "enforce":
            self._meter(intent, mode, "blocked_cis", started)
            return MutationOutcome(
                mode=mode, applied=False, blocked=True, violations=violations
            )

        # 3-4. Idempotency + record (bitemporal names come from MutationRecord).
        record, fact_payload = self._build_record(intent)

        if mode == "shadow":
            return await self._apply_shadow(
                intent, record, fact_payload, violations, started
            )
        return await self._apply_enforce(
            intent, record, fact_payload, violations, started
        )

    # ── Mode paths ──────────────────────────────────────────────────────────

    async def _apply_shadow(
        self,
        intent: MutationIntent,
        record: MutationRecord,
        fact_payload: Optional[dict],
        violations: list[str],
        started: float,
    ) -> MutationOutcome:
        """Delegate exactly as today; the ledger observes and never interferes."""
        result = await self._project(intent)
        outcome = MutationOutcome(
            mode="shadow",
            applied=True,
            mutation_id=record.mutation_id,
            violations=violations,
            record=record,
            projection_result=result,
        )
        try:
            append = await self._ledger_repo().append(record, fact_payload=fact_payload)
            outcome.ledger_recorded = append.inserted
            outcome.deduplicated = not append.inserted
            outcome.before_version_id = append.before_version_id
            outcome.after_version_id = append.after_version_id
            if append.inserted:
                await self._emit_event(record)
        except Exception as exc:
            # Shadow contract: a ledger failure never fails the write.
            metrics.increment(
                "graph_mutation_ledger_failures_total",
                labels={"mode": "shadow", "operation": intent.operation},
            )
            logger.warning(
                "shadow ledger append failed (write preserved): op=%s tenant=%s: %s",
                intent.operation,
                intent.tenant_id,
                exc,
            )
        self._meter(intent, "shadow", "applied", started)
        return outcome

    async def _apply_enforce(
        self,
        intent: MutationIntent,
        record: MutationRecord,
        fact_payload: Optional[dict],
        violations: list[str],
        started: float,
    ) -> MutationOutcome:
        """Ledger is transactional with the decision; failures propagate."""
        append = await self._ledger_repo().append(record, fact_payload=fact_payload)
        if not append.inserted:
            self._meter(intent, "enforce", "deduplicated", started)
            return MutationOutcome(
                mode="enforce",
                applied=False,
                deduplicated=True,
                mutation_id=append.mutation_id,
                violations=violations,
                record=record,
            )
        result = await self._project(intent)
        await self._emit_event(record)
        self._meter(intent, "enforce", "applied", started)
        return MutationOutcome(
            mode="enforce",
            applied=True,
            mutation_id=record.mutation_id,
            ledger_recorded=True,
            violations=violations,
            record=record,
            before_version_id=append.before_version_id,
            after_version_id=append.after_version_id,
            projection_result=result,
        )

    # ── Pipeline stages ─────────────────────────────────────────────────────

    def _check_shape(self, intent: MutationIntent) -> None:
        if intent.operation not in GRAPH_MUTATION_TYPES:
            raise ValueError(
                f"unknown mutation operation {intent.operation!r} "
                "(must be a GRAPH_MUTATION_TYPES value)"
            )
        targets = [t for t in (intent.edge, intent.vertex, intent.revocation) if t is not None]
        if len(targets) != 1:
            raise ValueError(
                "MutationIntent must set exactly one of edge / vertex / revocation"
            )
        if not intent.tenant_id:
            raise ValueError("MutationIntent.tenant_id is required")

    def _validate(self, intent: MutationIntent) -> list[str]:
        """Delegate edge shape/consent validation to the canonical validator."""
        if intent.edge is None:
            return []
        result = GraphWriteValidator().validate(intent.edge)
        return list(result.violations)

    async def _cis_stage(self, intent: MutationIntent, mode: str) -> bool:
        """Optional CIS risk gateway; returns True when CIS quarantined it."""
        if not _cis_enabled():
            return False
        try:
            from shared.cis.mutation_gateway import check_mutation_gateway

            entity_id, entity_type = self._cis_entity(intent)
            risk = await check_mutation_gateway(
                mutation_class=2,
                entity_id=entity_id,
                entity_type=entity_type,
                proposed_changes={"operation": intent.operation},
                tenant_id=intent.tenant_id,
                originating_agent_id=intent.actor_id
                if intent.actor_kind == "agent"
                else None,
            )
            if risk.quarantined:
                metrics.increment(
                    "graph_mutation_gateway_cis_quarantined_total",
                    labels={"mode": mode, "operation": intent.operation},
                )
                return True
        except Exception as exc:  # pragma: no cover — CIS is best-effort
            logger.debug("CIS mutation stage skipped: %s", exc)
        return False

    @staticmethod
    def _cis_entity(intent: MutationIntent) -> tuple[str, str]:
        if intent.vertex is not None:
            return intent.vertex.vertex_id, intent.vertex.vertex_type
        if intent.edge is not None:
            return intent.edge.from_vertex_id, "ENTITY"
        assert intent.revocation is not None
        return intent.revocation.from_vertex_id, "ENTITY"

    def _build_record(
        self, intent: MutationIntent
    ) -> tuple[MutationRecord, Optional[dict]]:
        """Build the ledger record + bitemporal fact payload for the intent.

        The record's temporal fields use exactly the canonical
        ``BITEMPORAL_EDGE_PROPERTIES`` names (enforced by the MutationRecord
        contract test); ``recorded_at`` is system time at the gateway.
        """
        recorded_at = utc_now()
        aggregate_type, aggregate_id = self._aggregate(intent)
        idempotency_key = self._idempotency_key(intent)

        valid_from = intent.valid_from
        if valid_from is None and intent.edge is not None:
            valid_from = intent.edge.properties.get("valid_from") or None
        valid_to = intent.valid_to
        if valid_to is None and intent.edge is not None:
            valid_to = intent.edge.properties.get("valid_to") or None

        record = MutationRecord(
            mutation_id=str(uuid.uuid4()),
            tenant_id=intent.tenant_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            operation=intent.operation,
            actor_kind=intent.actor_kind,
            actor_id=intent.actor_id,
            subject_kind=intent.subject_kind,
            subject_id=intent.subject_id,
            valid_from=valid_from,
            valid_to=valid_to,
            recorded_at=recorded_at,
            correlation_id=intent.correlation_id,
            causation_id=intent.causation_id,
            source_event_id=intent.source_event_id,
            idempotency_key=idempotency_key,
            reason_code=intent.reason_code,
            causality_class=intent.causality_class,
            confidence=intent.confidence,
            evidence_refs=intent.evidence_refs,
            model_refs=intent.model_refs,
            policy_refs=intent.policy_refs,
            consent_refs=intent.consent_refs,
            change_set_id=intent.change_set_id,
            schema_version=GATEWAY_SCHEMA_VERSION,
        )
        return record, self._fact_payload(intent)

    @staticmethod
    def _aggregate(intent: MutationIntent) -> tuple[str, str]:
        if intent.vertex is not None:
            return "node", intent.vertex.vertex_id
        if intent.edge is not None:
            e = intent.edge
            return "edge", f"{e.edge_type}:{e.from_vertex_id}:{e.to_vertex_id}"
        r = intent.revocation
        assert r is not None
        return "edge", f"{r.edge_type}:{r.from_vertex_id}:{r.to_vertex_id}"

    def _idempotency_key(self, intent: MutationIntent) -> str:
        """Deterministic replay key (stage 3): reuse the canonical helper."""
        if intent.idempotency_key:
            return intent.idempotency_key
        if intent.edge is not None:
            existing = intent.edge.properties.get("idempotency_key")
            if existing:
                return str(existing)
            key = make_edge_idempotency_key(
                intent.tenant_id,
                intent.edge.edge_type,
                intent.edge.from_vertex_id,
                intent.edge.to_vertex_id,
                str(
                    intent.source_event_id
                    or intent.edge.properties.get("source_event_id", "")
                ),
            )
            # Carry the key onto the projected edge so validator/backends see it.
            intent.edge.properties.setdefault("idempotency_key", key)
            return key
        if intent.revocation is not None:
            r = intent.revocation
            raw = (
                f"{intent.tenant_id}:{intent.operation}:{r.edge_type}:"
                f"{r.from_vertex_id}:{r.to_vertex_id}:{intent.source_event_id or ''}"
            )
            return hashlib.sha256(raw.encode()).hexdigest()
        v = intent.vertex
        assert v is not None
        payload_hash = hashlib.sha256(
            json.dumps(v.properties, sort_keys=True, default=str).encode()
        ).hexdigest()
        raw = f"{intent.tenant_id}:{intent.operation}:{v.vertex_id}:{payload_hash}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _fact_payload(intent: MutationIntent) -> Optional[dict]:
        """The replayable payload versioned into ``graph_fact_versions``."""
        if intent.edge is not None:
            e = intent.edge
            return {
                "kind": "edge",
                "edge_type": e.edge_type,
                "from_vertex_id": e.from_vertex_id,
                "to_vertex_id": e.to_vertex_id,
                "properties": dict(e.properties),
            }
        if intent.vertex is not None:
            v = intent.vertex
            return {
                "kind": "node",
                "vertex_type": v.vertex_type,
                "vertex_id": v.vertex_id,
                "properties": dict(v.properties),
            }
        r = intent.revocation
        assert r is not None
        return {
            "kind": "edge_revocation",
            "edge_type": r.edge_type,
            "from_vertex_id": r.from_vertex_id,
            "to_vertex_id": r.to_vertex_id,
            "reason": r.reason,
        }

    async def _project(self, intent: MutationIntent) -> Any:
        """Stage 6: current projection through the existing GraphClient."""
        client = self._client()
        if intent.revocation is not None:
            r = intent.revocation
            return await client.revoke_edge(
                from_vertex_id=r.from_vertex_id,
                to_vertex_id=r.to_vertex_id,
                edge_type=r.edge_type,
                reason=r.reason,
                tenant_id=intent.tenant_id,
            )
        if intent.vertex is not None:
            if intent.operation == "node_created":
                return await client.add_vertex(intent.vertex)
            return await client.upsert_vertex(intent.vertex)
        assert intent.edge is not None
        return await client.add_edge(intent.edge)

    async def _emit_event(self, record: MutationRecord) -> None:
        """Stage 7: graph.mutated bus event (best-effort, never blocks writes)."""
        try:
            from dependencies.providers import get_producer
            from shared.events.events import Event, Topic

            await get_producer().publish(
                Event(
                    topic=Topic.GRAPH_MUTATED,
                    tenant_id=record.tenant_id,
                    source_service="graph.mutation_gateway",
                    correlation_id=record.correlation_id or "",
                    payload={
                        "mutation_id": record.mutation_id,
                        "operation": record.operation,
                        "aggregate_type": record.aggregate_type,
                        "aggregate_id": record.aggregate_id,
                        "idempotency_key": record.idempotency_key,
                        "source_event_id": record.source_event_id,
                        "before_version_id": record.before_version_id,
                        "after_version_id": record.after_version_id,
                    },
                )
            )
        except Exception as exc:
            logger.debug("graph.mutated emit skipped: %s", exc)

    @staticmethod
    def _meter(intent: MutationIntent, mode: str, status: str, started: float) -> None:
        metrics.increment(
            "graph_mutation_gateway_total",
            labels={"mode": mode, "operation": intent.operation, "status": status},
        )
        metrics.timing(
            "graph_mutation_gateway_latency_ms",
            (time.monotonic() - started) * 1000,
            labels={"mode": mode, "operation": intent.operation},
        )


# ── Module-level accessor ────────────────────────────────────────────────────

_shared_gateway: Optional[GraphMutationGateway] = None


def get_mutation_gateway() -> GraphMutationGateway:
    """Process-wide gateway bound to the shared GraphClient."""
    global _shared_gateway
    if _shared_gateway is None:
        _shared_gateway = GraphMutationGateway()
    return _shared_gateway


# ═══════════════════════════════════════════════════════════════════════════
# DETERMINISM SUBSTRATE — replay + digests
# ═══════════════════════════════════════════════════════════════════════════

# Volatile properties written by the backend at revoke time; excluded from
# digests so replay-time and write-time graphs compare equal.
_DIGEST_VOLATILE_PROPS = frozenset({"revoked_at"})


def _drive(coro: Any) -> Any:
    """Synchronously drive an in-memory backend coroutine (it never awaits)."""
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise RuntimeError("in-memory graph operation unexpectedly suspended")


def _canonical_props(properties: dict[str, Any]) -> dict[str, str]:
    return {
        str(k): str(v)
        for k, v in properties.items()
        if k not in _DIGEST_VOLATILE_PROPS
    }


def _digest_state(vertices: Iterable[Vertex], edges: Iterable[Edge]) -> str:
    """Stable sha256 over sorted canonical vertices + edges."""
    vertex_rows = sorted(
        (
            {
                "vertex_id": v.vertex_id,
                "vertex_type": v.vertex_type,
                "properties": _canonical_props(v.properties or {}),
            }
            for v in vertices
        ),
        key=lambda row: row["vertex_id"],
    )
    edge_rows = sorted(
        (
            {
                "edge_type": e.edge_type,
                "from_vertex_id": e.from_vertex_id,
                "to_vertex_id": e.to_vertex_id,
                "properties": _canonical_props(e.properties or {}),
            }
            for e in edges
        ),
        key=lambda row: (
            row["edge_type"],
            row["from_vertex_id"],
            row["to_vertex_id"],
            row["properties"].get("idempotency_key", ""),
        ),
    )
    canonical = json.dumps(
        {"vertices": vertex_rows, "edges": edge_rows},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def replay_ledger(records: Iterable[dict]) -> str:
    """Pure function: apply ledger rows to a fresh in-memory graph → digest.

    ``records`` are ledger rows as returned by
    ``GraphMutationLedgerRepository.list_records`` — each carries
    ``operation`` plus the joined after-version ``payload``. Rows are applied
    in the given (ledger) order; the same records always produce the same
    digest.
    """
    backend = _InMemoryGraphBackend()
    for row in records:
        payload = row.get("payload") or {}
        kind = payload.get("kind")
        operation = row.get("operation", "")
        if kind == "edge_revocation" or operation in _REVOKE_OPERATIONS:
            _drive(
                backend.revoke_edge(
                    from_vertex_id=payload.get("from_vertex_id", ""),
                    to_vertex_id=payload.get("to_vertex_id", ""),
                    edge_type=payload.get("edge_type", ""),
                    reason=payload.get("reason", operation),
                    tenant_id=row.get("tenant_id"),
                )
            )
        elif kind == "edge":
            _drive(
                backend.add_edge(
                    Edge(
                        edge_type=payload["edge_type"],
                        from_vertex_id=payload["from_vertex_id"],
                        to_vertex_id=payload["to_vertex_id"],
                        properties=dict(payload.get("properties") or {}),
                    )
                )
            )
        elif kind == "node":
            _drive(
                backend.upsert_vertex(
                    Vertex(
                        vertex_type=payload["vertex_type"],
                        vertex_id=payload["vertex_id"],
                        properties=dict(payload.get("properties") or {}),
                    )
                )
            )
        # Rows without a payload (pure ledger annotations) do not change state.
    return _digest_state(backend._vertices.values(), backend._edges)


async def current_graph_digest(client: Any, tenant_id: str, scope: str = "") -> str:
    """Digest of the CURRENT projected graph for one tenant.

    Uses the same canonicalization as :func:`replay_ledger` so a shadow-mode
    ledger can be replayed and compared for parity. ``scope`` is a checkpoint
    label only (recorded in ``graph_checkpoints``); the digest always covers
    the tenant's full projected graph. Vertices/edges without a matching
    ``tenant_id`` property are excluded.
    """
    backend = getattr(client, "_backend", None)
    if isinstance(backend, _InMemoryGraphBackend):
        vertices = list(backend._vertices.values())
        edges = list(backend._edges)
    else:  # pragma: no cover — Neptune path exercised in staging
        vertices = await client.get_all_vertices(limit=100_000)
        edges = []
        seen: set[int] = set()
        for vertex in vertices:
            for edge in await client.get_edges(
                vertex.vertex_id, direction="out", include_revoked=True
            ):
                marker = id(edge)
                if marker not in seen:
                    seen.add(marker)
                    edges.append(edge)
    vertices = [
        v for v in vertices if str((v.properties or {}).get("tenant_id", "")) == tenant_id
    ]
    edges = [
        e for e in edges if str((e.properties or {}).get("tenant_id", "")) == tenant_id
    ]
    return _digest_state(vertices, edges)


__all__ = [
    "GATEWAY_SCHEMA_VERSION",
    "EdgeRevocation",
    "GraphMutationGateway",
    "MutationIntent",
    "MutationOutcome",
    "current_graph_digest",
    "get_mutation_gateway",
    "replay_ledger",
]
