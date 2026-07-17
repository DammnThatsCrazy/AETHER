"""Founding-tenant release-surface exclusion enforcement.

config/founding_tenant_release.yaml excludes whole domains from the founding
release surface. The route-policy middleware must enforce those exclusions
(403) when — and only when — the founding-tenant profile is active. Loading is
lazy: any other profile resolves to an empty exclusion set.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _crypto_ok() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401
        return True
    except BaseException:  # noqa: BLE001 - PanicException is not an Exception
        return False


pytestmark = pytest.mark.skipif(not _crypto_ok(), reason="cryptography unavailable")

_BACKEND_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")

_MANIFEST = yaml.safe_load((ROOT / "config/founding_tenant_release.yaml").read_text())
FOUNDING_PROFILE = _MANIFEST["profile"]
EXCLUDED_DOMAINS = set(_MANIFEST["release_surface"]["excluded_domains"])


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


@contextmanager
def active_profile(profile: str):
    """Fresh backend generation with the given deployment profile active."""
    _evict_backend()
    settings_mod = importlib.import_module("config.settings")
    registry = importlib.import_module("services.security.route_registry")
    registry.founding_excluded_domains.cache_clear()
    settings = settings_mod.settings
    original = settings.runtime
    object.__setattr__(
        settings, "runtime", dataclasses.replace(original, deployment_profile=profile)
    )
    try:
        yield registry
    finally:
        object.__setattr__(settings, "runtime", original)
        registry.founding_excluded_domains.cache_clear()


class _PolicyRequest:
    class _State:
        request_id = "req-test"

    def __init__(self):
        self.headers = {}
        self.method = "GET"
        self.state = self._State()


def _context():
    from shared.auth.auth import Role, TenantContext

    return TenantContext(
        tenant_id="t-1",
        role=Role.EDITOR,
        permissions=["read", "write", "ingest", "analytics"],
    )


def test_manifest_domains_excluded_when_founding_profile_active():
    with active_profile(FOUNDING_PROFILE) as registry:
        assert registry.founding_excluded_domains(FOUNDING_PROFILE) == frozenset(
            EXCLUDED_DOMAINS
        )
        for domain in EXCLUDED_DOMAINS:
            assert registry.founding_domain_excluded(domain, FOUNDING_PROFILE)
        # Plural route domains match their singular manifest entry.
        assert registry.founding_domain_excluded("stablecoins", FOUNDING_PROFILE)
        # Domains on the release surface stay allowed.
        assert not registry.founding_domain_excluded("identity", FOUNDING_PROFILE)
        assert not registry.founding_domain_excluded("batch", FOUNDING_PROFILE)


def test_no_exclusions_when_profile_is_not_founding():
    with active_profile("local-live") as registry:
        assert registry.founding_excluded_domains("local-live") == frozenset()
        for domain in EXCLUDED_DOMAINS:
            assert not registry.founding_domain_excluded(domain, "local-live")


def test_route_policy_denies_excluded_domain_route_for_founding_profile():
    with active_profile(FOUNDING_PROFILE):
        mw = importlib.import_module("middleware.middleware")
        denial = mw._evaluate_route_policy(
            _PolicyRequest(), "/v1/derivatives/positions", _context()
        )
        assert denial is not None
        assert "ROUTE_POLICY_DOMAIN_EXCLUDED" in str(denial.to_dict())


def test_route_policy_allows_release_surface_route_for_founding_profile():
    with active_profile(FOUNDING_PROFILE):
        mw = importlib.import_module("middleware.middleware")
        assert (
            mw._evaluate_route_policy(_PolicyRequest(), "/v1/identity/resolve", _context())
            is None
        )


def test_route_policy_allows_excluded_domain_when_profile_off():
    with active_profile("local-live"):
        mw = importlib.import_module("middleware.middleware")
        assert (
            mw._evaluate_route_policy(
                _PolicyRequest(), "/v1/derivatives/positions", _context()
            )
            is None
        )
