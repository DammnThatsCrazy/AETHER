"""Domain coverage of the credential slot registry (program sec9, gap 1).

Every credentialed domain that the authority must serve — payments, stablecoin
RPCs, derivatives venues, interop providers, rewards rails, x402 facilitators,
signing keys, webhook signing secrets, and OAuth/token refs — must declare at
least one slot. The declarations are policy-only (no live values), environment
templates ("any"), and carry the operational vocabulary (secret type, required
scopes, validation and rotation policy) the state machine depends on.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.providers.credentials.slot_registry import (  # noqa: E402
    build_slot_registry,
    declared_domains,
    get_slot,
    slots_for,
    slots_for_domain,
)

# Every in-scope credentialed domain. ``oauth`` is in scope from the build brief
# (OAuth/token refs) even though it is not named in the gap list.
IN_SCOPE_DOMAINS = (
    "payments",
    "stablecoin_rpc",
    "derivatives",
    "interop",
    "rewards",
    "x402",
    "signing",
    "webhook",
    "oauth",
)

# Slots the build brief explicitly requires per domain.
REQUIRED_SLOTS: dict[str, set[str]] = {
    "stablecoin_rpc": {"api_key"},
    "derivatives": {"api_key"},
    "interop": {"api_key"},
    "rewards": {"signer_key", "webhook_secret"},
    "x402": {"api_key", "webhook_secret"},
    "signing": {"signing_key"},
    "webhook": {"webhook_signing_secret"},
    "oauth": {"token_ref"},
}


@pytest.mark.parametrize("domain", IN_SCOPE_DOMAINS)
def test_every_in_scope_domain_has_declared_slots(domain):
    slots = slots_for_domain(domain)
    assert slots, f"domain {domain!r} has no declared credential slots"
    assert all(s.domain == domain for s in slots), (domain, [s.domain for s in slots])
    assert all(s.environment == "any" for s in slots), (
        domain,
        "declarations must be environment templates (sandbox/live bind at the version)",
    )
    # Every declaration carries the operational vocabulary — no silent defaults.
    for slot in slots:
        assert slot.secret_type, (domain, slot.slot_name)
        assert slot.scope_policy, (domain, slot.slot_name)
        assert slot.required_for, (domain, slot.slot_name)
        assert slot.validation_strategy in ("live_probe", "signature_selfcheck", "token_probe"), (
            domain, slot.slot_name, slot.validation_strategy,
        )
        assert slot.rotation_policy in ("overlap", "replace"), (
            domain, slot.slot_name, slot.rotation_policy,
        )
        assert slot.sensitive is True, (domain, slot.slot_name)


@pytest.mark.parametrize("domain", IN_SCOPE_DOMAINS)
def test_required_slots_are_declared(domain):
    for slot_name in REQUIRED_SLOTS.get(domain, set()):
        assert get_slot(domain, slot_name) is not None, (
            f"domain {domain!r} is missing required slot {slot_name!r}"
        )


def test_all_declared_domains_are_in_scope_and_vice_versa():
    assert set(declared_domains()) == set(IN_SCOPE_DOMAINS)
    # A domain token resolves through the generic provider accessor too, so a
    # tenant can store a domain credential via create_pending.
    for domain in IN_SCOPE_DOMAINS:
        assert slots_for(domain), (domain, "domain token must resolve via slots_for()")


def test_payment_domain_aggregates_adapter_slots():
    payment_slots = slots_for_domain("payments")
    adapter_count = sum(len(slots_for(p)) for p in build_slot_registry())
    assert len(payment_slots) == adapter_count
    assert len(payment_slots) >= 1
    # Payment slots carry their concrete adapter endpoint hints (host=...).
    assert any(s.endpoint_policy and "host=" in s.endpoint_policy for s in payment_slots)


def test_domain_declarations_are_declaration_only():
    """No live values, no concrete hosts — endpoint hints are policy, not URLs."""
    for domain in ("stablecoin_rpc", "derivatives", "interop", "rewards", "x402", "signing", "webhook", "oauth"):
        for slot in slots_for_domain(domain):
            if slot.endpoint_policy:
                assert "://" not in slot.endpoint_policy, (
                    domain, slot.slot_name, slot.endpoint_policy,
                )
                assert not slot.endpoint_policy.lower().startswith("host="), (
                    domain, slot.slot_name, slot.endpoint_policy,
                )
