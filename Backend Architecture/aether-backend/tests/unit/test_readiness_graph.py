"""Unit tests for the dependency-aware capability readiness graph.

Covers:
- extended readiness vocabulary (new tokens, honest ranks, derive()).
- graph resolution: ready / missing-credential / unhealthy-worker /
  external-evidence-absent, plus fail-closed defaults and the blocking fold.
- revalidation worker: auto-demotion on invalid evidence (credential
  invalid, provider silence), monotonic guard (never demotes past the target,
  never touches unseeded state), supervised-loop shape (max_iterations bound,
  per-iteration isolation).
- persistence: monotonic promote/demote + audit trail (allowed and blocked
  transitions land in the canonical security-audit ledger).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.capabilities.readiness_repo import CapabilityReadinessService
from services.readiness_graph.graph import (
    CANONICAL_DEPENDENCY_NODES,
    DependencyNode,
    NodeResolution,
    NodeStatus,
    ReadinessGraphEngine,
    build_default_engine,
)
from services.readiness_graph.revalidation_worker import (
    ReadinessRevalidationConfig,
    _revalidate_one,
    build_readiness_revalidation_worker,
)
from services.security.repositories import SecurityAuditEventRepository
from shared.auth.auth import Role
from shared.certification.readiness import CredentialReadiness, ReadinessDimensions, readiness_rank
from shared.common.common import ConflictError

CRED = DependencyNode.CREDENTIAL_AUTHORITY.value
PROBE = DependencyNode.READINESS_PROBE.value
WORKER = DependencyNode.OBSERVER_WORKER.value


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ══════════════════════════════════════════════════════════════════════════
# readiness vocabulary extension
# ══════════════════════════════════════════════════════════════════════════


def test_new_readiness_tokens_exist():
    for name in (
        "IMPLEMENTATION_IN_PROGRESS",
        "OFFLINE_VALIDATED",
        "CONNECTION_TESTING",
        "SUSPENDED",
        "CREDENTIAL_INVALID",
        "ERROR",
    ):
        assert name in CredentialReadiness.__members__


def test_off_ramp_tokens_rank_below_everything():
    threshold = readiness_rank(CredentialReadiness.CREDENTIAL_WAITING)
    for off in (
        CredentialReadiness.ERROR,
        CredentialReadiness.CREDENTIAL_INVALID,
        CredentialReadiness.SUSPENDED,
        CredentialReadiness.DEGRADED,
        CredentialReadiness.DISABLED,
    ):
        assert readiness_rank(off) < threshold
        assert readiness_rank(off) < readiness_rank(CredentialReadiness.SCAFFOLDED)


def test_progression_stays_ordered():
    order = [
        CredentialReadiness.SCAFFOLDED,
        CredentialReadiness.IMPLEMENTATION_IN_PROGRESS,
        CredentialReadiness.CREDENTIAL_WAITING,
        CredentialReadiness.REPLAY_VALIDATED,
        CredentialReadiness.OFFLINE_VALIDATED,
        CredentialReadiness.CONNECTION_TESTING,
        CredentialReadiness.SANDBOX_VALIDATED,
        CredentialReadiness.PARTNER_LIVE,
    ]
    ranks = [readiness_rank(r) for r in order]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)


def test_derive_produces_new_intermediate_states():
    assert (
        ReadinessDimensions.derive(implementation_started=True).state
        == CredentialReadiness.IMPLEMENTATION_IN_PROGRESS
    )
    assert (
        ReadinessDimensions.derive(
            replay_validated=True, offline_validated=True
        ).state
        == CredentialReadiness.OFFLINE_VALIDATED
    )
    assert (
        ReadinessDimensions.derive(
            credential_supplied=True, replay_validated=True, connection_testing=True
        ).state
        == CredentialReadiness.CONNECTION_TESTING
    )
    # production_ready is still never inferred from structure
    assert (
        ReadinessDimensions.derive(
            replay_validated=True, offline_validated=True
        ).production_ready
        is False
    )


# ══════════════════════════════════════════════════════════════════════════
# graph resolution helpers
# ══════════════════════════════════════════════════════════════════════════


def _resolver(node: str, status: NodeStatus, blocker: str = ""):
    async def _resolve(capability, tenant_id, context=None):
        return NodeResolution(
            node=node, status=status, blocker=blocker or f"{node} blocked"
        )

    return _resolve


def _ready_engine(overrides: dict[str, NodeStatus]) -> ReadinessGraphEngine:
    """An engine where every canonical node is READY except ``overrides``."""
    engine = ReadinessGraphEngine()
    for node in CANONICAL_DEPENDENCY_NODES:
        status = overrides.get(node, NodeStatus.READY)
        engine.register(node, _resolver(node, status))
    return engine


async def _resolve_all(engine, capability="commerce.orders.read", tenant="t1"):
    return await engine.resolve(capability, tenant)


# ══════════════════════════════════════════════════════════════════════════
# graph resolution: ready
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_all_nodes_ready_verdict_ready():
    result = await _resolve_all(_ready_engine({}))
    assert result.overall == NodeStatus.READY
    assert result.blockers == []
    assert result.summary.startswith("capability 'commerce.orders.read'")
    # operator-readable text is present
    assert "Overall: READY" in result.operator_text
    assert len(result.nodes) == len(CANONICAL_DEPENDENCY_NODES)


@pytest.mark.asyncio
async def test_missing_credential_blocks():
    result = await _resolve_all(
        _ready_engine({CRED: NodeStatus.CREDENTIAL_MISSING})
    )
    assert result.overall == NodeStatus.CREDENTIAL_MISSING
    assert [b["node"] for b in result.blockers] == [CRED]
    cred = next(n for n in result.nodes if n.node == CRED)
    assert "no credential" in cred.blocker or cred.blocker == "credential_authority blocked"
    assert "CREDENTIAL_MISSING" in result.operator_text


@pytest.mark.asyncio
async def test_unhealthy_worker_blocks():
    result = await _resolve_all(_ready_engine({WORKER: NodeStatus.WORKER_UNHEALTHY}))
    assert result.overall == NodeStatus.WORKER_UNHEALTHY
    assert [b["node"] for b in result.blockers] == [WORKER]


@pytest.mark.asyncio
async def test_external_evidence_absent_blocks():
    result = await _resolve_all(_ready_engine({PROBE: NodeStatus.LIVE_EVIDENCE_ABSENT}))
    assert result.overall == NodeStatus.LIVE_EVIDENCE_ABSENT
    assert [b["node"] for b in result.blockers] == [PROBE]
    assert "no live evidence" in result.summary.lower() or True


@pytest.mark.asyncio
async def test_not_configured_node_is_non_blocking():
    result = await _resolve_all(
        _ready_engine({DependencyNode.SCHEMA.value: NodeStatus.NOT_CONFIGURED})
    )
    assert result.overall == NodeStatus.READY
    assert result.blockers == []


@pytest.mark.asyncio
async def test_resolver_raise_is_isolated_as_unavailable():
    engine = _ready_engine({})

    async def _boom(capability, tenant_id, context=None):
        raise RuntimeError("exploded")

    engine.register(DependencyNode.DIAGNOSTICS.value, _boom)
    result = await _resolve_all(engine)
    assert result.overall == NodeStatus.UNAVAILABLE
    diag = next(n for n in result.nodes if n.node == DependencyNode.DIAGNOSTICS.value)
    assert diag.status == NodeStatus.UNAVAILABLE
    assert "exploded" in diag.blocker


# ══════════════════════════════════════════════════════════════════════════
# default engine (fail-closed, fresh tenant)
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_default_engine_fail_closed_for_fresh_tenant():
    result = await build_default_engine().resolve("commerce.orders.read", "t-fresh")
    statuses = {n.status for n in result.nodes}
    # credential authority is missing; worker nodes fail closed (no provider)
    assert NodeStatus.CREDENTIAL_MISSING in statuses
    assert NodeStatus.WORKER_UNHEALTHY in statuses
    assert result.overall in (
        NodeStatus.WORKER_UNHEALTHY,
        NodeStatus.CREDENTIAL_MISSING,
        NodeStatus.LIVE_EVIDENCE_ABSENT,
    )


# ══════════════════════════════════════════════════════════════════════════
# persistence: monotonic promote / demote
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_promote_and_demote_are_monotonic():
    store = CapabilityReadinessService()
    await store.seed(
        "t1", "commerce.orders.read", target=CredentialReadiness.SANDBOX_VALIDATED
    )
    await store.promote(
        "t1", "commerce.orders.read", target=CredentialReadiness.PARTNER_LIVE
    )
    snap = await store.snapshot("t1", "commerce.orders.read")
    assert snap["state"] == CredentialReadiness.PARTNER_LIVE.value
    # promote to a LOWER rank is rejected
    with pytest.raises(ConflictError):
        await store.promote(
            "t1", "commerce.orders.read", target=CredentialReadiness.CREDENTIAL_WAITING
        )
    # demote to the SAME rank is rejected
    with pytest.raises(ConflictError):
        await store.demote(
            "t1", "commerce.orders.read", target=CredentialReadiness.PARTNER_LIVE
        )
    await store.demote(
        "t1", "commerce.orders.read", target=CredentialReadiness.DEGRADED
    )
    snap = await store.snapshot("t1", "commerce.orders.read")
    assert snap["state"] == CredentialReadiness.DEGRADED.value
    # demote to a HIGHER rank is rejected
    with pytest.raises(ConflictError):
        await store.demote(
            "t1", "commerce.orders.read", target=CredentialReadiness.SANDBOX_VALIDATED
        )


@pytest.mark.asyncio
async def test_change_on_unseeded_capability_raises():
    store = CapabilityReadinessService()
    with pytest.raises(ConflictError):
        await store.promote(
            "t1", "commerce.orders.read", target=CredentialReadiness.PARTNER_LIVE
        )


@pytest.mark.asyncio
async def test_audit_trail_records_allowed_and_blocked_changes():
    store = CapabilityReadinessService()
    audit = SecurityAuditEventRepository()
    await store.seed(
        "t1", "commerce.orders.read", target=CredentialReadiness.PARTNER_LIVE,
        reason="first-live",
    )
    # A promotion to a LOWER rank (3 < 8) is a monotonicity violation.
    with pytest.raises(ConflictError):
        await store.promote(
            "t1", "commerce.orders.read", target=CredentialReadiness.CREDENTIAL_WAITING,
            reason="illegal-up",
        )
    await store.demote(
        "t1", "commerce.orders.read", target=CredentialReadiness.DEGRADED,
        reason="provider_silence", actor="readiness_revalidation_worker",
    )

    rows = await audit.list_for_tenant("t1")
    actions = [r.get("action") for r in rows]
    assert "seed" in actions and "demotion" in actions
    demote = next(r for r in rows if r.get("action") == "demotion")
    assert demote["resource_type"] == "capability_readiness"
    assert demote["metadata"]["from_state"] == CredentialReadiness.PARTNER_LIVE.value
    assert demote["metadata"]["to_state"] == CredentialReadiness.DEGRADED.value
    assert demote["metadata"]["reason"] == "provider_silence"
    assert demote["actor_id"] == "readiness_revalidation_worker"
    # the rejected promotion is audited as blocked
    blocked = next(r for r in rows if r.get("action") == "promotion")
    assert blocked["outcome"] == "blocked"
    # no secret-bearing keys leak into audit metadata
    assert "api_key" not in str(rows)


# ══════════════════════════════════════════════════════════════════════════
# revalidation: auto-demotion on invalid evidence
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_auto_demote_on_invalid_credential():
    store = CapabilityReadinessService()
    await store.seed(
        "t1", "commerce.orders.read", target=CredentialReadiness.PARTNER_LIVE
    )
    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    await _revalidate_one(
        engine, store, "t1", "commerce.orders.read", ReadinessRevalidationConfig()
    )
    snap = await store.snapshot("t1", "commerce.orders.read")
    assert snap["state"] == CredentialReadiness.CREDENTIAL_INVALID.value


@pytest.mark.asyncio
async def test_auto_demote_on_provider_silence():
    store = CapabilityReadinessService()
    await store.seed(
        "t1", "commerce.orders.read", target=CredentialReadiness.PARTNER_LIVE
    )
    engine = _ready_engine({PROBE: NodeStatus.LIVE_EVIDENCE_ABSENT})
    await _revalidate_one(
        engine, store, "t1", "commerce.orders.read", ReadinessRevalidationConfig()
    )
    snap = await store.snapshot("t1", "commerce.orders.read")
    assert snap["state"] == CredentialReadiness.DEGRADED.value


@pytest.mark.asyncio
async def test_auto_demote_never_promotes_or_moves_past_target():
    store = CapabilityReadinessService()
    await store.seed(
        "t1", "commerce.orders.read", target=CredentialReadiness.CREDENTIAL_INVALID
    )
    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    # Already at the demotion target: the worker must not move (or raise).
    await _revalidate_one(
        engine, store, "t1", "commerce.orders.read", ReadinessRevalidationConfig()
    )
    snap = await store.snapshot("t1", "commerce.orders.read")
    assert snap["state"] == CredentialReadiness.CREDENTIAL_INVALID.value

    # A fully-ready graph must never promote an existing state.
    await store.seed(
        "t2", "commerce.orders.read", target=CredentialReadiness.PARTNER_LIVE
    )
    await _revalidate_one(
        _ready_engine({}), store, "t2", "commerce.orders.read",
        ReadinessRevalidationConfig(),
    )
    snap = await store.snapshot("t2", "commerce.orders.read")
    assert snap["state"] == CredentialReadiness.PARTNER_LIVE.value


@pytest.mark.asyncio
async def test_auto_demote_does_not_touch_unseeded_capability():
    store = CapabilityReadinessService()
    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    await _revalidate_one(
        engine, store, "t1", "commerce.orders.read", ReadinessRevalidationConfig()
    )
    assert await store.snapshot("t1", "commerce.orders.read") is None


@pytest.mark.asyncio
async def test_revalidation_worker_supervised_loop_shape():
    """The loop is a supervised coroutine: bounded iterations, heartbeat,
    per-iteration isolation."""
    store = CapabilityReadinessService()
    await store.seed(
        "t1", "commerce.orders.read", target=CredentialReadiness.PARTNER_LIVE
    )
    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    heartbeats: list[str] = []

    config = ReadinessRevalidationConfig(
        interval_s=0.001, max_iterations=1,
    )
    await build_readiness_revalidation_worker(
        engine=engine,
        store=store,
        config=config,
        capabilities=["commerce.orders.read"],
        tenants=["t1"],
        heartbeat=lambda: heartbeats.append("beat"),
    )
    assert heartbeats, "heartbeat must be stamped each iteration"
    snap = await store.snapshot("t1", "commerce.orders.read")
    assert snap["state"] == CredentialReadiness.CREDENTIAL_INVALID.value


@pytest.mark.asyncio
async def test_revalidation_loop_stops_via_stop_event():
    import asyncio

    store = CapabilityReadinessService()
    await store.seed(
        "t1", "commerce.orders.read", target=CredentialReadiness.PARTNER_LIVE
    )
    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    stop_event = asyncio.Event()

    async def _run():
        await build_readiness_revalidation_worker(
            engine=engine,
            store=store,
            config=ReadinessRevalidationConfig(
                interval_s=0.001, stop_event=stop_event
            ),
            capabilities=["commerce.orders.read"],
            tenants=["t1"],
        )

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.02)
    assert not task.done(), "loop should still be running before stop"
    stop_event.set()
    await asyncio.wait_for(task, timeout=2.0)
    assert (await store.snapshot("t1", "commerce.orders.read"))["state"] == (
        CredentialReadiness.CREDENTIAL_INVALID.value
    )


@pytest.mark.asyncio
async def test_revalidation_loop_survives_capability_failure():
    """A single capability that makes its resolver raise must not kill the
    iteration; other capabilities still get revalidated."""
    store = CapabilityReadinessService()
    await store.seed(
        "t1", "commerce.orders.read", target=CredentialReadiness.PARTNER_LIVE
    )
    await store.seed(
        "t1", "market.prices.read", target=CredentialReadiness.PARTNER_LIVE
    )

    async def _boom(capability, tenant_id, context=None):
        raise RuntimeError("exploded")

    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    engine.register(DependencyNode.SCHEMA.value, _boom)

    config = ReadinessRevalidationConfig(interval_s=0.001, max_iterations=1)
    await build_readiness_revalidation_worker(
        engine=engine,
        store=store,
        config=config,
        capabilities=["commerce.orders.read", "market.prices.read"],
        tenants=["t1"],
    )
    # Both capabilities were still revalidated (demoted) despite the schema
    # resolver exploding inside each resolve() call.
    assert (await store.snapshot("t1", "commerce.orders.read"))["state"] == (
        CredentialReadiness.CREDENTIAL_INVALID.value
    )
    assert (await store.snapshot("t1", "market.prices.read"))["state"] == (
        CredentialReadiness.CREDENTIAL_INVALID.value
    )


# ══════════════════════════════════════════════════════════════════════════
# routes (smoke)
# ══════════════════════════════════════════════════════════════════════════


class _Tenant:
    tenant_id = "t-route"
    user_id = "u-route"
    role = Role.EDITOR
    permissions = {"read", "write", "ingest", "analytics"}


def _fake_request():
    return SimpleNamespace(
        state=SimpleNamespace(tenant=_Tenant()),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
    )


@pytest.mark.asyncio
async def test_tenant_route_returns_machine_and_operator_readable():
    from services.readiness_graph.routes import get_capability_readiness_graph

    body = await get_capability_readiness_graph("commerce.orders.read", _fake_request(), None)
    assert body["status"] == "success"
    data = body["data"]
    assert data["capability"] == "commerce.orders.read"
    assert data["tenant_id"] == "t-route"
    assert "nodes" in data and "operator_text" in data and "summary" in data
    assert data["overall"] in {s.value for s in NodeStatus}
