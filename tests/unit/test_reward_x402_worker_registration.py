"""Reward / x402 / credential maintenance workers must be *supervised*.

The mission's single largest runtime defect was that
``build_reward_delivery_outbox_worker`` — the at-least-once reward delivery
loop — was a builder no supervisor ever started, so a reward left the durable
outbox only when an operator manually hit the drain route. The same class of
gap covered stale reward-budget reservation release, DLQ visibility, and
expired-credential-overlap sweeping. (The x402 settlement reconciliation loop
that was once in this set was retired with the commerce control plane,
ADR-012: Aether observes x402 settlement, it does not own settlement state.)

These tests pin the fix as a topology contract, not a one-off wiring:

- **No orphan specs.** Every spec ``build_worker_specs`` constructs is claimed
  by exactly one worker role in ``ROLE_TO_SPEC_NAMES``. A spec that is built but
  unclaimed silently vanishes in every *dedicated* / *consolidated* deployment
  (only the local ``all`` token returns unclaimed specs), which is exactly how
  the reward outbox went unsupervised in production while looking wired locally.
- **The mission workers are registered under the right roles.**
- **The retired commerce control-plane loops stay unregistered.**
- **The shared worker loop isolates a failing tick** without dying.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "services" / "api"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from workers.runtime import roles as roles_mod  # noqa: E402
from workers.runtime import specs as specs_mod  # noqa: E402

# The workers this phase wired into the supervisor, and the role that must own
# each. Kept as data so a regression that drops one is a single-line diff.
MISSION_WORKERS = {
    "reward_delivery_outbox": "outbox-relay",
    "reward_reservation_release": "maintenance",
    "reward_dlq_sweeper": "maintenance",
    "credential_expiry_sweep": "maintenance",
}


def _build_spec_names() -> list[str]:
    settings = SimpleNamespace(intelligence_graph=SimpleNamespace())
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


def test_retired_commerce_control_plane_workers_are_not_built():
    """ADR-012: Aether no longer owns x402 settlement state or commerce
    approvals/entitlements, so none of their supervised loops may come back."""
    built = set(_build_spec_names())
    for name in (
        "x402_settlement_reconciliation",
        "commerce_approval_sweeper",
        "commerce_entitlement_sweeper",
        "commerce_reconciliation",
    ):
        assert name not in built
        assert all(name not in names for names in roles_mod.ROLE_TO_SPEC_NAMES.values())


def test_lean_worker_execution_group_hosts_every_mission_worker():
    """A consolidated ``lean-worker`` process must run every mission worker, or they are lost
    exactly where the reward outbox was lost before."""
    built = _build_spec_names()
    lean = set(roles_mod.specs_for_role("lean-worker", built))
    for name in MISSION_WORKERS:
        assert name in lean, f"{name} is not hosted by the lean-worker group"


# ── kill switch + loop resilience ─────────────────────────────────────────────


async def test_worker_loop_isolates_a_failing_tick_and_stays_cancellable():
    from value.rewards import workers as workers_mod

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
