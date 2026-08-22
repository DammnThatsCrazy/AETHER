"""Slot registry derives from adapter descriptors and cannot disagree with them."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.providers.credentials.slot_registry import (  # noqa: E402
    build_slot_registry,
    get_slot,
    known_providers,
    slots_for,
)


@pytest.mark.parametrize("provider", list(ADAPTERS.keys()))
def test_registry_matches_adapter_required_credentials(provider):
    adapter = ADAPTERS[provider]
    declared = tuple(adapter.certification_descriptor().required_credentials)
    slot_names = tuple(s.slot_name for s in slots_for(adapter.provider_name))
    assert slot_names == declared, (provider, slot_names, declared)


def test_webhook_only_providers_have_one_slot():
    for p in ("privy", "stripe"):
        names = [s.slot_name for s in slots_for(p)]
        assert names == ["webhook_signing_secret"], (p, names)


def test_polling_providers_have_two_slots_with_endpoint():
    expected_apikey = {
        "coinbase": "onramp_api_key",
        "moonpay": "server_api_key",
        "bridge": "api_key",
    }
    for p, apikey in expected_apikey.items():
        slots = {s.slot_name: s for s in slots_for(p)}
        assert set(slots) == {"webhook_signing_secret", apikey}, (p, set(slots))
        wh = slots["webhook_signing_secret"]
        assert wh.secret_type == "hmac_secret" and wh.rotation_policy == "overlap"
        assert wh.endpoint_policy is None
        ak = slots[apikey]
        assert ak.secret_type == "bearer_token" and ak.rotation_policy == "replace"
        assert ak.endpoint_policy and "host=" in ak.endpoint_policy


def test_unknown_slot_and_provider():
    assert get_slot("coinbase", "webhook_signing_secret") is not None
    assert get_slot("coinbase", "not_a_slot") is None
    assert slots_for("nonexistent-provider") == ()
    # The registry merges payment-adapter-derived providers with the static
    # domain sources (reward signing / rewards webhook); adapters remain a
    # strict subset and never get shadowed.
    assert set(ADAPTERS.keys()) <= set(known_providers())
    from services.rewards.signer_slots import REWARD_SLOT_DECLARATIONS
    from services.x402.credential_slots import declared_slots as x402_slots

    expected = (
        set(ADAPTERS.keys())
        | set(REWARD_SLOT_DECLARATIONS)
        | set(x402_slots())
    )
    assert set(known_providers()) == expected


def test_domain_partition_is_consistent():
    from services.providers.credentials.slot_registry import providers_for_domain

    assert providers_for_domain("payments") == tuple(sorted(ADAPTERS.keys()))
    assert providers_for_domain("signing") == ("reward_signer",)
    # stripe_credit (the stripe_credit reward-rail's own API key) and
    # tenant_webhook (the tenant_webhook rail's HMAC secret) both live in the
    # rewards domain, sorted.
    assert providers_for_domain("rewards") == ("stripe_credit", "tenant_webhook")
    # no provider name appears in two domains
    registry = build_slot_registry()
    for provider, slots in registry.items():
        assert len({s.domain for s in slots} & {"payments"}) <= 1


def test_registry_is_cached_stable():
    assert build_slot_registry() is build_slot_registry()
