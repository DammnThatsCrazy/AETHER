import json
from pathlib import Path

import jsonschema
import pytest

from scripts.release.resolve_environment import load_requirements, resolve


def _full(**overrides):
    values = {name: "PASS" for name in ("vpc", "ecs", "ecr", "sqs", "sns", "dynamodb", "s3", "kms", "secrets", "aurora", "postgres_graph", "cloudfront", "alb", "observability")}
    values.update(overrides)
    return values


def test_staging_resolves_full_and_is_promotion_equivalent():
    result = resolve("staging", _full())
    assert result["disposition"] == "PASS"
    assert result["resolved_profile"] == "staging"
    assert result["production_equivalent"] is True
    assert result["omitted"] == []


def test_staging_degrades_explicitly_when_aurora_is_unavailable():
    result = resolve("staging", _full(aurora="UNAVAILABLE", postgres_graph="PASS"))
    assert result["disposition"] == "PASS_WITH_DEGRADATION"
    assert result["resolved_profile"] == "staging-degraded"
    assert result["production_equivalent"] is False
    assert {item["capability"] for item in result["omitted"]} == {"aurora", "postgres_graph"}
    assert result["capabilities"]["postgres_graph"]["status"] == "UNAVAILABLE"


def test_production_does_not_silently_degrade():
    result = resolve("production-lean", _full(aurora="UNAVAILABLE"))
    assert result["disposition"] == "BLOCKED_EXTERNAL"
    assert result["resolved_profile"] == "production-lean"
    assert result["production_equivalent"] is False
    assert any(item.startswith("aurora:") for item in result["blockers"])
    assert any(item.startswith("postgres_graph:") for item in result["blockers"])


def test_missing_capability_is_unknown_and_blocks_required_profile():
    result = resolve("staging", {})
    assert result["disposition"] == "BLOCKED_EXTERNAL"
    assert result["capabilities"]["aurora"]["status"] == "UNKNOWN"


def test_unknown_profile_and_status_fail_closed():
    with pytest.raises(ValueError, match="unknown deployment profile"):
        resolve("does-not-exist", {})
    with pytest.raises(ValueError, match="unknown capability status"):
        resolve("staging", {"aurora": "HEALTHY"})


def test_resolution_matches_contract_schema():
    schema = json.loads(Path("contracts/delivery/environment-resolution.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(resolve("staging", _full()))


def test_requirements_are_self_consistent():
    requirements = load_requirements()
    assert set(requirements["profiles"]) == {"local", "local-full", "demo", "preview", "staging", "production-lean", "production-scale", "enterprise-isolated"}
