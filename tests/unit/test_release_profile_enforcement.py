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

import importlib.util
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


# ---------------------------------------------------------------------------
# Env-template ↔ canonical-profile parity (staging / production drift)
# ---------------------------------------------------------------------------
#
# Canonical staging and production-lean FORBID msk, elasticache, neptune and
# clickhouse (config/deployment_profiles.yaml → forbidden_resources). A template
# for those profiles that suggests Kafka, Redis or Neptune as ACTIVE defaults is
# the exact "staging environment drift" defect this guards: the old staging
# template shipped `EVENT_BROKER=kafka` as an active default while the canonical
# staging event backend is sns_sqs and msk is forbidden.
#
# `.env.example` is intentionally excluded: it is the LOCAL development
# template, and the local profile legitimately runs kafka/redis/neptune as
# optional local dependencies.

# Env vars that witness a forbidden dependency being suggested as a default.
_FORBIDDEN_ENV_WITNESSES = (
    "KAFKA_BROKERS",
    "KAFKA_BOOTSTRAP_SERVERS",
    "REDIS_HOST",
    "REDIS_PORT",
    "NEPTUNE_ENDPOINT",
    "CLICKHOUSE_HOST",
    "CLICKHOUSE_PORT",
)

# Canonical backend dimension -> env selector var.
_BACKEND_SELECTOR_VARS = {
    "database": "DATABASE_BACKEND",
    "cache": "CACHE_BACKEND",
    "event": "EVENT_BACKEND",
    "graph": "GRAPH_BACKEND",
    "analytics": "ANALYTICS_BACKEND",
    "object": "OBJECT_BACKEND",
}


def _active_env_keys(path: Path) -> set[str]:
    """Keys declared as ACTIVE (non-commented) env assignments in a template."""
    keys = set()
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        keys.add(s.partition("=")[0].strip())
    return keys


def _profile_backends(profile: str) -> dict[str, str]:
    data = yaml.safe_load((ROOT / "config" / "deployment_profiles.yaml").read_text())
    backends = (data["profiles"][profile] or {}).get("backends")
    assert backends, f"profile {profile!r} has no backends block"
    return backends


def _assert_selectors_match_profile(path: Path, profile: str, *, ml: str, extra: dict[str, str]):
    """The template's *_BACKEND selectors must equal the canonical profile's."""
    backends = _profile_backends(profile)
    vals = _env_values(path)
    for dim, var in _BACKEND_SELECTOR_VARS.items():
        expected = backends[dim]
        assert vals.get(var) == expected, (
            f"{path.name} {var}={vals.get(var)!r} != canonical {profile} "
            f"{dim}={expected!r}"
        )
    assert vals.get("ML_MODE") == ml, (
        f"{path.name} ML_MODE={vals.get('ML_MODE')!r} != canonical {profile} ml={ml!r}"
    )
    for var, expected in extra.items():
        assert vals.get(var) == expected, (
            f"{path.name} {var}={vals.get(var)!r} != expected {expected!r}"
        )


def test_staging_template_selectors_match_canonical_profile():
    # EVENT_BROKER drives actual SQS-vs-Kafka dispatch (shared/events/events.py)
    # and defaults to kafka when unset; staging forbids msk, so it must be
    # pinned to sns_sqs alongside EVENT_BACKEND.
    _assert_selectors_match_profile(
        STAGING,
        "staging",
        ml="inline",
        extra={"EVENT_BROKER": "sns_sqs", "DEPLOYMENT_PROFILE": "staging"},
    )


def test_staging_template_has_no_forbidden_dependency_defaults():
    active = _active_env_keys(STAGING)
    for witness in _FORBIDDEN_ENV_WITNESSES:
        assert witness not in active, (
            f"{STAGING.name} must not declare ACTIVE {witness}: canonical staging "
            "forbids msk/elasticache/neptune/clickhouse"
        )


def test_production_template_selectors_match_canonical_profile():
    # The production example is the founding production-lean template
    # (DEPLOYMENT_PROFILE=production-lean is pinned against the manifest above).
    # Its selectors must equal production-lean's canonical backends: cache is
    # DynamoDB (elasticache forbidden), event is SNS+SQS (msk forbidden).
    _assert_selectors_match_profile(
        PROD,
        "production-lean",
        ml="inline",
        extra={"EVENT_BROKER": "sns_sqs"},
    )


def test_production_template_has_no_forbidden_dependency_defaults():
    active = _active_env_keys(PROD)
    for witness in _FORBIDDEN_ENV_WITNESSES:
        assert witness not in active, (
            f"{PROD.name} must not declare ACTIVE {witness}: canonical "
            "production-lean forbids msk/elasticache/neptune/clickhouse"
        )


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _required_vars(mod, monkeypatch, *, env: str, profile: str | None) -> dict[str, bool]:
    if profile:
        monkeypatch.setenv("DEPLOYMENT_PROFILE", profile)
    else:
        monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
    monkeypatch.setenv("AETHER_ENV", env)
    return dict(mod._required_infra_vars())


def test_validate_infra_is_profile_aware(monkeypatch):
    """validate_infra must derive required infra from the profile's backends."""
    mod = _load_script("validate_infra")

    # staging forbids msk/elasticache/neptune/clickhouse: required infra is the
    # Postgres DSN + the SQS queue URL — nothing Kafka/Redis/Neptune/ClickHouse.
    staging = _required_vars(mod, monkeypatch, env="staging", profile="staging")
    assert staging.get("DATABASE_URL") is True
    assert staging.get("SQS_QUEUE_URL") is True
    assert staging.get("SNS_TOPIC_ARN") is False
    for forbidden in (
        "REDIS_HOST",
        "KAFKA_BOOTSTRAP_SERVERS",
        "NEPTUNE_ENDPOINT",
        "CLICKHOUSE_HOST",
    ):
        assert forbidden not in staging, f"staging must not require {forbidden}"

    # production-lean forbids the same heavy backends.
    lean = _required_vars(mod, monkeypatch, env="production", profile="production-lean")
    assert lean.get("DATABASE_URL") is True
    assert lean.get("SQS_QUEUE_URL") is True
    for forbidden in (
        "REDIS_HOST",
        "KAFKA_BOOTSTRAP_SERVERS",
        "NEPTUNE_ENDPOINT",
        "CLICKHOUSE_HOST",
    ):
        assert forbidden not in lean, f"production-lean must not require {forbidden}"

    # production-scale MAY enable the heavy backends, so their connection vars
    # become required when that profile is selected.
    scale = _required_vars(mod, monkeypatch, env="production", profile="production-scale")
    for required in (
        "REDIS_HOST",
        "KAFKA_BOOTSTRAP_SERVERS",
        "NEPTUNE_ENDPOINT",
        "CLICKHOUSE_HOST",
    ):
        assert scale.get(required) is True, f"production-scale must require {required}"

    # local needs none of the cloud connection vars.
    local = _required_vars(mod, monkeypatch, env="local", profile="local")
    for var in (
        "REDIS_HOST",
        "KAFKA_BOOTSTRAP_SERVERS",
        "NEPTUNE_ENDPOINT",
        "CLICKHOUSE_HOST",
        "SQS_QUEUE_URL",
    ):
        assert var not in local, f"local must not require {var}"


def test_validate_infra_rejects_known_insecure_extraction_seed():
    mod = _load_script("validate_infra")
    assert mod._is_placeholder_or_insecure_default("aether-mesh-canary-seed")
    assert mod._is_placeholder_or_insecure_default(" AETHER-MESH-CANARY-SEED ")
    assert not mod._is_placeholder_or_insecure_default("random-production-seed")
