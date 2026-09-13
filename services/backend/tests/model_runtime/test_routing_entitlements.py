"""Tests for server-authoritative routing entitlements (ADR-008 D4).

Covers the allowlist resolver (grant/deny per tenant, fail-closed defaults),
requested-over-default resolution, composite AND-ing, decision immutability, and
the tenant-safe reason invariants (no secrets, no cross-tenant leakage).
Uses plain ``assert`` only; no external assertion libraries.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from services.model_runtime.routing.entitlements import (
    AllowlistEntitlementResolver,
    CompositeEntitlementResolver,
    EntitlementResolver,
)
from services.model_runtime.routing.models import EntitlementDecision, RoutingNotEntitled

# The module this security-invariant test asserts against.
_ENTITLEMENTS_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "model_runtime"
    / "routing"
    / "entitlements.py"
)

# Sensitive patterns that must never appear in a tenant-visible reason.
_FORBIDDEN_IN_REASONS = (
    "sk-",
    "AKIA",
    "api_key",
    "api-key",
    "credential",
    "password",
    "-----BEGIN",
    "/tmp/",
    "/etc/",
    "secret",
)


async def _assert_raises_async(exc_type, fn, *args, **kwargs) -> None:
    """Plain-assert stand-in for pytest.raises on an async callable."""
    try:
        await fn(*args, **kwargs)
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


def test_entitlement_resolver_is_a_protocol():
    # typing.Protocol is structural; verify the members exist on instances.
    res = AllowlistEntitlementResolver(entitlements={"t1": {"m1"}})
    assert callable(res.assert_model_entitled)
    assert callable(res.resolve)
    # And that EntitlementResolver is importable as the named protocol type.
    assert EntitlementResolver is not None


# ---------------------------------------------------------------------------
# Allowlist: grant / deny per tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowlist_grant_deny_per_tenant():
    res = AllowlistEntitlementResolver(
        entitlements={"t1": {"claude-1", "claude-2"}, "t2": {"gpt-4"}}
    )
    granted = await res.assert_model_entitled("t1", "claude-1")
    assert granted.entitled is True
    assert granted.model_id == "claude-1"
    assert granted.tenant_id == "t1"
    assert granted.reason

    denied_t1 = await res.assert_model_entitled("t1", "gpt-4")
    assert denied_t1.entitled is False
    assert denied_t1.model_id == "gpt-4"
    assert denied_t1.reason

    granted_t2 = await res.assert_model_entitled("t2", "gpt-4")
    assert granted_t2.entitled is True

    denied_t2 = await res.assert_model_entitled("t2", "claude-1")
    assert denied_t2.entitled is False


@pytest.mark.asyncio
async def test_allowlist_is_per_tenant_not_global():
    # A model allowed for one tenant must not be entitled for another.
    res = AllowlistEntitlementResolver(entitlements={"t1": {"shared-model"}})
    assert (await res.assert_model_entitled("t1", "shared-model")).entitled is True
    assert (await res.assert_model_entitled("t2", "shared-model")).entitled is False


# ---------------------------------------------------------------------------
# Fail-closed defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tenant_denied_fail_closed():
    res = AllowlistEntitlementResolver(entitlements={"known": {"m1"}})
    dec = await res.assert_model_entitled("ghost", "m1")
    assert dec.entitled is False
    assert "tenant" in dec.reason


@pytest.mark.asyncio
async def test_empty_entitlements_deny_everything():
    res = AllowlistEntitlementResolver()  # no allowlist -> deny all
    assert (await res.assert_model_entitled("t1", "claude-1")).entitled is False
    assert (await res.assert_model_entitled("t2", "anything")).entitled is False


@pytest.mark.asyncio
async def test_missing_model_denied():
    res = AllowlistEntitlementResolver(entitlements={"t1": {"claude-1"}})
    dec = await res.assert_model_entitled("t1", "not-in-allowlist")
    assert dec.entitled is False
    assert dec.model_id == "not-in-allowlist"
    # A known-but-empty tenant allowlist is also a denial, not a grant.
    res2 = AllowlistEntitlementResolver(entitlements={"t1": set()})
    assert (await res2.assert_model_entitled("t1", "claude-1")).entitled is False


# ---------------------------------------------------------------------------
# resolve: requested over default; neither raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_picks_requested_over_default():
    res = AllowlistEntitlementResolver(entitlements={"t1": {"requested", "default"}})
    dec = await res.resolve("t1", "requested", "default")
    assert dec.model_id == "requested"
    assert dec.entitled is True
    # Requested model denied but default allowed -> the requested route is denied.
    res2 = AllowlistEntitlementResolver(entitlements={"t1": {"default"}})
    dec2 = await res2.resolve("t1", "requested", "default")
    assert dec2.model_id == "requested"
    assert dec2.entitled is False


@pytest.mark.asyncio
async def test_resolve_uses_default_when_no_requested():
    res = AllowlistEntitlementResolver(entitlements={"t1": {"default"}})
    dec = await res.resolve("t1", None, "default")
    assert dec.model_id == "default"
    assert dec.entitled is True


@pytest.mark.asyncio
async def test_resolve_with_neither_raises_routing_not_entitled():
    res = AllowlistEntitlementResolver(entitlements={"t1": {"m1"}})
    await _assert_raises_async(RoutingNotEntitled, res.resolve, "t1", None, None)


@pytest.mark.asyncio
async def test_resolve_raises_no_model_requested_message():
    res = AllowlistEntitlementResolver(entitlements={"t1": {"m1"}})
    try:
        await res.resolve("t1", None, None)
    except RoutingNotEntitled as exc:
        assert "no model requested" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("expected RoutingNotEntitled")


# ---------------------------------------------------------------------------
# Composite: fail-closed AND across resolvers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_ands_two_resolvers():
    allow = AllowlistEntitlementResolver(entitlements={"t1": {"m1"}})
    allow2 = AllowlistEntitlementResolver(entitlements={"t1": {"m1"}})

    composite = CompositeEntitlementResolver([allow, allow2])
    dec = await composite.assert_model_entitled("t1", "m1")
    assert dec.entitled is True

    deny = AllowlistEntitlementResolver()  # empty -> denies everything
    composite_deny = CompositeEntitlementResolver([allow, deny])
    dec_deny = await composite_deny.assert_model_entitled("t1", "m1")
    assert dec_deny.entitled is False
    # Reverse order: a single deny still fails the whole composite.
    composite_deny_rev = CompositeEntitlementResolver([deny, allow])
    dec_deny_rev = await composite_deny_rev.assert_model_entitled("t1", "m1")
    assert dec_deny_rev.entitled is False


@pytest.mark.asyncio
async def test_composite_first_deny_reason_wins():
    allow = AllowlistEntitlementResolver(entitlements={"t1": {"m1"}})
    deny = AllowlistEntitlementResolver(entitlements={"t1": {"other"}})
    deny_alone = await deny.assert_model_entitled("t1", "m1")
    assert deny_alone.entitled is False

    composite = CompositeEntitlementResolver([deny, allow])
    dec = await composite.assert_model_entitled("t1", "m1")
    assert dec.entitled is False
    assert dec.reason == deny_alone.reason


@pytest.mark.asyncio
async def test_composite_all_allow_reasons_joined():
    allow_a = AllowlistEntitlementResolver(entitlements={"t1": {"m1"}})
    allow_b = AllowlistEntitlementResolver(entitlements={"t1": {"m1"}})
    composite = CompositeEntitlementResolver([allow_a, allow_b])
    dec = await composite.assert_model_entitled("t1", "m1")
    assert dec.entitled is True
    a = await allow_a.assert_model_entitled("t1", "m1")
    b = await allow_b.assert_model_entitled("t1", "m1")
    assert dec.reason == f"{a.reason}; {b.reason}"


@pytest.mark.asyncio
async def test_composite_empty_denies_all():
    composite = CompositeEntitlementResolver([])
    dec = await composite.assert_model_entitled("t1", "m1")
    assert dec.entitled is False
    assert "resolvers" in dec.reason


@pytest.mark.asyncio
async def test_composite_resolve_semantics():
    allow = AllowlistEntitlementResolver(entitlements={"t1": {"default"}})
    composite = CompositeEntitlementResolver([allow])
    dec = await composite.resolve("t1", None, "default")
    assert dec.model_id == "default"
    assert dec.entitled is True
    await _assert_raises_async(RoutingNotEntitled, composite.resolve, "t1", None, None)


# ---------------------------------------------------------------------------
# Immutability + security
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decisions_are_frozen():
    res = AllowlistEntitlementResolver(entitlements={"t1": {"m1"}})
    dec = await res.assert_model_entitled("t1", "m1")
    assert isinstance(dec, EntitlementDecision)
    for attr in ("entitled", "reason", "model_id", "tenant_id"):
        try:
            setattr(dec, attr, "mutated")
        except (AttributeError, ValidationError):
            continue
        raise AssertionError(f"frozen decision allowed mutation of {attr}")


@pytest.mark.asyncio
async def test_no_secrets_and_no_cross_tenant_leakage_in_reasons():
    res = AllowlistEntitlementResolver(
        entitlements={
            "t1": {"m1", "m2"},
            "other-tenant": {"super-secret-internal-model-id"},
        }
    )

    # Unknown tenant: the reason must not reveal ANY other tenant's allowlist.
    ghost = await res.assert_model_entitled("ghost", "m1")
    assert ghost.entitled is False
    assert "super-secret-internal-model-id" not in ghost.reason
    assert "m2" not in ghost.reason

    # Denied model reason must not include sensitive patterns.
    denied = await res.assert_model_entitled("t1", "sk-ant-badkey")
    assert denied.entitled is False
    for pattern in _FORBIDDEN_IN_REASONS:
        assert pattern not in denied.reason

    # Granted reason is tenant-safe too.
    granted = await res.assert_model_entitled("t1", "m1")
    assert granted.entitled is True
    for pattern in _FORBIDDEN_IN_REASONS:
        assert pattern not in granted.reason


def test_module_never_imports_credentials_or_provider_sdks():
    """Security invariant: no credential backend or provider SDK is reachable."""
    src = _ENTITLEMENTS_SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        "shared.credentials",
        "credential_backend",
        "noesis",
        "import anthropic",
        "import openai",
        "os.getenv",
        "getpass",
    ):
        assert forbidden not in src
