"""Dependency-aware capability readiness graph.

Given a capability name + tenant, the engine resolves every *declared*
dependency node (credential authority, RPC config, chain identity, price
provider, durable cursor, observer worker, finality engine, reorg recovery,
reconciliation, schema, entitlement, usage meter, readiness probe,
diagnostics) to a ``(status, blocker)`` pair, then folds the nodes into one
overall readiness verdict.

The engine is resolver-driven: each canonical node has an async resolver
``(capability, tenant_id, context) -> NodeResolution``. Default resolvers
consult the canonical credential facade and the persisted capability-readiness
probe; worker-backed nodes fail closed (absence of health signal is not
health); config-declared nodes read per-capability declarations. Operators may
inject real resolvers (worker-supervisor health, provider reachability, …) via
:meth:`ReadinessGraphEngine.register` or :func:`build_default_engine`.

Node status vocabulary matches program sec7:
``READY | UNAVAILABLE | DISABLED | NOT_CONFIGURED | CREDENTIAL_MISSING |
CREDENTIAL_INVALID | PROVIDER_UNREACHABLE | WORKER_UNHEALTHY |
LIVE_EVIDENCE_ABSENT``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from shared.certification.readiness import CredentialReadiness
from shared.common.common import ConflictError, utc_now
from shared.credentials.service import connector_ref, credential_service
from services.capabilities.activation_repository import (
    ActivationStateRepo,
    ConcurrentTransitionError,
)
from services.capabilities.lifecycle import (
    CapabilityLifecycleAuthority,
    IllegalTransitionError,
)

# ── Node status vocabulary (program sec7) ────────────────────────────────────


class NodeStatus(str, Enum):
    """Per-node readiness status in the dependency graph.

    ``READY`` and ``NOT_CONFIGURED`` are the only non-blocking statuses: a
    declared dependency that is not configured in this deployment does not, by
    itself, block the capability. Every other status is a blocker.
    """

    READY = "ready"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    CREDENTIAL_MISSING = "credential_missing"
    CREDENTIAL_INVALID = "credential_invalid"
    PROVIDER_UNREACHABLE = "provider_unreachable"
    WORKER_UNHEALTHY = "worker_unhealthy"
    LIVE_EVIDENCE_ABSENT = "live_evidence_absent"


#: Statuses that block the overall capability verdict.
BLOCKING_STATUSES: frozenset[NodeStatus] = frozenset(
    {
        NodeStatus.UNAVAILABLE,
        NodeStatus.DISABLED,
        NodeStatus.CREDENTIAL_MISSING,
        NodeStatus.CREDENTIAL_INVALID,
        NodeStatus.PROVIDER_UNREACHABLE,
        NodeStatus.WORKER_UNHEALTHY,
        NodeStatus.LIVE_EVIDENCE_ABSENT,
    }
)

#: Severity order among blocking statuses (lowest = least severe blocker).
_BLOCKING_SEVERITY: dict[NodeStatus, int] = {
    NodeStatus.LIVE_EVIDENCE_ABSENT: 1,
    NodeStatus.UNAVAILABLE: 2,
    NodeStatus.CREDENTIAL_MISSING: 3,
    NodeStatus.CREDENTIAL_INVALID: 4,
    NodeStatus.PROVIDER_UNREACHABLE: 5,
    NodeStatus.WORKER_UNHEALTHY: 6,
    NodeStatus.DISABLED: 7,
}


def is_blocking(status: NodeStatus) -> bool:
    """True iff ``status`` blocks the capability from being ready."""
    return status in BLOCKING_STATUSES


def worst_blocking_status(statuses: list[NodeStatus]) -> Optional[NodeStatus]:
    """Return the most severe blocking status, or ``None`` if none block."""
    blocking = [s for s in statuses if is_blocking(s)]
    if not blocking:
        return None
    return max(blocking, key=lambda s: _BLOCKING_SEVERITY[s])


# ── Canonical dependency nodes ───────────────────────────────────────────────


class DependencyNode(str, Enum):
    """Canonical dependency nodes a capability's readiness can hinge on."""

    CREDENTIAL_AUTHORITY = "credential_authority"
    RPC_CONFIG = "rpc_config"
    CHAIN_IDENTITY = "chain_identity"
    PRICE_PROVIDER = "price_provider"
    DURABLE_CURSOR = "durable_cursor"
    OBSERVER_WORKER = "observer_worker"
    FINALITY_ENGINE = "finality_engine"
    REORG_RECOVERY = "reorg_recovery"
    RECONCILIATION = "reconciliation"
    SCHEMA = "schema"
    ENTITLEMENT = "entitlement"
    USAGE_METER = "usage_meter"
    READINESS_PROBE = "readiness_probe"
    DIAGNOSTICS = "diagnostics"


