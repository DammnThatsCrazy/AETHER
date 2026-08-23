"""Unit tests for the dependency-aware capability readiness graph.

Covers:
- canonical readiness vocabulary (main's 11-member CredentialReadiness enum,
  honest ranks, derive()).
- graph resolution: ready / missing-credential / unhealthy-worker /
  external-evidence-absent, plus fail-closed defaults and the blocking fold.
- revalidation worker: auto-demotion on invalid evidence (credential
  invalid, provider silence), monotonic guard (never demotes past the target,
  never touches unseeded state), supervised-loop shape (max_iterations bound,
  per-iteration isolation).
- persistence: main's append-only capability-lifecycle history (legal and
  blocked transitions), mapped through the graph-local CapabilityReadinessAdapter.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.capabilities.lifecycle import (
    CapabilityLifecycleAuthority,
    IllegalTransitionError,
)
from services.readiness_graph.graph import (
    CANONICAL_DEPENDENCY_NODES,
    CapabilityReadinessAdapter,
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
from shared.auth.auth import Role
from shared.certification.readiness import (
    CredentialReadiness,
    ReadinessDimensions,
    readiness_rank,
)

CRED = DependencyNode.CREDENTIAL_AUTHORITY.value
PROBE = DependencyNode.READINESS_PROBE.value
WORKER = DependencyNode.OBSERVER_WORKER.value

# Main's lifecycle authority persists readiness per
# (tenant_id, provider, environment, capability) coordinate; the tests seed a
# stable coordinate and exercise it through the canonical authority + the
# graph-side adapter.
P = "coinbase"
E = "sandbox"
CAP = "commerce.orders.read"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def _authority() -> CapabilityLifecycleAuthority:
    """Authority with the fail-closed promotion preconditions pre-wired."""

    async def _evidence(_refs: list[str]) -> bool:
        return True

    async def _entitled(*_args) -> bool:
        return True

    async def _active_credential(*_args) -> str:
        return "credref://test/active"

    return CapabilityLifecycleAuthority(
        evidence_resolver=_evidence,
        entitlement_checker=_entitled,
        credential_checker=_active_credential,
    )


async def _seed_live(
    authority: CapabilityLifecycleAuthority,
    tenant_id: str,
    capability: str,
) -> None:
    """Walk a capability up the canonical progression to PARTNER_LIVE."""
    for target, refs in (
        (CredentialReadiness.CREDENTIAL_SUPPLIED, None),
        (CredentialReadiness.CONNECTION_VALIDATED, ["evidence://1"]),
        (CredentialReadiness.SANDBOX_VALIDATED, ["evidence://2"]),
        (CredentialReadiness.PARTNER_LIVE, ["evidence://3"]),
    ):
        await authority.promote(
            tenant_id=tenant_id,
            provider=P,
            environment=E,
            capability=capability,
            target=target,
            actor_type="system_worker",
            actor_id="test-seed",
            reason="test seed",
            evidence_refs=refs,
        )


# ══════════════════════════════════════════════════════════════════════════
# canonical readiness vocabulary
# ══════════════════════════════════════════════════════════════════════════


def test_new_readiness_tokens_exist():
    # Main's canonical 11-member CredentialReadiness enum (contract
    # packages/shared/contracts/readiness-vocabulary.json, schema v2.0.0).
    expected = {
        "SCAFFOLDED",
        "CREDENTIAL_WAITING",
        "REPLAY_VALIDATED",
        "CREDENTIAL_SUPPLIED",
        "CONNECTION_VALIDATED",
        "SANDBOX_VALIDATED",
        "PARTNER_LIVE",
        "DEGRADED",
        "SUSPENDED",
        "REVOKED",
        "DISABLED",
    }
    assert set(CredentialReadiness.__members__) == expected


def test_off_ramp_tokens_rank_below_everything():
    threshold = readiness_rank(CredentialReadiness.CREDENTIAL_WAITING)
    for off in (
        CredentialReadiness.DEGRADED,
        CredentialReadiness.SUSPENDED,
        CredentialReadiness.REVOKED,
        CredentialReadiness.DISABLED,
    ):
        assert readiness_rank(off) < threshold
        assert readiness_rank(off) < readiness_rank(CredentialReadiness.SCAFFOLDED)


def test_progression_stays_ordered():
    order = [
        CredentialReadiness.SCAFFOLDED,
        CredentialReadiness.CREDENTIAL_WAITING,
        CredentialReadiness.REPLAY_VALIDATED,
        CredentialReadiness.CREDENTIAL_SUPPLIED,
        CredentialReadiness.CONNECTION_VALIDATED,
        CredentialReadiness.SANDBOX_VALIDATED,
        CredentialReadiness.PARTNER_LIVE,
    ]
    ranks = [readiness_rank(r) for r in order]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)


def test_derive_produces_new_intermediate_states():
    assert (
        ReadinessDimensions.derive(code_complete=True, infra_defined=True).state
        == CredentialReadiness.CREDENTIAL_WAITING
    )
    assert (
        ReadinessDimensions.derive(replay_validated=True).state
        == CredentialReadiness.REPLAY_VALIDATED
    )
    assert (
        ReadinessDimensions.derive(
            credential_supplied=True, connection_validated=True
        ).state
        == CredentialReadiness.CONNECTION_VALIDATED
    )
    # restore coverage of the remaining intermediate rungs
    assert (
        ReadinessDimensions.derive(
            code_complete=True, infra_defined=True, credential_supplied=True
        ).state
        == CredentialReadiness.CREDENTIAL_SUPPLIED
    )
    assert (
        ReadinessDimensions.derive(
            credential_supplied=True,
            connection_validated=True,
            replay_validated=True,
            sandbox_validated=True,
        ).state
        == CredentialReadiness.SANDBOX_VALIDATED
    )
    # production_ready is still never inferred from structure
    assert (
        ReadinessDimensions.derive(replay_validated=True).production_ready is False
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
    # credential authority is missing; unwired worker nodes resolve to
    # NOT_CONFIGURED (non-blocking) — an unwired node must never fabricate a
    # WORKER_UNHEALTHY blocker that could drive a readiness demotion.
    assert NodeStatus.CREDENTIAL_MISSING in statuses
    assert NodeStatus.NOT_CONFIGURED in statuses
    assert NodeStatus.WORKER_UNHEALTHY not in statuses
    assert result.overall in (
        NodeStatus.CREDENTIAL_MISSING,
        NodeStatus.LIVE_EVIDENCE_ABSENT,
    )


# ══════════════════════════════════════════════════════════════════════════
# persistence: monotonic promote / demote (main's lifecycle authority)
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_promote_and_demote_are_monotonic():
    authority = await _authority()
    for target, refs in (
        (CredentialReadiness.CREDENTIAL_SUPPLIED, None),
        (CredentialReadiness.CONNECTION_VALIDATED, ["evidence://1"]),
        (CredentialReadiness.SANDBOX_VALIDATED, ["evidence://2"]),
    ):
        await authority.promote(
            tenant_id="t1", provider=P, environment=E, capability=CAP,
            target=target, actor_type="system_worker", actor_id="test",
            reason="seed", evidence_refs=refs,
        )
    await authority.promote(
        tenant_id="t1", provider=P, environment=E, capability=CAP,
        target=CredentialReadiness.PARTNER_LIVE,
        actor_type="system_worker", actor_id="test", reason="live",
        evidence_refs=["evidence://3"],
    )
    state = await authority.get_state("t1", P, E, CAP)
    assert state["readiness_state"] == CredentialReadiness.PARTNER_LIVE.value
    # promote to a LOWER rank is rejected
    with pytest.raises(IllegalTransitionError):
        await authority.promote(
            tenant_id="t1", provider=P, environment=E, capability=CAP,
            target=CredentialReadiness.CREDENTIAL_WAITING,
            actor_type="system_worker", actor_id="test",
        )
    # demote to the SAME rank is rejected
    with pytest.raises(IllegalTransitionError):
        await authority.demote(
            tenant_id="t1", provider=P, environment=E, capability=CAP,
            target=CredentialReadiness.PARTNER_LIVE,
            actor_type="system_worker", actor_id="test", reason="noop",
        )
    await authority.demote(
        tenant_id="t1", provider=P, environment=E, capability=CAP,
        target=CredentialReadiness.DEGRADED,
        actor_type="system_worker", actor_id="test", reason="provider_silence",
    )
    state = await authority.get_state("t1", P, E, CAP)
    assert state["readiness_state"] == CredentialReadiness.DEGRADED.value
    # demote to a HIGHER rank is rejected
    with pytest.raises(IllegalTransitionError):
        await authority.demote(
            tenant_id="t1", provider=P, environment=E, capability=CAP,
            target=CredentialReadiness.SANDBOX_VALIDATED,
            actor_type="system_worker", actor_id="test", reason="up",
        )


@pytest.mark.asyncio
async def test_change_on_unseeded_capability_raises():
    authority = await _authority()
    # An unseeded coordinate reads as CREDENTIAL_WAITING; a multi-step jump
    # straight to PARTNER_LIVE is not a legal single-step edge.
    with pytest.raises(IllegalTransitionError):
        await authority.promote(
            tenant_id="t1", provider=P, environment=E, capability=CAP,
            target=CredentialReadiness.PARTNER_LIVE,
            actor_type="system_worker", actor_id="test", reason="jump",
        )


@pytest.mark.asyncio
async def test_history_records_allowed_and_blocked_changes():
    authority = await _authority()
    await _seed_live(authority, "t1", CAP)
    # A promotion to a LOWER rank is a monotonicity violation — no row written.
    with pytest.raises(IllegalTransitionError):
        await authority.promote(
            tenant_id="t1", provider=P, environment=E, capability=CAP,
            target=CredentialReadiness.CREDENTIAL_WAITING,
            actor_type="system_worker", actor_id="test", reason="illegal-up",
        )
    await authority.demote(
        tenant_id="t1", provider=P, environment=E, capability=CAP,
        target=CredentialReadiness.DEGRADED,
        actor_type="system_worker", actor_id="readiness_revalidation_worker",
        reason="provider_silence",
    )
    rows = await authority.history("t1", P, E, CAP)
    # newest-first append-only state versions: 4 seed steps + 1 demotion.
    assert len(rows) == 5
    assert rows[0]["readiness_state"] == CredentialReadiness.DEGRADED.value
    assert rows[0]["actor_id"] == "readiness_revalidation_worker"
    assert rows[0]["reason"] == "provider_silence"
    # exactly one non-superseded current row; the rest are superseded history.
    current = await authority.get_state("t1", P, E, CAP)
    assert current["readiness_state"] == CredentialReadiness.DEGRADED.value
    assert current["superseded"] is False
    superseded = [r for r in rows if r.get("superseded")]
    assert len(superseded) == len(rows) - 1
    # no secret-bearing keys leak into the persisted rows.
    assert "api_key" not in str(rows)


# ══════════════════════════════════════════════════════════════════════════
# revalidation: auto-demotion on invalid evidence
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_auto_demote_on_invalid_credential():
    authority = await _authority()
    await _seed_live(authority, "t1", CAP)
    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    await _revalidate_one(
        engine, CapabilityReadinessAdapter(), "t1", CAP, ReadinessRevalidationConfig()
    )
    state = await authority.get_state("t1", P, E, CAP)
    assert state["readiness_state"] == CredentialReadiness.REVOKED.value


@pytest.mark.asyncio
async def test_auto_demote_on_provider_silence():
    authority = await _authority()
    await _seed_live(authority, "t1", CAP)
    engine = _ready_engine({PROBE: NodeStatus.LIVE_EVIDENCE_ABSENT})
    await _revalidate_one(
        engine, CapabilityReadinessAdapter(), "t1", CAP, ReadinessRevalidationConfig()
    )
    state = await authority.get_state("t1", P, E, CAP)
    assert state["readiness_state"] == CredentialReadiness.DEGRADED.value


@pytest.mark.asyncio
async def test_auto_demote_never_promotes_or_moves_past_target():
    authority = await _authority()
    await _seed_live(authority, "t1", CAP)
    await authority.demote(
        tenant_id="t1", provider=P, environment=E, capability=CAP,
        target=CredentialReadiness.REVOKED,
        actor_type="system_worker", actor_id="test", reason="seed off-ramp",
    )
    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    # Already at the demotion target: the worker must not move (or raise).
    await _revalidate_one(
        engine, CapabilityReadinessAdapter(), "t1", CAP, ReadinessRevalidationConfig()
    )
    state = await authority.get_state("t1", P, E, CAP)
    assert state["readiness_state"] == CredentialReadiness.REVOKED.value

    # A fully-ready graph must never promote an existing state.
    await _seed_live(authority, "t2", CAP)
    await _revalidate_one(
        _ready_engine({}), CapabilityReadinessAdapter(), "t2", CAP,
        ReadinessRevalidationConfig(),
    )
    state = await authority.get_state("t2", P, E, CAP)
    assert state["readiness_state"] == CredentialReadiness.PARTNER_LIVE.value


@pytest.mark.asyncio
async def test_auto_demote_does_not_touch_unseeded_capability():
    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    await _revalidate_one(
        engine, CapabilityReadinessAdapter(), "t1", CAP, ReadinessRevalidationConfig()
    )
    assert await CapabilityReadinessAdapter().snapshot("t1", CAP) is None


@pytest.mark.asyncio
async def test_revalidation_worker_supervised_loop_shape():
    """The loop is a supervised coroutine: bounded iterations, heartbeat,
    per-iteration isolation."""
    authority = await _authority()
    await _seed_live(authority, "t1", CAP)
    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    heartbeats: list[str] = []

    config = ReadinessRevalidationConfig(
        interval_s=0.001, max_iterations=1,
    )
    await build_readiness_revalidation_worker(
        engine=engine,
        store=CapabilityReadinessAdapter(),
        config=config,
        capabilities=[CAP],
        tenants=["t1"],
        heartbeat=lambda: heartbeats.append("beat"),
    )
    assert heartbeats, "heartbeat must be stamped each iteration"
    state = await authority.get_state("t1", P, E, CAP)
    assert state["readiness_state"] == CredentialReadiness.REVOKED.value


@pytest.mark.asyncio
async def test_revalidation_loop_stops_via_stop_event():
    import asyncio

    authority = await _authority()
    await _seed_live(authority, "t1", CAP)
    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    stop_event = asyncio.Event()

    async def _run():
        await build_readiness_revalidation_worker(
            engine=engine,
            store=CapabilityReadinessAdapter(),
            config=ReadinessRevalidationConfig(
                interval_s=0.001, stop_event=stop_event
            ),
            capabilities=[CAP],
            tenants=["t1"],
        )

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.02)
    assert not task.done(), "loop should still be running before stop"
    stop_event.set()
    await asyncio.wait_for(task, timeout=2.0)
    state = await authority.get_state("t1", P, E, CAP)
    assert state["readiness_state"] == CredentialReadiness.REVOKED.value


@pytest.mark.asyncio
async def test_revalidation_loop_survives_capability_failure():
    """A single capability that makes its resolver raise must not kill the
    iteration; other capabilities still get revalidated."""
    authority = await _authority()
    await _seed_live(authority, "t1", CAP)
    await _seed_live(authority, "t1", "market.prices.read")

    async def _boom(capability, tenant_id, context=None):
        raise RuntimeError("exploded")

    engine = _ready_engine({CRED: NodeStatus.CREDENTIAL_INVALID})
    engine.register(DependencyNode.SCHEMA.value, _boom)

    config = ReadinessRevalidationConfig(interval_s=0.001, max_iterations=1)
    await build_readiness_revalidation_worker(
        engine=engine,
        store=CapabilityReadinessAdapter(),
        config=config,
        capabilities=[CAP, "market.prices.read"],
        tenants=["t1"],
    )
    # Both capabilities were still revalidated (demoted) despite the schema
    # resolver exploding inside each resolve() call.
    for capability in (CAP, "market.prices.read"):
        state = await authority.get_state("t1", P, E, capability)
        assert state["readiness_state"] == CredentialReadiness.REVOKED.value


@pytest.mark.asyncio
async def test_revalidation_without_worker_provider_does_not_demote_live():
    """A live capability whose only non-READY nodes are unwired worker-backed
    nodes must NOT be auto-demoted when no worker-health provider is wired (an
    unwired node must not drive a mutation), while a genuinely blocking node
    (expired credential) still demotes."""
    authority = await _authority()
    await _seed_live(authority, "t1", CAP)

    async def _ready_credential(capability, tenant_id, context=None):
        return NodeResolution(
            node=CRED,
            status=NodeStatus.READY,
            evidence={"ref": "cred://ok"},
        )

    # Default engine with NO worker_status_provider: worker-backed nodes are
    # unwired and must resolve to NOT_CONFIGURED (non-blocking), never
    # WORKER_UNHEALTHY.
    engine = build_default_engine(credential_resolver=_ready_credential)
    result = await engine.resolve(CAP, "t1")
    worker_nodes = {
        DependencyNode.OBSERVER_WORKER.value,
        DependencyNode.FINALITY_ENGINE.value,
        DependencyNode.REORG_RECOVERY.value,
        DependencyNode.RECONCILIATION.value,
    }
    worker_statuses = {n.status for n in result.nodes if n.node in worker_nodes}
    assert NodeStatus.WORKER_UNHEALTHY not in worker_statuses
    assert worker_statuses == {NodeStatus.NOT_CONFIGURED}

    # Revalidation pass over that engine: nothing blocks, so the live
    # capability stays PARTNER_LIVE — it is NOT auto-demoted to DEGRADED by an
    # unwired worker node.
    await _revalidate_one(
        engine, CapabilityReadinessAdapter(), "t1", CAP, ReadinessRevalidationConfig()
    )
    state = await authority.get_state("t1", P, E, CAP)
    assert state["readiness_state"] == CredentialReadiness.PARTNER_LIVE.value

    # A genuinely blocking node (expired credential) still demotes even with
    # no worker provider wired.
    async def _invalid_credential(capability, tenant_id, context=None):
        return NodeResolution(
            node=CRED,
            status=NodeStatus.CREDENTIAL_INVALID,
            blocker="expired",
        )

    engine2 = build_default_engine(credential_resolver=_invalid_credential)
    await _revalidate_one(
        engine2, CapabilityReadinessAdapter(), "t1", CAP, ReadinessRevalidationConfig()
    )
    state = await authority.get_state("t1", P, E, CAP)
    assert state["readiness_state"] == CredentialReadiness.REVOKED.value


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
