"""Reward / x402 / credential maintenance workers must be *supervised*.

The mission's single largest runtime defect was that
``build_reward_delivery_outbox_worker`` — the at-least-once reward delivery
loop — was a builder no supervisor ever started, so a reward left the durable
outbox only when an operator manually hit the drain route. The same class of
gap covered x402 settlement reconciliation (settlements never advanced past
PENDING on their own), stale reward-budget reservation release, DLQ visibility,
and expired-credential-overlap sweeping.

These tests pin the fix as a topology contract, not a one-off wiring:

- **No orphan specs.** Every spec ``build_worker_specs`` constructs is claimed
  by exactly one worker role in ``ROLE_TO_SPEC_NAMES``. A spec that is built but
  unclaimed silently vanishes in every *dedicated* / *consolidated* deployment
  (only the local ``all`` token returns unclaimed specs), which is exactly how
  the reward outbox went unsupervised in production while looking wired locally.
- **The five mission workers are registered under the right roles.**
- **The x402 reconciliation worker honours its kill switch** (skips a SUSPENDED
  tenant) and its loop **isolates a failing tick** without dying.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.runtime import roles as roles_mod  # noqa: E402
from services.runtime import specs as specs_mod  # noqa: E402

# The five workers this phase wired into the supervisor, and the role that must
# own each. Kept as data so a regression that drops one is a single-line diff.
MISSION_WORKERS = {
    "reward_delivery_outbox": "outbox-relay",
    "x402_settlement_reconciliation": "materializer",
    "reward_reservation_release": "maintenance",
    "reward_dlq_sweeper": "maintenance",
    "credential_expiry_sweep": "maintenance",
}


def _build_spec_names(*, commerce_enabled: bool = True) -> list[str]:
    settings = SimpleNamespace(
        intelligence_graph=SimpleNamespace(
            enable_commerce_control_plane=commerce_enabled
        )
    )
    specs = specs_mod.build_worker_specs(registry=SimpleNamespace(), settings=settings)
    return [s.name for s in specs]


def _owned_spec_names() -> set[str]:
    names: set[str] = set()
    for spec_names in roles_mod.ROLE_TO_SPEC_NAMES.values():
        names |= set(spec_names)
    return names


# ── the topology contract ─────────────────────────────────────────────────────


def test_every_built_spec_is_owned_by_exactly_one_role():
    """A built-but-unclaimed loop spec never runs in a real deployment.

    ``specs_for_role`` only returns unclaimed specs for the local ``all`` token;
    every deployable token (a dedicated worker role or a consolidated execution
    group) resolves through ``ROLE_TO_SPEC_NAMES``. So an orphan spec is not a
    style nit — it is a worker that silently never starts in staging/production.
    """
    built = _build_spec_names()
    owned = _owned_spec_names()

    assert set(built) == owned, (
        "build_worker_specs and ROLE_TO_SPEC_NAMES disagree "
        f"(built-only: {sorted(set(built) - owned)}, "
        f"owned-only: {sorted(owned - set(built))})"
    )
    # No spec is claimed by two roles, and each resolves back to its owner.
    for name in built:
        assert roles_mod.owning_role(name) is not None, f"{name} has no owning role"


def test_mission_workers_are_registered_and_role_attributed():
    built = _build_spec_names()
    for name, expected_role in MISSION_WORKERS.items():
        assert name in built, f"{name} is not registered in build_worker_specs"
        assert roles_mod.owning_role(name) == expected_role, (
            f"{name} should be owned by {expected_role}, "
            f"got {roles_mod.owning_role(name)}"
        )


def test_reward_delivery_outbox_is_supervised_regression():
    """Defect-8 regression: the reward outbox drain must be a supervised spec.

    It rides ``outbox-relay`` alongside the notification/event outbox relays, so
    a dedicated outbox-relay process actually drains reward deliveries.
    """
    assert "reward_delivery_outbox" in _build_spec_names()
    owned = roles_mod.ROLE_TO_SPEC_NAMES["outbox-relay"]
    assert {"notification_outbox", "event_outbox_relay", "reward_delivery_outbox"} <= owned
    picked = roles_mod.specs_for_role(
        "outbox-relay", ["reward_delivery_outbox", "job_worker", "notification_outbox"]
    )
    assert set(picked) == {"reward_delivery_outbox", "notification_outbox"}
    # A pure API process runs none of them.
    assert roles_mod.specs_for_role("api", ["reward_delivery_outbox"]) == []


def test_x402_reconciliation_is_gated_on_the_commerce_control_plane():
    def _spec(commerce_enabled: bool):
        settings = SimpleNamespace(
            intelligence_graph=SimpleNamespace(
                enable_commerce_control_plane=commerce_enabled
            )
        )
        specs = specs_mod.build_worker_specs(
            registry=SimpleNamespace(), settings=settings
        )
        return next(s for s in specs if s.name == "x402_settlement_reconciliation")

    assert _spec(commerce_enabled=True).enabled() is True
    assert _spec(commerce_enabled=False).enabled() is False
    # Reconciliation degrades a capability while its work stays durable — it must
    # not abort startup.
    assert _spec(commerce_enabled=True).required is False


def test_lean_worker_execution_group_hosts_every_mission_worker():
    """A consolidated ``lean-worker`` process must run all five, or they are lost
    exactly where the reward outbox was lost before."""
    built = _build_spec_names()
    lean = set(roles_mod.specs_for_role("lean-worker", built))
    for name in MISSION_WORKERS:
        assert name in lean, f"{name} is not hosted by the lean-worker group"


# ── kill switch + loop resilience ─────────────────────────────────────────────


async def test_reconciliation_worker_skips_a_suspended_tenant(monkeypatch):
    """The kill switch is evaluated per settlement ENVIRONMENT: a PENDING
    settlement whose environment is suspended is skipped (not verified)."""
    from services.x402 import reconciliation as recon_mod

    class _SuspendedAuthority:
        async def get_state(self, tenant_id, provider, environment, capability):
            return {"readiness_state": "suspended"}

    # _capability_suspended imports get_lifecycle_authority lazily from this
    # module, so patching the attribute here is what the worker will resolve.
    import services.capabilities.lifecycle as lifecycle_mod

    monkeypatch.setattr(
        lifecycle_mod, "get_lifecycle_authority", lambda: _SuspendedAuthority()
    )

    class _Settlement:
        settlement_id = "s1"
        environment = "sandbox"
        receipt_id = "rc1"
        tx_hash = "0x1"

    class _Store:
        async def list_settlements(self, tenant_id, state=None):
            return [_Settlement()]

    worker = recon_mod.X402ReconciliationWorker()
    worker._store = _Store()
    monkeypatch.setattr(worker, "_write_cursor", lambda *a, **k: _async_none())

    result = await worker.reconcile_tenant("tenant-suspended")
    assert result["skipped"] == 1
    assert result["settled"] == 0 and result["failed"] == 0


async def _async_none():
    return None


async def test_worker_loop_isolates_a_failing_tick_and_stays_cancellable():
    from services.rewards import workers as workers_mod

    calls = {"n": 0}
    survived = asyncio.Event()

    async def _tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom on first tick")
        if calls["n"] >= 2:
            survived.set()

    task = asyncio.create_task(
        workers_mod._run_loop("test_loop", _tick, interval_seconds=0.001)
    )
    try:
        await asyncio.wait_for(survived.wait(), timeout=2.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # It ran again after the first tick raised — one bad tick never kills the loop.
    assert calls["n"] >= 2
