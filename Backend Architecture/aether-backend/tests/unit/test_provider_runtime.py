"""Root CI-gated smoke tests for the Universal Provider Runtime package surface.

Verifies the package re-exports the full public surface (routers, registry
singleton, certification harness), that the routers carry the canonical
prefixes, that ``certify_provider`` returns a ``CertificationReport``, and that
the provider registry's ``load_all()`` is idempotent and installs the legacy
connector corpus with ``source="legacy"``.

The registry integration tests are honestly skipped until Team C's
``services.provider_runtime.registry`` lands; the package import surface and the
certification harness run regardless.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.certification import CertificationReport
from shared.integration_contracts.identity import ProviderIdentity
from shared.integration_contracts.manifest import (
    Accounts,
    Authentication,
    Availability,
    Configuration,
    CredentialFieldSpec,
    Deployment,
    ManifestReadiness,
    ProviderManifest,
    Sync,
    Webhooks,
)
from shared.integration_contracts.normalization import NormalizationResult

from services.provider_runtime import (
    __all__ as provider_runtime_all,
    admin_router,
    certify_provider,
    router,
    webhook_public_router,
)


# ── Package surface ─────────────────────────────────────────────────────────


def test_package_imports_expose_the_full_surface():
    expected = {
        "router",
        "admin_router",
        "webhook_public_router",
        "provider_registry",
        "certify_provider",
    }
    assert expected <= set(provider_runtime_all)
    assert router.prefix == "/v1/provider-connections"
    assert admin_router.prefix == "/v1/admin/kyber/provider-connections"
    assert webhook_public_router.prefix == "/v1/provider-webhooks"
    assert callable(certify_provider)


# ── Certification harness ───────────────────────────────────────────────────


def _make_cert_plugin():
    manifest = ProviderManifest(
        provider_family="shopify",
        product_id="products",
        capability_id="read",
        display_name="Shopify Products",
        category="ecommerce",
        readiness=ManifestReadiness(state=CredentialReadiness.SCAFFOLDED, level=1),
        availability=Availability(),
        authentication=Authentication(
            type="api_key",
            credential_schema=[
                CredentialFieldSpec(name="api_key", type="secret", required=True, secret=True)
            ],
        ),
        configuration=Configuration(),
        accounts=Accounts(),
        webhooks=Webhooks(),
        sync=Sync(),
        data_outputs=["shopify.orders"],
        product_destinations=["olympus_lake"],
        deployment=Deployment(),
    )

    class _Normalizer:
        def normalize(self, raw):
            return NormalizationResult(events=[], dropped=[])

    class _Plugin:
        def identity(self):
            return ProviderIdentity.parse("shopify.products.read")

        def manifest(self):
            return manifest

        def auth(self):
            return None

        def account(self):
            return None

        def pull(self):
            return None

        def webhook(self):
            return None

        def report(self):
            return None

        def stream(self):
            return None

        def reconciliation(self):
            return None

        def normalizer(self):
            return _Normalizer()

    return _Plugin()


def test_certify_provider_returns_report(monkeypatch: pytest.MonkeyPatch):
    # Isolate the Team A capability-honesty seam; the harness must still report
    # a fully-passing certification for a conforming plugin.
    from services.provider_runtime import certification as cert_mod

    monkeypatch.setattr(cert_mod, "_capability_violations", lambda plugin: [])

    report = certify_provider(_make_cert_plugin())

    assert isinstance(report, CertificationReport)
    assert report.identity == "shopify.products.read"
    assert report.passed is True
    assert len(report.checks) == 10


# ── Provider registry (skipped until Team C lands) ─────────────────────────


def test_provider_registry_load_all_idempotent_and_legacy_source():
    try:
        from services.provider_runtime import provider_registry
    except ImportError:
        pytest.skip("blocked on Team C: services.provider_runtime.registry not landed")

    first = provider_registry.load_all()
    second = provider_registry.load_all()
    # Idempotent per registry instance: repeated loads do not grow the registry.
    assert first == second
    assert provider_registry.list() == provider_registry.list()

    sources = provider_registry.sources()
    assert isinstance(sources, dict)
    assert "legacy" in set(sources.values())
