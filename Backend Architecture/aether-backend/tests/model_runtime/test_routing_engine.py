"""Model-routing engine tests — ADR-008 D4 four routing modes + fallback.

Covers ``auto`` (best-from-registry, allowlist filtering, resolver authority),
``tenant_default``, ``explicit``, and strict ``policy_required`` semantics;
mode resolution from a profile's ``defaultRoutingMode`` (and default to
``auto``); entitlement-denied fallback (recorded with reason); fail-closed
behavior when no entitled fallback exists; and the audit-safe
``describe_selection`` one-liner. Plain ``assert`` only.
"""

from __future__ import annotations

import pytest

from services.model_runtime.models import ModelProvider
from services.model_runtime.routing.engine import ModelRouter
from services.model_runtime.routing.entitlements import AllowlistEntitlementResolver
from services.model_runtime.routing.fallback import StaticFallbackChain
from services.model_runtime.routing.models import (
    RoutingMode,
    RoutingPolicyViolation,
    RoutingRequest,
    RoutingUnavailable,
)

# --------------------------------------------------------------------- helpers


def _make_router(
    *,
    tenant_models,
    chain: StaticFallbackChain | None = None,
    profile_registry=None,
    default_provider: ModelProvider = ModelProvider.DETERMINISTIC,
) -> ModelRouter:
    entitlements = AllowlistEntitlementResolver(
        entitlements={"tenant-acme": tenant_models}
    )
    fallback = chain if chain is not None else StaticFallbackChain(
        ["claude-haiku-4-5-20251001", "gpt-4o-mini"]
    )
    return ModelRouter(
        entitlements,
        fallback=fallback,
        profile_registry=profile_registry,
        default_provider=default_provider,
    )


_ALL = {
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.1-mini",
    "kimi-k2",
    "deepseek-chat",
    "qwen2.5-72b-instruct",
}


def _request(**kwargs) -> RoutingRequest:
    kwargs.setdefault("tenant_id", "tenant-acme")
    return RoutingRequest(**kwargs)


# ------------------------------------------------------------------ auto mode


@pytest.mark.asyncio
async def test_auto_mode_picks_recommended_first():
    router = _make_router(tenant_models=_ALL)
    sel = await router.route(_request(mode=RoutingMode.AUTO))
    assert sel.model_id == "claude-opus-5"  # first recommended in registry order
    assert sel.mode == RoutingMode.AUTO
    assert sel.entitled is True
    assert sel.fallback is False
    assert sel.fallback_reason is None
    assert sel.provider == ModelProvider.ANTHROPIC


@pytest.mark.asyncio
async def test_mode_none_defaults_to_auto():
    router = _make_router(tenant_models=_ALL)
    # No mode, no profile -> AUTO (the documented default).
    sel = await router.route(_request())
    assert sel.mode == RoutingMode.AUTO
    assert sel.model_id == "claude-opus-5"


@pytest.mark.asyncio
async def test_auto_allowlist_filters_skips_better_model():
    router = _make_router(tenant_models=_ALL)
    sel = await router.route(
        _request(mode=RoutingMode.AUTO, entitled_model_ids={"claude-sonnet-5", "gpt-4o-mini"})
    )
    # claude-opus-5 is filtered out by the allowlist; claude-sonnet-5 (recommended,
    # earlier in registry order) wins over gpt-4o-mini (also recommended).
    assert sel.model_id == "claude-sonnet-5"
    assert sel.fallback is False


@pytest.mark.asyncio
async def test_auto_allowlist_can_pick_stable_when_only_candidate():
    router = _make_router(tenant_models=_ALL)
    sel = await router.route(
        _request(mode=RoutingMode.AUTO, entitled_model_ids={"claude-fable-5"})
    )
    assert sel.model_id == "claude-fable-5"
    assert sel.fallback is False


@pytest.mark.asyncio
async def test_auto_empty_allowlist_is_unavailable():
    router = _make_router(tenant_models=_ALL)
    with pytest.raises(RoutingUnavailable):
        await router.route(_request(mode=RoutingMode.AUTO, entitled_model_ids=set()))


