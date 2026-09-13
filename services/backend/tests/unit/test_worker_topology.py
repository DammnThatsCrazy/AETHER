"""No-orphan topology proof for supervised loop workers (program sec10/sec11).

Every :class:`~services.runtime.supervisor.WorkerSpec` built by
``build_worker_specs()`` must be claimed by at least one worker role in
``ROLE_TO_SPEC_NAMES``. A spec no role claims is silently filtered out of every
deployable role token (only local ``all`` mode runs it), which makes the
supervised loop a deployment blind spot: it looks supervised and never runs in
any real environment.

This suite pins the invariant in both directions:

- (a) every spec the builder returns is claimed by >= 1 role (no
      defined-but-unclaimed worker), and
- (b) every documented worker-builder module that *exists* in the tree is
      registered (import the module, assert its spec exists and its factory
      references the module).

Most orphan workers' builders were authored during the closure wave
(stablecoin/interop/derivatives loops, credential expiry sweep, dead-letter
sweeper, settlement reconciliation, reward reservation release, reward claim
reconciliation, reward receipt evidence). They are registered by name + claimed
by a role and asserted against their real builder module. The one remaining
pending builder (interop scan) stays registered by name + claimed by a role and
is asserted flag-gated OFF by default so it stays inert until its builder and
flag are both live.
"""

from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace

from services.runtime.roles import ROLE_TO_SPEC_NAMES, specs_for_role
from services.runtime.specs import build_worker_specs
from services.runtime.supervisor import WorkerSpec


# Settings stub covering only the attributes the spec ``enabled`` predicates
# reference. The predicates are only *invoked* inside the supervisor at start,
# never at spec-build time, but the inert-by-default test below evaluates them
# directly, so every attribute they touch must exist here.
SETTINGS = SimpleNamespace(
    delivery=SimpleNamespace(enabled=True),
    card_linked_payment_rails=SimpleNamespace(enabled=False),
    stablecoin_intelligence=SimpleNamespace(enabled=False),
    interop=SimpleNamespace(adapters_enabled=False),
    derivatives=SimpleNamespace(reconciliation_enabled=False),
    intelligence_graph=SimpleNamespace(enable_x402_layer=False),
    provider_gateway=SimpleNamespace(enabled=False),
    runtime=SimpleNamespace(),
    payment_rails=SimpleNamespace(),
)


def _built_specs() -> list[WorkerSpec]:
    return build_worker_specs(registry=object(), settings=SETTINGS)


def _claimed_spec_names() -> set[str]:
    claimed: set[str] = set()
    for spec_names in ROLE_TO_SPEC_NAMES.values():
        claimed |= set(spec_names)
    return claimed


# Every documented orphan (program sec10/sec11) that must be registered. All of
# these now have real builders (import-asserted via EXISTING_BUILDER_MODULES).
DOCUMENTED_ORPHANS: frozenset[str] = frozenset(
    {
        "reward_delivery_outbox",
        "card_linked_graph_outbox",
        "readiness_revalidation",
        "stablecoin_provider_polling",
        "interop_scan",
        "derivatives_venue_sweep",
        "x402_settlement_reconciliation",
        "credential_expiry_sweep",
        "dead_letter_sweeper",
        "reward_reservation_release",
        "reward_claim_reconciliation",
        "reward_receipt_evidence",
    }
)

# Worker-builder modules that exist today, mapped to the spec that must
# reference them. ``test_documented_builder_modules_are_registered`` imports
# each module and asserts its spec exists and its factory source mentions the
# module — a real regression signal, not a pending-build placeholder.
EXISTING_BUILDER_MODULES: dict[str, str] = {
    "reward_delivery_outbox": "services.rewards.delivery_outbox",
    "card_linked_graph_outbox": "services.card_linked_payments.graph_outbox",
    # Authored by the capability-readiness agent (1A) in this wave.
    "readiness_revalidation": "services.readiness_graph.revalidation_worker",
    # Authored by INT-C during the credential-turnkey integration pass.
    "stablecoin_provider_polling": "services.stablecoins.polling",
    "derivatives_venue_sweep": "services.derivatives.multi_venue",
    # Main's canonical x402 settlement spec (the old branch-only
    # settlement_reconciliation / x402_reconciliation split folded into one).
    "x402_settlement_reconciliation": "services.rewards.workers",
    "credential_expiry_sweep": "services.rewards.workers",
    "dead_letter_sweeper": "services.runtime.dead_letter_sweeper",
    "reward_reservation_release": "services.rewards.workers",
    "reward_claim_reconciliation": "services.rewards.reconcile",
    "reward_receipt_evidence": "services.rewards.receipt_evidence",
    # Authored during the integration pass: the poll-loop builder lives in
    # services/interop/scan_worker (the spec's factory source).
    "interop_scan": "services.interop.scan_worker",
}

