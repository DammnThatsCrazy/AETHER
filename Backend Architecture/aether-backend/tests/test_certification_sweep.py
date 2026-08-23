"""Offline certification sweep over the ENTIRE first-release provider scope
(program §25/§28).

The canonical credentialless certification (``shared.certification``) certifies
each first-release provider WITHOUT network access or real credentials, by
asserting on the adapter's honest ``AdapterCertificationDescriptor`` (plus
optional offline behavioral hooks). This sweep:

* runs ``run_certification`` over **every** first-release descriptor resolved
  from source (identical to ``scripts/credentialless_certification.py``);
* additionally instantiates the payment adapters and the comms conformance
  adapters so the *behavioral* checks (secret redaction, request construction,
  auth injection, tenant isolation, idempotent replay, …) actually execute
  rather than skip;
* enforces the PR7-time strict gate: no first-release provider may remain
  SCAFFOLDED or below CREDENTIAL_WAITING — unless it is honestly declared in
  ``SCAFFOLDED_ALLOWLIST`` with a reason (currently empty: nothing is declared).

Nothing here makes a network call or needs a credential.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from shared.certification.checks import ALL_CHECKS, run_certification
from shared.certification.readiness import CredentialReadiness, readiness_rank
from shared.certification.registry import (
    build_capability_matrix,
    iter_first_release_descriptors,
)

#: Honest-declaration allowlist for first-release providers that remain
#: SCAFFOLDED. The PR7-time strict gate forbids scaffolded first-release
#: providers; adding an entry here is the *declared* escape hatch and must
#: carry a reason. It is intentionally empty.
SCAFFOLDED_ALLOWLIST: dict[str, str] = {}

#: Domain tokens whose adapters expose behavioral hooks (duck-typed) so the
#: generic behavioral checks apply. Descriptor-only domains certify on the
#: descriptor-level checks; behavioral checks skip honestly.
_HOOKED_DOMAINS = {"payments", "communications"}


def _describe(d) -> str:
    return f"{d.domain}:{d.provider} ({d.adapter})"


def test_first_release_scope_is_nonempty_and_deterministic():
    descriptors = iter_first_release_descriptors()
    assert descriptors, "first-release scope must not be empty"
    keys = [(d.domain, d.provider) for d in descriptors]
    assert keys == sorted(keys), "descriptors must be deterministically sorted"
    # The matrix must be byte-identical across calls (no timestamps/randomness).
    a = build_capability_matrix()
    b = build_capability_matrix()
    assert a == b


# ══════════════════════════════════════════════════════════════════════════
# (1) canonical descriptor-level certification over the whole scope
# ══════════════════════════════════════════════════════════════════════════


def test_descriptor_level_certification_passes_for_every_first_release_provider():
    failures: list[tuple[str, str]] = []
    for d in iter_first_release_descriptors():
        results = run_certification(d)
        for r in results:
            if not r.passed:
                failures.append((_describe(d), f"{r.name}: {r.detail}"))
    assert failures == [], (
        "first-release provider(s) failed credentialless certification:\n"
        + "\n".join(f"  - {p}: {detail}" for p, detail in failures)
    )


# ══════════════════════════════════════════════════════════════════════════
# (2) strict gate: no SCAFFOLDED, none below CREDENTIAL_WAITING
# ══════════════════════════════════════════════════════════════════════════


def test_no_scaffolded_first_release_providers_remain():
    scaffolded = [
        d for d in iter_first_release_descriptors()
        if d.first_release and d.implementation_state == CredentialReadiness.SCAFFOLDED
    ]
    undeclared = [d for d in scaffolded if d.provider not in SCAFFOLDED_ALLOWLIST]
    assert undeclared == [], (
        "first-release provider(s) are SCAFFOLDED with no honest declaration: "
        + ", ".join(_describe(d) for d in undeclared)
    )


def test_strict_gate_all_first_release_providers_at_least_credential_waiting():
    threshold = readiness_rank(CredentialReadiness.CREDENTIAL_WAITING)
    below = [
        d for d in iter_first_release_descriptors()
        if d.first_release and readiness_rank(d.implementation_state) < threshold
    ]
    assert below == [], (
        "first-release provider(s) below CREDENTIAL_WAITING: "
        + ", ".join(f"{_describe(d)}={d.implementation_state.value}" for d in below)
    )


def test_all_first_release_providers_are_marked_first_release():
    descriptors = iter_first_release_descriptors()
    assert all(d.first_release for d in descriptors)
    matrix = build_capability_matrix()
    assert matrix["summary"]["first_release"] == matrix["summary"]["total"]


# ══════════════════════════════════════════════════════════════════════════
# (3) behavioral certification where adapters expose offline hooks
# ══════════════════════════════════════════════════════════════════════════


def _payment_adapter(token: str):
    """Instantiate the payment adapter the registry resolves for ``token``."""
    from shared.certification import registry as cert_registry

    module, cls = cert_registry._PAYMENT_ADAPTERS[token]  # noqa: SLF001 - same source mapping
    mod = __import__(module, fromlist=[cls])
    return getattr(mod, cls)()


@pytest.mark.parametrize(
    "token",
    ["privy", "stripe_onramp", "coinbase", "moonpay", "bridge"],
)
def test_payment_adapter_behavioral_certification(token: str):
    """Instantiated payment adapters must pass ALL checks including the
    behavioral ones (secret redaction, request construction, auth injection)."""
    adapter = _payment_adapter(token)
    ctx = {"timeout_seconds": 30}
    results = run_certification(adapter, ctx)
    assert len(results) == len(ALL_CHECKS)
    failed = [r for r in results if not r.passed]
    assert failed == [], (
        f"payments:{token} failed behavioral certification: "
        + ", ".join(f"{r.name}: {r.detail}" for r in failed)
    )


def test_communications_conformance_passes_for_every_comms_provider():
    """The §25 comms conformance suite (generic + comms-domain checks) must pass
    for every registered communications first-release provider (item 6)."""
    from services.comms.conformance import certify_comms

    providers = [
        d.provider for d in iter_first_release_descriptors()
        if d.domain == "communications"
    ]
    assert providers, "expected at least one communications provider"
    failures: list[tuple[str, str]] = []
    for provider in providers:
        results = certify_comms(connector_type=provider)
        for r in results:
            if not r.passed:
                failures.append((provider, f"{r.name}: {r.detail}"))
    assert failures == [], (
        "communications provider(s) failed the comms conformance suite:\n"
        + "\n".join(f"  - {p}: {detail}" for p, detail in failures)
    )


# ══════════════════════════════════════════════════════════════════════════
# (4) capability-matrix self-consistency (reported readiness stays truthful)
# ══════════════════════════════════════════════════════════════════════════


def test_capability_matrix_is_self_consistent():
    matrix = build_capability_matrix()
    summary = matrix["summary"]
    providers = matrix["providers"]
    assert sum(summary["by_state"].values()) == summary["total"]
    assert sum(summary["by_domain"].values()) == summary["total"]
    assert summary["first_release"] == summary["total"]
    assert summary["total"] == len(providers)
    # Every provider row matches its descriptor-derived readiness.
    for d in iter_first_release_descriptors():
        row = providers[f"{d.domain}:{d.provider}"]
        assert row["state"] == d.implementation_state.value
        assert row["state_rank"] == readiness_rank(d.implementation_state)
