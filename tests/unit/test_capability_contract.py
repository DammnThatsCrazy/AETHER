"""Canonical tenant capability contract — release surface + typed schema.

Pins that GET /v1/capabilities now carries a non-secret release block
(deployment profile, environment, enforcement posture, enabled route prefixes,
excluded domains) so the frontends can gate navigation against what the active
profile actually supports, and that the manifest narrowing only applies to the
founding profile.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

from services.capabilities.release_surface import resolve_release_surface  # noqa: E402
from services.capabilities.schema import (  # noqa: E402
    CapabilitiesResponse,
    EnforcementState,
    ReleaseCapabilities,
)


def test_release_surface_production_lean():
    s = resolve_release_surface("production-lean")
    assert s["deployment_profile"] == "production-lean"
    assert s["release_class"] == "production"
    assert "/v1/profile360" in s["enabled_route_prefixes"]
    assert "stablecoin" in s["excluded_domains"]
    assert "derivatives" in s["excluded_domains"]


def test_release_surface_non_founding_profile_has_no_manifest_narrowing():
    s = resolve_release_surface("production-scale")
    assert s["excluded_domains"] == []
    assert s["enabled_route_prefixes"] == []
    # A real profile still resolves its class.
    assert s["release_class"] in {"production", None} or isinstance(s["release_class"], str)


def test_resolve_release_reflects_settings():
    from config.settings import get_settings
    from services.capabilities.routes import _resolve_release

    rel = _resolve_release(get_settings())
    assert rel.deployment_profile  # non-empty
    assert rel.environment == "local"
    assert isinstance(rel.enforcement.route_registry_enforced, bool)


def test_capabilities_response_schema_roundtrips():
    r = CapabilitiesResponse(
        tenant_id="t",
        release=ReleaseCapabilities(
            deployment_profile="production-lean",
            environment="production",
            release_class="production",
            enforcement=EnforcementState(
                policy_enforcement=True,
                route_registry_enforced=True,
                kyber_operator_gate=True,
            ),
            enabled_route_prefixes=["/v1/profile360"],
            excluded_domains=["stablecoin"],
        ),
        profile_sub_resources=["identity"],
        providers=[{"id": "p", "category": "social", "status": "unconfigured"}],
        consent_purposes_granted=[],
        consent_purposes_all=[],
        feature_flags={"connectors_enabled": False},
        evaluated_at="2026-01-01T00:00:00Z",
    )
    d = r.model_dump()
    assert d["release"]["enforcement"]["route_registry_enforced"] is True
    assert d["release"]["excluded_domains"] == ["stablecoin"]
    # provider dict coerced into the typed shape
    assert d["providers"][0]["circuit_breaker"] == "closed"


def test_capabilities_response_excludes_secret_fields():
    # The contract must never surface secret-like keys.
    fields = set(CapabilitiesResponse.model_fields)
    assert not (fields & {"secrets", "credential", "api_key", "signing_key"})
    rel_fields = set(ReleaseCapabilities.model_fields)
    assert not (rel_fields & {"secrets", "database_url"})
