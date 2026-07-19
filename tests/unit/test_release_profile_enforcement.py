"""Release-surface enforcement config — env examples and excluded-domain denial.

Guards two regressions found during production wiring:
  1. `.env.production.example` shipped ROUTE_REGISTRY_ENFORCED=false and a
     non-canonical DEPLOYMENT_PROFILE=cloud-live, so the route-policy spine was
     inert and the founding-tenant excluded-domain denial never fired.
  2. `.env.staging.example` set no DEPLOYMENT_PROFILE (defaulting to local-live)
     and no enforcement flags.

Also pins that the founding-tenant manifest's excluded domains resolve to a
denied classification under production-lean (and only under that profile).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

PROD = ROOT / ".env.production.example"
STAGING = ROOT / ".env.staging.example"


def _canonical_profiles() -> set[str]:
    data = yaml.safe_load((ROOT / "config" / "deployment_profiles.yaml").read_text())
    return set((data.get("profiles") or {}).keys())


def _env_values(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        # Drop trailing inline comments (" # ...").
        val = re.split(r"\s+#", val, 1)[0].strip()
        out[key.strip()] = val
    return out


def test_env_deployment_profiles_are_canonical():
    canon = _canonical_profiles()
    for envf in (PROD, STAGING):
        prof = _env_values(envf).get("DEPLOYMENT_PROFILE")
        assert prof is not None, f"{envf.name} missing DEPLOYMENT_PROFILE"
        assert prof in canon, (
            f"{envf.name} DEPLOYMENT_PROFILE={prof!r} is not canonical "
            f"(config/deployment_profiles.yaml: {sorted(canon)})"
        )


def test_deploy_targets_enforce_route_registry():
    # The backend fails closed at boot (ROUTE_POLICY_ENFORCEMENT_REQUIRED) if any
    # of these are not true in a deploy target — the example must not contradict it.
    for envf in (PROD, STAGING):
        vals = _env_values(envf)
        for flag in (
            "POLICY_ENFORCEMENT_ENABLED",
            "ROUTE_REGISTRY_ENFORCED",
            "KYBER_OPERATOR_GATE_ENFORCED",
        ):
            assert vals.get(flag) == "true", (
                f"{envf.name} {flag} must be 'true' (fail-closed enforcement)"
            )


def test_production_profile_matches_founding_manifest():
    manifest = yaml.safe_load((ROOT / "config" / "founding_tenant_release.yaml").read_text())
    manifest_profile = str(manifest.get("profile"))
    assert _env_values(PROD).get("DEPLOYMENT_PROFILE") == manifest_profile


def test_excluded_domains_denied_under_production_lean():
    from services.security.route_registry import (
        founding_domain_excluded,
        founding_excluded_domains,
    )

    excluded = founding_excluded_domains("production-lean")
    assert {
        "stablecoin",
        "derivatives",
        "payments",
        "rewards",
        "economic",
        "financial",
        "agent-execution",
    } <= set(excluded)
    # Plural route domain matches its singular manifest entry.
    assert founding_domain_excluded("stablecoins", "production-lean") is True
    assert founding_domain_excluded("derivatives", "production-lean") is True
    assert founding_domain_excluded("payments", "production-lean") is True
    # A core, non-excluded domain stays allowed.
    assert founding_domain_excluded("profile", "production-lean") is False


def test_excluded_domains_scoped_to_founding_profile():
    from services.security.route_registry import founding_excluded_domains

    # The manifest narrows only its declared profile; others are unaffected.
    assert founding_excluded_domains("production-scale") == frozenset()
    assert founding_excluded_domains("staging") == frozenset()