#: Default declared dependency set, in display order.
CANONICAL_DEPENDENCY_NODES: tuple[str, ...] = tuple(
    node.value for node in DependencyNode
)

#: Nodes backed by a supervised worker (fail closed when no health evidence).
WORKER_NODES: frozenset[str] = frozenset(
    {
        DependencyNode.OBSERVER_WORKER.value,
        DependencyNode.FINALITY_ENGINE.value,
        DependencyNode.REORG_RECOVERY.value,
        DependencyNode.RECONCILIATION.value,
    }
)

#: Nodes resolved from per-capability config/declaration evidence.
CONFIG_NODES: frozenset[str] = frozenset(
    {
        DependencyNode.RPC_CONFIG.value,
        DependencyNode.CHAIN_IDENTITY.value,
        DependencyNode.PRICE_PROVIDER.value,
        DependencyNode.DURABLE_CURSOR.value,
        DependencyNode.SCHEMA.value,
        DependencyNode.ENTITLEMENT.value,
        DependencyNode.USAGE_METER.value,
        DependencyNode.DIAGNOSTICS.value,
    }
)


# ── Result models ────────────────────────────────────────────────────────────


class NodeResolution(BaseModel):
    """One dependency node's readiness verdict (machine-readable)."""

    node: str
    status: NodeStatus
    blocker: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    resolved_at: str = Field(default_factory=lambda: utc_now().isoformat())


class ReadinessGraphResult(BaseModel):
    """Full readiness-graph verdict for one capability + tenant.

    Carries BOTH machine-readable fields (``overall``, ``nodes``, ``blockers``)
    and operator-readable ones (``summary`` one-liner + ``operator_text`` full
    report).
    """

    capability: str
    tenant_id: str
    evaluated_at: str = Field(default_factory=lambda: utc_now().isoformat())
    overall: NodeStatus
    nodes: list[NodeResolution]
    blockers: list[dict[str, str]] = Field(default_factory=list)
    summary: str = ""
    operator_text: str = ""

    def to_view(self) -> dict[str, Any]:
        """Route-facing view: machine fields + operator-readable text."""
        return self.model_dump()

    @classmethod
    def _build(
        cls,
        capability: str,
        tenant_id: str,
        nodes: list[NodeResolution],
    ) -> "ReadinessGraphResult":
        blockers = [
            {"node": n.node, "status": n.status.value, "blocker": n.blocker}
            for n in nodes
            if is_blocking(n.status)
        ]
        overall = worst_blocking_status([n.status for n in nodes]) or NodeStatus.READY
        summary = _summarize(capability, tenant_id, overall, blockers)
        return cls(
            capability=capability,
            tenant_id=tenant_id,
            overall=overall,
            nodes=nodes,
            blockers=blockers,
            summary=summary,
            operator_text=_operator_report(capability, tenant_id, overall, nodes),
        )


def _summarize(
    capability: str,
    tenant_id: str,
    overall: NodeStatus,
    blockers: list[dict[str, str]],
) -> str:
    if not blockers:
        return (
            f"capability {capability!r} for tenant {tenant_id or '<none>'} is "
            f"READY — every declared dependency is resolved."
        )
    # Anchor the summary on the blocker that determines the overall verdict.
    top = next(
        (b for b in blockers if b["status"] == overall.value), blockers[0]
    )
    return (
        f"capability {capability!r} for tenant {tenant_id or '<none>'} is "
        f"{overall.value.upper()} — {len(blockers)} blocker(s); most severe: "
        f"{top['node']} ({top['status']}): {top['blocker'] or 'no detail'}"
    )


def _operator_report(
    capability: str,
    tenant_id: str,
    overall: NodeStatus,
    nodes: list[NodeResolution],
) -> str:
    lines = [
        f"Readiness graph — capability={capability!r} tenant={tenant_id or '<none>'}",
        f"Overall: {overall.value.upper()}",
        "",
        "Declared dependency nodes:",
    ]
    for n in nodes:
        status = n.status.value.upper()
        blocker = f"  blocker: {n.blocker}" if n.blocker else ""
        lines.append(f"  - {n.node}: {status}{blocker}")
    return "\n".join(lines)