@pytest.mark.asyncio
async def test_auto_resolver_authoritative_over_allowlist():
    # The allowlist admits claude-sonnet-5 but the resolver denies it; the
    # resolver is authoritative, so the router falls back.
    router = _make_router(tenant_models={"claude-haiku-4-5-20251001"})
    sel = await router.route(
        _request(
            mode=RoutingMode.AUTO,
            entitled_model_ids={"claude-sonnet-5", "claude-haiku-4-5-20251001"},
        )
    )
    assert sel.model_id == "claude-haiku-4-5-20251001"
    assert sel.fallback is True
    assert sel.fallback_reason is not None


@pytest.mark.asyncio
async def test_auto_best_not_entitled_falls_back():
    router = _make_router(tenant_models={"claude-haiku-4-5-20251001"})
    sel = await router.route(_request(mode=RoutingMode.AUTO))
    assert sel.model_id == "claude-haiku-4-5-20251001"
    assert sel.fallback is True
    assert "entitled" in (sel.fallback_reason or "")


@pytest.mark.asyncio
async def test_auto_uses_custom_registry():
    custom_models = [
        {"modelId": "custom-a", "provider": "anthropic", "status": "recommended"},
        {"modelId": "custom-b", "provider": "openai", "status": "stable"},
    ]
    router = ModelRouter(
        AllowlistEntitlementResolver(entitlements={"tenant-acme": {"custom-a", "custom-b"}}),
        registry_models=custom_models,
        fallback=StaticFallbackChain(["custom-b"]),
    )
    sel = await router.route(_request(mode=RoutingMode.AUTO))
    assert sel.model_id == "custom-a"
    assert sel.provider == ModelProvider.ANTHROPIC
    assert sel.fallback is False


# ------------------------------------------------------------- mode resolution


@pytest.mark.asyncio
async def test_mode_from_profile_default_explicit():
    router = _make_router(tenant_models=_ALL)
    # entity_classification defaultRoutingMode is "explicit".
    sel = await router.route(
        _request(profile_id="entity_classification", requested_model="gpt-4o")
    )
    assert sel.mode == RoutingMode.EXPLICIT
    assert sel.model_id == "gpt-4o"
    assert sel.fallback is False


@pytest.mark.asyncio
async def test_mode_from_profile_default_auto():
    router = _make_router(tenant_models=_ALL)
    # noesis_query_planning defaultRoutingMode is "auto".
    sel = await router.route(_request(profile_id="noesis_query_planning"))
    assert sel.mode == RoutingMode.AUTO
    assert sel.model_id == "claude-opus-5"


# ------------------------------------------------------------ tenant_default


@pytest.mark.asyncio
async def test_tenant_default_mode_selects_default():
    router = _make_router(tenant_models=_ALL)
    sel = await router.route(
        _request(mode=RoutingMode.TENANT_DEFAULT, tenant_default_model="gpt-4o-mini")
    )
    assert sel.model_id == "gpt-4o-mini"
    assert sel.mode == RoutingMode.TENANT_DEFAULT
    assert sel.entitled is True
    assert sel.fallback is False
    assert sel.provider == ModelProvider.OPENAI


@pytest.mark.asyncio
async def test_tenant_default_not_entitled_falls_back():
    router = _make_router(tenant_models={"claude-haiku-4-5-20251001"})
    sel = await router.route(
        _request(mode=RoutingMode.TENANT_DEFAULT, tenant_default_model="gpt-4o-mini")
    )
    assert sel.model_id == "claude-haiku-4-5-20251001"
    assert sel.fallback is True
    assert "not entitled" in (sel.fallback_reason or "")


@pytest.mark.asyncio
async def test_tenant_default_missing_falls_back():
    router = _make_router(tenant_models=_ALL)
    sel = await router.route(_request(mode=RoutingMode.TENANT_DEFAULT))
    assert sel.fallback is True
    assert "not configured" in (sel.fallback_reason or "")


# ---------------------------------------------------------------- explicit


