"""Publishable API keys — the key class that ships inside page HTML.

A secret key is held server-side. A publishable key is installed in a
customer's page by the CDN loader's snippet, so it is public the moment it is
issued: anyone can read it out of View Source. That changes what it may be
issued with and what it may reach, and both halves are asserted here because
either one alone is not a control:

  * what it is granted — ingestion authority only, never the caller's
    requested permissions, and never without a site binding;
  * what it reaches — confined to ingestion paths by credential class, and
    unable to write for a site it was not issued for.

There is also a cache half. validate_async resolves a key from the auth cache
before the durable record, so a class or binding that reaches only the record
is not enforced at all on the fast path. That split-brain is asserted directly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "services" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

import asyncio  # noqa: E402

from shared.auth.auth import (  # noqa: E402
    APIKeyValidator,
    CREDENTIAL_CLASS_PUBLISHABLE,
    KEY_CLASS_PUBLISHABLE,
    KEY_CLASS_SECRET,
    PUBLISHABLE_KEY_PERMISSIONS,
    _build_context_from_key_data,
)
from services.me.key_issuance import generate_raw_key, resolve_key_grant  # noqa: E402


# ── What a publishable key is issued with ────────────────────────────────────

def test_publishable_key_is_granted_ingest_authority_not_what_was_requested():
    """POST /v1/batch is guarded twice — ingest at the boundary, write in the
    handler — so the issued set is fixed, not taken from the caller."""
    permissions, site_ids = resolve_key_grant(KEY_CLASS_PUBLISHABLE, ["read"], ["site_a"])
    assert permissions == PUBLISHABLE_KEY_PERMISSIONS
    assert "ingest" in permissions and "write" in permissions
    assert site_ids == ["site_a"]


def test_publishable_key_cannot_widen_its_own_grant():
    """A caller asking for more gets the fixed set, never the union."""
    permissions, _ = resolve_key_grant(
        KEY_CLASS_PUBLISHABLE, ["read", "admin", "billing"], ["site_a"]
    )
    assert permissions == PUBLISHABLE_KEY_PERMISSIONS
    assert "billing" not in permissions


def test_publishable_key_requires_a_site_binding():
    """Refusing an unscoped one is what makes the binding mean anything —
    permitting it would make every publishable key tenant-wide."""
    for empty in (None, []):
        with pytest.raises(Exception) as exc:
            resolve_key_grant(KEY_CLASS_PUBLISHABLE, ["read"], empty)
        assert "site_ids is required" in str(exc.value)


def test_secret_key_keeps_the_callers_permissions_and_no_site_binding():
    permissions, site_ids = resolve_key_grant(KEY_CLASS_SECRET, ["read", "analytics"], ["site_a"])
    assert permissions == ["read", "analytics"]
    # A secret key is not public, so the site binding does not apply to it.
    assert site_ids is None


def test_secret_key_is_the_default_class():
    assert KEY_CLASS_SECRET == "secret"
    assert KEY_CLASS_SECRET != KEY_CLASS_PUBLISHABLE


def test_the_credential_itself_states_which_class_it_is():
    """A secret key pasted into a snippet works perfectly until someone reads
    it out of View Source, so the mistake is silent. The prefix is what lets
    the loader warn about it at all."""
    assert generate_raw_key(KEY_CLASS_PUBLISHABLE).startswith("pk_")
    assert generate_raw_key(KEY_CLASS_SECRET).startswith("ak_")


def test_an_unknown_class_does_not_mint_a_publishable_key():
    """The prefix follows the class, and an unrecognised class is not
    publishable — so a typo cannot produce a credential that looks public."""
    assert generate_raw_key("publishable-ish").startswith("ak_")


# ── What a publishable key resolves to at request time ───────────────────────

def _key_data(**overrides) -> dict:
    data = {
        "tenant_id": "tenant-1",
        "role": "editor",
        "tier": "free",
        "permissions": PUBLISHABLE_KEY_PERMISSIONS,
    }
    data.update(overrides)
    return data


def test_publishable_record_resolves_to_the_publishable_credential_class():
    context = _build_context_from_key_data(
        _key_data(key_class=KEY_CLASS_PUBLISHABLE, site_ids=["site_a", "site_b"])
    )
    assert context.credential_class == CREDENTIAL_CLASS_PUBLISHABLE
    assert context.site_ids == ["site_a", "site_b"]


def test_secret_record_stays_legacy_and_unbound():
    context = _build_context_from_key_data(_key_data(key_class=KEY_CLASS_SECRET, site_ids=None))
    assert context.credential_class == "legacy"
    assert context.site_ids is None


def test_record_without_a_class_is_treated_as_secret():
    """Every key minted before this class existed must keep working unchanged,
    and must not be silently promoted into a class with different reach."""
    context = _build_context_from_key_data(_key_data())
    assert context.credential_class == "legacy"
    assert context.site_ids is None


def test_unknown_class_does_not_resolve_to_publishable():
    """Fail closed: an unrecognised class must not land in the publishable
    branch, which would hand it ingestion-only confinement it was never
    reviewed for — or, worse, be treated as trusted."""
    context = _build_context_from_key_data(_key_data(key_class="something_new"))
    assert context.credential_class == "legacy"


def test_publishable_class_survives_the_identity_of_the_tenant():
    """The binding is per-credential; it must not leak onto other tenants."""
    a = _build_context_from_key_data(
        _key_data(tenant_id="t-a", key_class=KEY_CLASS_PUBLISHABLE, site_ids=["site_a"])
    )
    b = _build_context_from_key_data(
        _key_data(tenant_id="t-b", key_class=KEY_CLASS_PUBLISHABLE, site_ids=["site_b"])
    )
    assert (a.tenant_id, a.site_ids) == ("t-a", ["site_a"])
    assert (b.tenant_id, b.site_ids) == ("t-b", ["site_b"])


# ── The cache path carries the class too ─────────────────────────────────────
#
# validate_async reads the auth cache before the durable record. A class or
# binding written only to the record is therefore not enforced at all for the
# entry's whole TTL — the key would resolve as an unconfined legacy key. That
# is the failure this section exists to prevent.


class _FakeCache:
    """Minimal stand-in for CacheClient — the validator only needs get/set_json."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def set_json(self, key, value, ttl=None):
        self.store[str(key)] = value

    async def get_json(self, key):
        return self.store.get(str(key))