# ── Resolver types ───────────────────────────────────────────────────────────

#: ResolveContext is an opaque bag the route/worker passes to resolvers (e.g.
#: a live worker-health map, provider status map, tenant headers).
ResolveContext = dict[str, Any]

#: An async resolver: (capability, tenant_id, context) -> NodeResolution.
ResolveFn = Callable[[str, str, ResolveContext], Awaitable[NodeResolution]]


# ── Built-in resolvers ───────────────────────────────────────────────────────


class CredentialAuthorityResolver:
    """Resolves the credential-authority node against the canonical facade.

    ``ref_for`` defaults to the canonical ``connector_ref`` (per-tenant, no
    secret material in the ref). ``credential_required`` lets a capability
    declare it needs no credential (node then reads READY).
    """

    def __init__(
        self,
        *,
        service: Any = None,
        ref_for: Optional[Callable[[str, str], str]] = None,
        credential_required: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._service = service or credential_service
        self._ref_for = ref_for or connector_ref
        self._required = credential_required or (lambda _capability: True)

    async def resolve(
        self, capability: str, tenant_id: str, context: ResolveContext = None
    ) -> NodeResolution:
        if not self._required(capability):
            return NodeResolution(
                node=DependencyNode.CREDENTIAL_AUTHORITY.value,
                status=NodeStatus.READY,
                evidence={"credential_required": False},
            )
        ref = self._ref_for(tenant_id, capability)
        try:
            md = await self._service.metadata(tenant_id, ref)
        except Exception as exc:  # pragma: no cover - defensive
            return NodeResolution(
                node=DependencyNode.CREDENTIAL_AUTHORITY.value,
                status=NodeStatus.UNAVAILABLE,
                blocker=(
                    f"credential authority unreachable for ref {ref!r}: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        if md is None:
            return NodeResolution(
                node=DependencyNode.CREDENTIAL_AUTHORITY.value,
                status=NodeStatus.CREDENTIAL_MISSING,
                blocker=f"no credential stored at ref {ref!r} for tenant {tenant_id or '<none>'}; "
                f"credential authority cannot authorize this capability",
                evidence={"ref": ref},
            )
        invalid = md.status in (
            CredentialReadiness.DISABLED,
            CredentialReadiness.DEGRADED,
            CredentialReadiness.SUSPENDED,
            CredentialReadiness.REVOKED,
        )
        if invalid:
            return NodeResolution(
                node=DependencyNode.CREDENTIAL_AUTHORITY.value,
                status=NodeStatus.CREDENTIAL_INVALID,
                blocker=(
                    f"credential at ref {ref!r} is {md.status.value} "
                    f"(lifecycle evidence) — it cannot authorize live calls"
                ),
                evidence={"ref": ref, "status": md.status.value},
            )
        return NodeResolution(
            node=DependencyNode.CREDENTIAL_AUTHORITY.value,
            status=NodeStatus.READY,
            evidence={"ref": ref, "status": md.status.value},
        )


class CapabilityReadinessAdapter:
    """Minimal graph-side adapter over main's activation-state lifecycle.

    The graph engine probes persisted readiness per ``(tenant_id, capability)``,
    while main's lifecycle authority persists readiness per
    ``(tenant_id, provider, environment, capability)`` coordinate. This adapter
    folds the canonical
    :class:`~services.capabilities.activation_repository.ActivationStateRepo`
    rows into snapshot-shaped records for the read path and routes the only
    write the graph path performs (auto-demotion) through the canonical
    :class:`~services.capabilities.lifecycle.CapabilityLifecycleAuthority`.

    It deliberately does NOT re-implement the superseded branch-side
    ``readiness_repo``: monotonicity, legal edges and the append-only audit
    history are main's lifecycle contract, enforced by the authority.
    """

    def __init__(
        self,
        repo: Optional[ActivationStateRepo] = None,
        authority: Optional[CapabilityLifecycleAuthority] = None,
    ) -> None:
        self._repo = repo or ActivationStateRepo()
        self._authority = authority or CapabilityLifecycleAuthority()

    async def snapshot(
        self, tenant_id: str, capability: str
    ) -> Optional[dict[str, Any]]:
        """Snapshot-shaped readiness record for ``(tenant_id, capability)``.

        Main keys readiness by ``(tenant_id, provider, environment, capability)``;
        the graph has no provider/environment coordinate, so when a capability
        is certified under more than one coordinate the newest state version
        wins. ``None`` when the capability has no persisted state.
        """
        rows = await self._repo.current_for_tenant(tenant_id)
        matches = [r for r in rows if r.get("capability") == capability]
        if not matches:
            return None
        row = max(matches, key=lambda r: int(r.get("state_version", 0)))
        return {
            "state": row.get("readiness_state"),
            "readiness_state": row.get("readiness_state"),
            "evidence_timestamp": row.get("occurred_at"),
            "provider": row.get("provider"),
            "environment": row.get("environment"),
            "capability": row.get("capability"),
            "tenant_id": row.get("tenant_id"),
        }

    async def demote(
        self,
        tenant_id: str,
        capability: str,
        *,
        target: CredentialReadiness,
        evidence: Optional[dict[str, Any]] = None,
        reason: str = "",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Route an auto-demotion through the lifecycle authority.

        The coordinate's provider/environment are taken from the persisted row;
        an unseeded capability raises :class:`ConflictError` (the branch-side
        contract the revalidation worker was written against). Main's
        ``IllegalTransitionError`` / ``ConcurrentTransitionError`` surface as
        ``ConflictError`` so callers that treat a rejected demotion as a
        race/no-op keep working.
        """
        snap = await self.snapshot(tenant_id, capability)
        if snap is None:
            raise ConflictError(
                f"cannot demote unseeded capability readiness for {capability!r} "
                f"tenant={tenant_id}"
            )
        try:
            return await self._authority.demote(
                tenant_id=tenant_id,
                provider=snap["provider"],
                environment=snap["environment"],
                capability=capability,
                target=target,
                actor_type="system_worker",
                actor_id=actor,
                reason=reason,
            )
        except (IllegalTransitionError, ConcurrentTransitionError) as exc:
            raise ConflictError(f"demotion rejected: {exc}") from exc


class ReadinessProbeResolver:
    """Resolves the readiness-probe node against persisted capability state.

    A recorded probe that is fresh AND at a live-validated state reads READY.
    A missing, stale, or not-yet-live probe reads LIVE_EVIDENCE_ABSENT — a
    probe is evidence, and evidence that is absent is not a pass.
    """

    #: Readiness states that count as live evidence.
    _LIVE_STATES = frozenset(
        {CredentialReadiness.PARTNER_LIVE, CredentialReadiness.SANDBOX_VALIDATED}
    )

    def __init__(
        self,
        *,
        store: Optional[CapabilityReadinessAdapter] = None,
        staleness_s: float = 300.0,
        now: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._store = store or CapabilityReadinessAdapter()
        self._staleness_s = staleness_s
        self._now = now or utc_now

    async def resolve(
        self, capability: str, tenant_id: str, context: ResolveContext = None
    ) -> NodeResolution:
        try:
            record = await self._store.snapshot(tenant_id, capability)
        except Exception as exc:  # pragma: no cover - defensive
            return NodeResolution(
                node=DependencyNode.READINESS_PROBE.value,
                status=NodeStatus.UNAVAILABLE,
                blocker=f"readiness probe store unavailable: {type(exc).__name__}: {exc}",
            )
        if record is None:
            return NodeResolution(
                node=DependencyNode.READINESS_PROBE.value,
                status=NodeStatus.LIVE_EVIDENCE_ABSENT,
                blocker=(
                    f"no capability readiness probe recorded for tenant "
                    f"{tenant_id or '<none>'} capability {capability!r}"
                ),
            )
        state = record.get("state")
        ts = record.get("evidence_timestamp")
        stale = self._is_stale(ts)
        if state in _OFF_RAMP_READINESS:
            return NodeResolution(
                node=DependencyNode.READINESS_PROBE.value,
                status=NodeStatus.DISABLED
                if state == CredentialReadiness.DISABLED.value
                else NodeStatus.CREDENTIAL_INVALID,
                blocker=(
                    f"readiness probe is at off-ramp state {state!r} "
                    f"(evidence at {ts})"
                ),
                evidence={"state": state, "evidence_timestamp": ts},
            )
        if state in {s.value for s in self._LIVE_STATES} and not stale:
            return NodeResolution(
                node=DependencyNode.READINESS_PROBE.value,
                status=NodeStatus.READY,
                evidence={
                    "state": state,
                    "evidence_timestamp": ts,
                    "probe_staleness_s": self._staleness_s,
                },
            )
        if stale:
            return NodeResolution(
                node=DependencyNode.READINESS_PROBE.value,
                status=NodeStatus.LIVE_EVIDENCE_ABSENT,
                blocker=(
                    f"readiness probe evidence is stale (evidence at {ts}); "
                    f"no fresh live evidence for this capability"
                ),
                evidence={"state": state, "evidence_timestamp": ts},
            )
        return NodeResolution(
            node=DependencyNode.READINESS_PROBE.value,
            status=NodeStatus.LIVE_EVIDENCE_ABSENT,
            blocker=(
                f"readiness probe at {state!r} — live validation has not been "
                f"proven for this capability"
            ),
            evidence={"state": state, "evidence_timestamp": ts},
        )

    def _is_stale(self, evidence_timestamp: Any) -> bool:
        if not evidence_timestamp:
            return True
        try:
            from shared.common.common import parse_iso

            age = (self._now() - parse_iso(str(evidence_timestamp))).total_seconds()
            return age > self._staleness_s
        except (ValueError, TypeError):  # pragma: no cover - defensive
            return True


#: Readiness tokens that are off-ramp — degraded/disabled/suspended/revoked,
#: ranked below the forward progression.
_OFF_RAMP_READINESS: frozenset[str] = frozenset(
    {
        CredentialReadiness.DEGRADED.value,
        CredentialReadiness.DISABLED.value,
        CredentialReadiness.SUSPENDED.value,
        CredentialReadiness.REVOKED.value,
    }
)


async def _worker_node_resolver(
    node: str,
    capability: str,
    tenant_id: str,
    context: ResolveContext,
    provider: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
) -> NodeResolution:
    """Fail-closed worker node: no health signal is not health."""
    if provider is None:
        return NodeResolution(
            node=node,
            status=NodeStatus.WORKER_UNHEALTHY,
            blocker=(
                f"no worker-health evidence wired for {node}; absence of a "
                f"health signal is not health"
            ),
        )
    try:
        status = provider(node) or {}
    except Exception as exc:  # pragma: no cover - defensive
        return NodeResolution(
            node=node,
            status=NodeStatus.WORKER_UNHEALTHY,
            blocker=f"worker-health provider failed for {node}: {type(exc).__name__}: {exc}",
        )
    healthy = bool(status.get("healthy", status.get("state") == "running"))
    if not healthy:
        return NodeResolution(
            node=node,
            status=NodeStatus.WORKER_UNHEALTHY,
            blocker=status.get("detail") or f"worker {node} is not healthy",
            evidence=status,
        )
    return NodeResolution(node=node, status=NodeStatus.READY, evidence=status)


async def _config_node_resolver(
    node: str,
    capability: str,
    tenant_id: str,
    context: ResolveContext,
    declarations: Optional[dict[str, Any]] = None,
) -> NodeResolution:
    """Resolve a config-declared node against per-capability declarations."""
    declared = (declarations or {}).get(node)
    if declared is None:
        return NodeResolution(
            node=node,
            status=NodeStatus.NOT_CONFIGURED,
            blocker=f"{node} is not declared/configured for capability {capability!r}",
        )
    if isinstance(declared, dict) and declared.get("enabled") is False:
        return NodeResolution(
            node=node,
            status=NodeStatus.NOT_CONFIGURED,
            blocker=f"{node} is declared but disabled for capability {capability!r}",
            evidence=declared,
        )
    if isinstance(declared, dict):
        return NodeResolution(
            node=node,
            status=NodeStatus.READY,
            evidence={k: v for k, v in declared.items() if k != "secret"},
        )
    return NodeResolution(
        node=node,
        status=NodeStatus.READY,
        evidence={"declared": True},
    )


# ── Engine ───────────────────────────────────────────────────────────────────


class ReadinessGraphEngine:
    """Resolves a capability+tenant's declared dependency graph to a verdict.

    Resolvers are registered per node name; a node with no registered resolver
    resolves to NOT_CONFIGURED (it is not part of this deployment's runtime
    contract). Declared dependencies default to :data:`CANONICAL_DEPENDENCY_NODES`
    and may be overridden per capability via ``dependencies``.
    """

    def __init__(
        self,
        *,
        resolvers: Optional[dict[str, ResolveFn]] = None,
        dependencies: Optional[dict[str, list[str]]] = None,
    ) -> None:
        self._resolvers: dict[str, ResolveFn] = dict(resolvers or {})
        self._dependencies: dict[str, list[str]] = dict(dependencies or {})

    def register(self, node: str, resolver: ResolveFn) -> None:
        """Register (or replace) the async resolver for ``node``."""
        self._resolvers[node] = resolver

    def declared_dependencies(self, capability: str) -> list[str]:
        """Dependency nodes declared for ``capability`` (canonical by default)."""
        return list(
            self._dependencies.get(capability) or CANONICAL_DEPENDENCY_NODES
        )

    async def resolve(
        self,
        capability: str,
        tenant_id: str,
        context: ResolveContext = None,
    ) -> ReadinessGraphResult:
        """Resolve every declared dependency node and fold to one verdict.

        Per-node exception isolation: a resolver that raises is reported as
        UNAVAILABLE with the exception detail, never propagated.
        """
        context = context or {}
        nodes: list[NodeResolution] = []
        for node in self.declared_dependencies(capability):
            resolver = self._resolvers.get(node)
            if resolver is None:
                nodes.append(
                    NodeResolution(
                        node=node,
                        status=NodeStatus.NOT_CONFIGURED,
                        blocker=(
                            f"no resolver registered for dependency node "
                            f"{node!r}; cannot evaluate"
                        ),
                    )
                )
                continue
            try:
                nodes.append(await resolver(capability, tenant_id, context))
            except Exception as exc:
                nodes.append(
                    NodeResolution(
                        node=node,
                        status=NodeStatus.UNAVAILABLE,
                        blocker=(
                            f"resolver for {node!r} failed: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                    )
                )
        return ReadinessGraphResult._build(capability, tenant_id, nodes)


# ── Default engine ───────────────────────────────────────────────────────────


def build_default_engine(
    *,
    credential_resolver: Optional[ResolveFn] = None,
    readiness_probe_resolver: Optional[ResolveFn] = None,
    worker_status_provider: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    config_declarations: Optional[dict[str, Any]] = None,
    dependencies: Optional[dict[str, list[str]]] = None,
) -> ReadinessGraphEngine:
    """Build an engine with the canonical default resolvers.

    * credential authority — canonical credential facade;
    * readiness probe — persisted capability readiness (via
      :class:`CapabilityReadinessAdapter`);
    * worker-backed nodes — fail closed unless ``worker_status_provider`` is
      wired (the integration pass should supply a live worker-health map);
    * config-declared nodes — resolved from ``config_declarations``
      (``{node: {...evidence}}``), else NOT_CONFIGURED.
    """
    engine = ReadinessGraphEngine(dependencies=dependencies)
    engine.register(
        DependencyNode.CREDENTIAL_AUTHORITY.value,
        credential_resolver or CredentialAuthorityResolver().resolve,
    )
    engine.register(
        DependencyNode.READINESS_PROBE.value,
        readiness_probe_resolver or ReadinessProbeResolver().resolve,
    )
    for node in sorted(WORKER_NODES):

        async def _worker(
            capability: str,
            tenant_id: str,
            context: ResolveContext,
            _node: str = node,
        ) -> NodeResolution:
            return await _worker_node_resolver(
                _node, capability, tenant_id, context,
                provider=worker_status_provider,
            )

        engine.register(node, _worker)
    for node in sorted(CONFIG_NODES):

        async def _config(
            capability: str,
            tenant_id: str,
            context: ResolveContext,
            _node: str = node,
        ) -> NodeResolution:
            return await _config_node_resolver(
                _node, capability, tenant_id, context,
                declarations=config_declarations,
            )

        engine.register(node, _config)
    return engine


__all__ = [
    "BLOCKING_STATUSES",
    "CANONICAL_DEPENDENCY_NODES",
    "CONFIG_NODES",
    "CapabilityReadinessAdapter",
    "DependencyNode",
    "NodeResolution",
    "NodeStatus",
    "ReadinessGraphEngine",
    "ReadinessGraphResult",
    "ReadinessProbeResolver",
    "CredentialAuthorityResolver",
    "ResolveContext",
    "WORKER_NODES",
    "build_default_engine",
    "is_blocking",
    "worst_blocking_status",
]