@pytest.mark.asyncio
async def test_explicit_mode_selects_requested():
    router = _make_router(tenant_models=_ALL)
    sel = await router.route(
        _request(mode=RoutingMode.EXPLICIT, requested_model="claude-sonnet-5")
    )
    assert sel.model_id == "claude-sonnet-5"
    assert sel.mode == RoutingMode.EXPLICIT
    assert sel.fallback is False
    assert sel.provider == ModelProvider.ANTHROPIC


@pytest.mark.asyncio
async def test_explicit_not_entitled_falls_back_recorded():
    router = _make_router(tenant_models={"claude-haiku-4-5-20251001"})
    sel = await router.route(
        _request(mode=RoutingMode.EXPLICIT, requested_model="gpt-4o")
    )
    assert sel.model_id == "claude-haiku-4-5-20251001"
    assert sel.mode == RoutingMode.EXPLICIT
    assert sel.fallback is True
    assert sel.fallback_reason is not None
    assert "not entitled" in sel.fallback_reason


@pytest.mark.asyncio
async def test_explicit_missing_requested_model_falls_back():
    router = _make_router(tenant_models=_ALL)
    sel = await router.route(_request(mode=RoutingMode.EXPLICIT))
    assert sel.fallback is True
    assert sel.fallback_reason is not None


@pytest.mark.asyncio
async def test_explicit_not_in_registry_falls_back():
    router = _make_router(tenant_models=_ALL)
    sel = await router.route(
        _request(mode=RoutingMode.EXPLICIT, requested_model="not-a-model")
    )
    assert sel.model_id == "claude-haiku-4-5-20251001"
    assert sel.fallback is True
    assert "unavailable" in (sel.fallback_reason or "")


# ------------------------------------------------------------ policy_required


@pytest.mark.asyncio
async def test_policy_required_uses_requested_model():
    router = _make_router(tenant_models=_ALL)
    sel = await router.route(
        _request(mode=RoutingMode.POLICY_REQUIRED, requested_model="claude-sonnet-5")
    )
    assert sel.model_id == "claude-sonnet-5"
    assert sel.mode == RoutingMode.POLICY_REQUIRED
    assert sel.fallback is False


@pytest.mark.asyncio
async def test_policy_required_denied_is_strict_no_fallback():
    router = _make_router(tenant_models={"claude-haiku-4-5-20251001"})
    # Even though a perfectly good fallback exists, policy_required must NOT
    # silently route elsewhere on denial.
    with pytest.raises(RoutingPolicyViolation):
        await router.route(
            _request(mode=RoutingMode.POLICY_REQUIRED, requested_model="gpt-4o")
        )


@pytest.mark.asyncio
async def test_policy_required_unmandated_is_unavailable():
    router = _make_router(tenant_models=_ALL)
    with pytest.raises(RoutingUnavailable):
        await router.route(_request(mode=RoutingMode.POLICY_REQUIRED))


@pytest.mark.asyncio
async def test_policy_required_profile_mandated_model():
    profile_registry = {
        "policy_mandated": {
            "profileId": "policy_mandated",
            "defaultRoutingMode": "policy_required",
            "allowedRoutingModes": ("policy_required",),
            "mandatedModel": "claude-sonnet-5",
        }
    }
    router = _make_router(tenant_models=_ALL, profile_registry=profile_registry)
    sel = await router.route(
        _request(profile_id="policy_mandated", mode=RoutingMode.POLICY_REQUIRED)
    )
    assert sel.model_id == "claude-sonnet-5"
    assert sel.mode == RoutingMode.POLICY_REQUIRED
    assert sel.fallback is False


@pytest.mark.asyncio
async def test_policy_required_profile_not_allowing_raises():
    router = _make_router(tenant_models=_ALL)
    # noesis_query_planning does not allow policy_required routing.
    with pytest.raises(RoutingPolicyViolation):
        await router.route(
            _request(
                profile_id="noesis_query_planning",
                mode=RoutingMode.POLICY_REQUIRED,
                requested_model="claude-sonnet-5",
            )
        )


