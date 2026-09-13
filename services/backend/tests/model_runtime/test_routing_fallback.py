"""Fallback chain + fallback selection tests (ADR-008 D4).

Verifies the safe-path guarantee: fallbacks never return the requested model,
never bypass the entitlement gate, and fail closed (unavailable vs policy
violation) with audit-safe reason strings.
"""

from __future__ import annotations

import pytest

from services.model_runtime.models import ModelProvider
from services.model_runtime.routing.fallback import (
    RegistryFallbackChain,
    StaticFallbackChain,
    select_fallback,
)
from services.model_runtime.routing.models import (
    RoutingPolicyViolation,
    RoutingUnavailable,
)


# --- StaticFallbackChain -------------------------------------------------


def test_static_chain_returns_order():
    chain = StaticFallbackChain(("claude-sonnet-5", "claude-haiku-4-5-20251001", "gpt-4o-mini"))
    assert chain.candidates() == (
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
        "gpt-4o-mini",
    )


def test_static_chain_accepts_list_and_records_provider():
    chain = StaticFallbackChain(["claude-sonnet-5"], provider=ModelProvider.ANTHROPIC)
    assert chain.candidates() == ("claude-sonnet-5",)
    assert chain.provider == ModelProvider.ANTHROPIC


def test_static_chain_provider_defaults_to_none():
    chain = StaticFallbackChain(("claude-sonnet-5",))
    assert chain.provider is None


def test_static_chain_describe_prefix():
    chain = StaticFallbackChain(("claude-sonnet-5", "claude-haiku-4-5-20251001"))
    assert chain.describe("claude-opus-5 unavailable") == (
        "fallback: claude-opus-5 unavailable -> claude-sonnet-5, claude-haiku-4-5-20251001"
    )


# --- select_fallback: requested-model exclusion ---------------------------


def test_select_fallback_skips_requested_model():
    chain = StaticFallbackChain(("claude-opus-5", "claude-sonnet-5"))
    assert select_fallback("claude-opus-5", chain) == "claude-sonnet-5"


def test_select_fallback_skips_requested_model_not_first():
    chain = StaticFallbackChain(("claude-opus-5", "claude-sonnet-5"))
    assert select_fallback("claude-sonnet-5", chain) == "claude-opus-5"


def test_select_fallback_returns_first_candidate_when_not_requested():
    chain = StaticFallbackChain(("claude-sonnet-5", "claude-haiku-4-5-20251001"))
    assert select_fallback("claude-opus-5", chain) == "claude-sonnet-5"


# --- select_fallback: entitlement gating ---------------------------------


def test_select_fallback_must_entitle_skips_non_entitled():
    chain = StaticFallbackChain(("claude-opus-5", "gpt-4o-mini", "claude-sonnet-5"))
    entitled = {"claude-sonnet-5"}
    assert (
        select_fallback("claude-opus-5", chain, must_entitle=entitled.__contains__)
        == "claude-sonnet-5"
    )


def test_select_fallback_must_entitle_gates_first_entitled():
    chain = StaticFallbackChain(("claude-sonnet-5", "claude-haiku-4-5-20251001"))
    entitled = {"claude-haiku-4-5-20251001"}
    assert (
        select_fallback("claude-opus-5", chain, must_entitle=entitled.__contains__)
        == "claude-haiku-4-5-20251001"
    )


def test_select_fallback_no_entitled_candidate_raises_policy_violation():
    chain = StaticFallbackChain(("claude-opus-5", "gpt-4o-mini"))
    with pytest.raises(RoutingPolicyViolation) as exc:
        select_fallback("claude-opus-5", chain, must_entitle=lambda m: False)
    assert str(exc.value) == "no entitled fallback"


# --- select_fallback: unavailable -----------------------------------------


def test_select_fallback_empty_chain_raises_unavailable():
    chain = StaticFallbackChain(())
    with pytest.raises(RoutingUnavailable) as exc:
        select_fallback("claude-opus-5", chain)
    assert str(exc.value) == "no fallback available"


def test_select_fallback_all_same_model_raises_unavailable():
    chain = StaticFallbackChain(("claude-opus-5", "claude-opus-5"))
    with pytest.raises(RoutingUnavailable) as exc:
        select_fallback("claude-opus-5", chain)
    assert str(exc.value) == "no fallback available"


def test_select_fallback_single_same_model_raises_unavailable():
    chain = StaticFallbackChain(("claude-opus-5",))
    with pytest.raises(RoutingUnavailable):
        select_fallback("claude-opus-5", chain)


# --- RegistryFallbackChain ------------------------------------------------


def test_registry_chain_default_candidates():
    chain = RegistryFallbackChain()
    assert chain.candidates() == (
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
    )


def test_registry_chain_excludes_given_ids():
    chain = RegistryFallbackChain(exclude=("claude-opus-5", "claude-sonnet-5"))
    assert chain.candidates() == (
        "claude-haiku-4-5-20251001",
        "claude-fable-5",
        "claude-opus-4-8",
    )


def test_registry_chain_respects_require_status():
    chain = RegistryFallbackChain(require_status=("stable",))
    assert chain.candidates() == ("claude-fable-5", "claude-opus-4-8", "claude-sonnet-4-6")


def test_registry_chain_require_status_only_recommended():
    chain = RegistryFallbackChain(require_status=("recommended",), max_candidates=5)
    assert chain.candidates() == (
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
        "gpt-4o-mini",
    )


def test_registry_chain_max_candidates_cap():
    chain = RegistryFallbackChain(max_candidates=1)
    assert chain.candidates() == ("claude-opus-5",)


def test_registry_chain_zero_max_candidates_is_empty():
    chain = RegistryFallbackChain(max_candidates=0)
    assert chain.candidates() == ()


def test_registry_chain_deterministic_across_calls():
    chain = RegistryFallbackChain(exclude=("claude-opus-5",))
    first = chain.candidates()
    second = chain.candidates()
    third = chain.candidates()
    assert first == second == third
    assert first == ("claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-fable-5")


def test_registry_chain_describe_prefix():
    chain = RegistryFallbackChain()
    assert chain.describe("over budget") == (
        "fallback: over budget -> claude-opus-5, claude-sonnet-5, claude-haiku-4-5-20251001"
    )


def test_registry_chain_select_fallback_skips_requested():
    chain = RegistryFallbackChain()
    # claude-opus-5 is the registry's first candidate; requesting it must skip it.
    assert select_fallback("claude-opus-5", chain) == "claude-sonnet-5"
