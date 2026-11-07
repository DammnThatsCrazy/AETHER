"""Financial capability records: generated matrix + cross-registry fail-closed."""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))

from connectors.integrations.data_rights.models import SourceUseAuthority
from shared.certification.capability_records import (
    build_financial_capability_matrix,
    domain_event_vocabulary,
    events_for_operations,
    validate_financial_capability_matrix,
)
from shared.certification.registry import (
    import_errors,
    iter_financial_descriptors,
)

OUTPUT = ROOT / "docs" / "_generated" / "financial-capability-matrix.json"


def _load(relative: str) -> dict:
    loaded = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _release() -> dict:
    return _load("config/founding_tenant_release.yaml")


def _matrix() -> dict:
    return build_financial_capability_matrix(
        iter_financial_descriptors(), release_manifest=_release()
    )


def _validate(matrix: dict) -> list[str]:
    return validate_financial_capability_matrix(
        matrix,
        service_classification=_load("config/service_classification.yaml"),
        route_registry=_load("config/route_registry.yaml"),
        release_manifest=_release(),
        deployment_profiles=_load("config/deployment_profiles.yaml"),
        data_rights_fields=SourceUseAuthority.model_fields,
        root=ROOT,
    )


def _version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def _generated_payload(matrix: dict) -> dict:
    payload = {
        "version": _version(),
        "generated_from": "services/api/shared/certification/capability_records.py",
        **matrix,
    }
    payload["summary"]["import_errors"] = import_errors()
    return payload


def test_committed_financial_matrix_matches_runtime_registry():
    committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert committed == _generated_payload(_matrix())


def test_financial_matrix_cross_registry_validation_passes():
    assert _validate(_matrix()) == []


def test_unknown_financial_domain_fails_build():
    descriptor = iter_financial_descriptors()[0].model_copy(
        update={"domain": "not_a_financial_domain"}
    )
    try:
        build_financial_capability_matrix([descriptor], release_manifest=_release())
    except ValueError as exc:
        assert "unknown financial domain" in str(exc)
    else:
        raise AssertionError("unknown financial domain should fail closed")


def test_event_claims_follow_declared_operations():
    matrix = _matrix()
    for record in matrix["records"].values():
        domain = record["domain"]
        expected = events_for_operations(domain, record["supported_operations"])
        assert set(record["supported_event_types"]) == set(expected)
        assert set(record["supported_event_types"]) <= set(domain_event_vocabulary(domain))


def test_derivative_snapshot_operations_do_not_claim_lifecycle_events():
    matrix = _matrix()
    for record in matrix["records"].values():
        if record["domain"] != "derivatives":
            continue
        if "realtime_account_stream" in record["supported_operations"]:
            continue
        assert "derivatives_position_opened_observed" not in record["supported_event_types"]


def test_summary_counts_match_records_and_domains():
    matrix = _matrix()
    records = matrix["records"]
    summary = matrix["summary"]
    assert summary["total"] == len(records)
    assert summary["total"] == len(iter_financial_descriptors())
    assert sum(summary["by_domain"].values()) == summary["total"]
    assert sum(summary["by_state"].values()) == summary["total"]
    assert set(summary["by_domain"]) == set(matrix["domain_surfaces"])


def test_canonical_but_unreachable_event_fails_closed():
    matrix = copy.deepcopy(_matrix())
    record = next(
        item
        for item in matrix["records"].values()
        if item["domain"] == "derivatives"
        and "realtime_account_stream" not in item["supported_operations"]
    )
    record["supported_event_types"].append("derivatives_position_opened_observed")
    errors = _validate(matrix)
    assert any("not reachable from declared operations" in error for error in errors)


def test_unknown_event_type_fails_closed():
    matrix = copy.deepcopy(_matrix())
    record = next(iter(matrix["records"].values()))
    record["supported_event_types"].append("not_a_canonical_event")
    errors = _validate(matrix)
    assert any("unsupported event type" in error for error in errors)


def test_production_claim_fails_closed_for_excluded_financial_domain():
    matrix = copy.deepcopy(_matrix())
    record = next(iter(matrix["records"].values()))
    record["deployment_profiles"] = ["staging", "production"]
    errors = _validate(matrix)
    assert any("claims production" in error for error in errors)


def test_scaffolded_record_cannot_advertise_events():
    matrix = copy.deepcopy(_matrix())
    record = next(iter(matrix["records"].values()))
    record["state"] = "scaffolded"
    record["state_rank"] = 0
    errors = _validate(matrix)
    assert any("scaffolded record must not advertise event types" in error for error in errors)


def test_unknown_data_right_fails_closed():
    matrix = copy.deepcopy(_matrix())
    record = next(iter(matrix["records"].values()))
    record["required_data_rights"] = ["everything_forever"]
    errors = _validate(matrix)
    assert any("unknown data right" in error for error in errors)