@pytest.mark.asyncio
async def test_policy_required_mandated_model_not_in_registry_raises():
    profile_registry = {
        "policy_mandated": {
            "profileId": "policy_mandated",
            "defaultRoutingMode": "policy_required",
            "allowedRoutingModes": ("policy_required",),
            "mandatedModel": "ghost-model",
        }
    }
    router = _make_router(tenant_models=_ALL, profile_registry=profile_registry)
    with pytest.raises(RoutingPolicyViolation):
        await router.route(
            _request(profile_id="policy_mandated", mode=RoutingMode.POLICY_REQUIRED)
        )


# -------------------------------------------------------------------- fallback


@pytest.mark.asyncio
async def test_fallback_records_flag_and_reason():
    router = _make_router(tenant_models={"claude-haiku-4-5-20251001"})
    sel = await router.route(
        _request(mode=RoutingMode.EXPLICIT, requested_model="gpt-4o")
    )
    assert sel.fallback is True
    assert isinstance(sel.fallback_reason, str)
    assert len(sel.fallback_reason) > 0
    assert sel.entitled is True  # the fallback route itself is entitled


@pytest.mark.asyncio
async def test_no_entitled_fallback_is_policy_violation():
    router = _make_router(tenant_models=set())  # nothing is entitled
    with pytest.raises(RoutingPolicyViolation):
        await router.route(
            _request(mode=RoutingMode.EXPLICIT, requested_model="gpt-4o")
        )


@pytest.mark.asyncio
async def test_fallback_never_reuses_requested_model():
    # Requested model is denied; fallback must pick a different entitled model.
    router = _make_router(tenant_models={"claude-haiku-4-5-20251001", "gpt-4o"})
    sel = await router.route(
        _request(mode=RoutingMode.EXPLICIT, requested_model="claude-sonnet-5")
    )
    assert sel.model_id == "claude-haiku-4-5-20251001"
    assert sel.model_id != "claude-sonnet-5"


# -------------------------------------------------------------- provider map


@pytest.mark.asyncio
async def test_unknown_provider_maps_to_default_provider():
    router = _make_router(tenant_models={"kimi-k2"})
    sel = await router.route(
        _request(mode=RoutingMode.EXPLICIT, requested_model="kimi-k2")
    )
    assert sel.model_id == "kimi-k2"
    # "kimi" is not a ModelProvider enum member -> default_provider.
    assert sel.provider == ModelProvider.DETERMINISTIC


@pytest.mark.asyncio
async def test_default_provider_override():
    router = _make_router(
        tenant_models={"kimi-k2"}, default_provider=ModelProvider.OPENAI
    )
    sel = await router.route(
        _request(mode=RoutingMode.EXPLICIT, requested_model="kimi-k2")
    )
    assert sel.provider == ModelProvider.OPENAI


# -------------------------------------------------------- describe_selection


@pytest.mark.asyncio
async def test_describe_selection_is_audit_safe():
    router = _make_router(tenant_models=_ALL)
    sel = await router.route(_request(mode=RoutingMode.AUTO))
    desc = router.describe_selection(sel)
    assert "model=claude-opus-5" in desc
    assert "mode=auto" in desc
    assert "provider=anthropic" in desc
    assert "entitled=yes" in desc
    assert "fallback=no" in desc
    # No tenant id, no credentials, no PII.
    assert "tenant-acme" not in desc
    assert "secret" not in desc and "api" not in desc and "sk-" not in desc


@pytest.mark.asyncio
async def test_describe_selection_includes_fallback_reason():
    router = _make_router(tenant_models={"claude-haiku-4-5-20251001"})
    sel = await router.route(
        _request(mode=RoutingMode.EXPLICIT, requested_model="gpt-4o")
    )
    desc = router.describe_selection(sel)
    assert "fallback=yes" in desc
    assert "reason=" in desc
    # The reason text is safe (no tenant identifier, no credentials).
    assert "tenant-acme" not in desc
    assert "secret" not in desc and "api" not in desc and "sk-" not in desc