def _registered_context(**kwargs):
    """Register a key, then resolve it back through the cache-only path."""
    cache = _FakeCache()
    validator = APIKeyValidator(environment="test", cache=cache)

    raw_key = "ak_" + "a" * 24
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        validator.register_api_key(
            api_key=raw_key,
            tenant_id="tenant-1",
            role="editor",
            tier="free",
            **kwargs,
        )
    )
    # Prove the resolution came from the cache, not a durable lookup.
    assert cache.store, "register_api_key wrote nothing to the cache"
    return validator, raw_key, cache


def test_registered_publishable_key_resolves_as_publishable_from_cache():
    validator, raw_key, _ = _registered_context(
        permissions=PUBLISHABLE_KEY_PERMISSIONS,
        key_class=KEY_CLASS_PUBLISHABLE,
        site_ids=["site_a"],
    )
    context = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        validator.validate_async(raw_key)
    )
    assert context.credential_class == CREDENTIAL_CLASS_PUBLISHABLE
    assert context.site_ids == ["site_a"]


def test_registered_secret_key_resolves_as_legacy_from_cache():
    validator, raw_key, _ = _registered_context(
        permissions=["read"], key_class=KEY_CLASS_SECRET
    )
    context = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        validator.validate_async(raw_key)
    )
    assert context.credential_class == "legacy"
    assert context.site_ids is None


def test_cache_entry_omitting_the_class_does_not_grant_publishable_reach():
    """A cache entry written by an older code path carries no class; resolving
    it must fall back to legacy, never to a class it was not reviewed for."""
    cache = _FakeCache()
    validator = APIKeyValidator(environment="test", cache=cache)
    raw_key = "ak_" + "b" * 24
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        validator.register_api_key(
            api_key=raw_key, tenant_id="tenant-1", permissions=PUBLISHABLE_KEY_PERMISSIONS
        )
    )
    # Simulate an entry written before the class existed.
    for value in cache.store.values():
        value.pop("key_class", None)
        value.pop("site_ids", None)

    context = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        validator.validate_async(raw_key)
    )
    assert context.credential_class == "legacy"