# Workers whose builders are still being authored. They must be flag-gated OFF
# by default so a real deployment cannot crash-loop a supervisor slot before the
# builder (or the flag) is live. Currently empty — every registered spec has a
# real, import-asserted builder.
PENDING_BUILD_WORKERS: frozenset[str] = frozenset()


# ── (a) every built spec is claimed by at least one role ────────────────────


def test_build_worker_specs_returns_claimed_specs_only():
    specs = _built_specs()
    assert specs, "expected at least one supervised WorkerSpec"
    names = [spec.name for spec in specs]
    assert len(names) == len(set(names)), "spec names must be unique"
    claimed = _claimed_spec_names()
    unclaimed = set(names) - claimed
    assert not unclaimed, f"specs with no role owner: {sorted(unclaimed)}"


def test_payment_alert_eval_is_no_longer_unclaimed():
    # Regression pin: payment_alert_eval previously ran only in local "all" mode
    # because no role claimed it.
    assert "payment_alert_eval" in _claimed_spec_names()


def test_every_documented_orphan_is_registered_and_claimed():
    specs = {spec.name for spec in _built_specs()}
    missing = DOCUMENTED_ORPHANS - specs
    assert not missing, f"documented orphans not registered: {sorted(missing)}"
    unclaimed = DOCUMENTED_ORPHANS - _claimed_spec_names()
    assert not unclaimed, f"documented orphans with no role owner: {sorted(unclaimed)}"


def test_role_claims_are_backed_by_real_specs():
    # The reverse direction of the no-orphan proof: a role claim for a spec the
    # builder never produces is dead topology (the role would silently wait for
    # a worker nothing registers).
    names = {spec.name for spec in _built_specs()}
    phantom = _claimed_spec_names() - names
    assert not phantom, f"role claims with no backing spec: {sorted(phantom)}"


# ── (b) every documented worker-builder module that exists is registered ────


def test_documented_builder_modules_are_registered():
    specs = {spec.name: spec for spec in _built_specs()}
    for spec_name, module in EXISTING_BUILDER_MODULES.items():
        mod = importlib.import_module(module)
        assert mod is not None, f"{module} failed to import"
        assert spec_name in specs, f"{module} builder is not registered as {spec_name!r}"
        source = inspect.getsource(specs[spec_name].factory)
        assert module in source, (
            f"{spec_name!r} factory does not reference {module}; "
            "the lazy import drifted from the registered builder module"
        )


# ── role-filter integration + inert-by-default guards ───────────────────────


def test_all_role_runs_every_spec():
    specs = _built_specs()
    assert [spec.name for spec in specs_for_role("all", specs)] == [
        spec.name for spec in specs
    ]


def test_every_role_claim_is_selected_by_specs_for_role():
    specs = _built_specs()
    for role, claimed in ROLE_TO_SPEC_NAMES.items():
        owned = {spec.name for spec in specs_for_role(role, specs)}
        missing = set(claimed) - owned
        assert not missing, f"role {role!r} cannot select its own specs: {sorted(missing)}"
        # A role must never select a spec it does not own.
        extra = owned - set(claimed)
        assert not extra, f"role {role!r} selected unowned specs: {sorted(extra)}"


def test_pending_build_workers_are_inert_by_default():
    specs = {spec.name: spec for spec in _built_specs()}
    for name in PENDING_BUILD_WORKERS:
        assert name in specs, f"pending-build worker {name!r} is not registered"
        assert not specs[name].enabled(), (
            f"{name!r} must be flag-gated OFF by default until its builder is "
            "authored and explicitly enabled"
        )
