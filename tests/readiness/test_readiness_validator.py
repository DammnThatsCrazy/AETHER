"""The validator must FAIL closed on dishonest readiness records.

Each test constructs a deliberately dishonest record and asserts the specific
guardrail fires. These prove the validation rules in the readiness-refactor
contract are real, not decorative.
"""

from __future__ import annotations

import copy

from scripts.lib.readiness_model import ReadinessModel, feature_from_dict, load_model
from scripts.validate_readiness_model import ERRORS, check_feature

MODEL: ReadinessModel = load_model()


def _base() -> dict:
    return {
        "feature_id": "sample",
        "title": "Sample",
        "scope": {"id": "sample-v1", "version": 1, "target": "pilot"},
        "repository_ceiling": {"type": "CREDENTIAL_TURNKEY", "achieved": True},
        "implementation": {
            "state": "TURNKEY",
            "denominator": "in-scope",
            "controls": [{"id": "c1", "weight": 1, "satisfied": True}],
            "remaining_work": [],
        },
        "productionization": {
            "denominator": "in-scope",
            "controls": [{"id": "p1", "weight": 1, "satisfied": True}],
        },
        "activation": {"state": "NO_EXTERNAL_BLOCKER", "blockers": []},
        "dependencies": {"hard": [], "soft": []},
        "environment_evidence": {
            "local": {"state": "VERIFIED", "credentialed": False},
            "ci": {"state": "VERIFIED", "credentialed": False},
        },
        "operational_ownership": {
            "team": "platform",
            "runbook": "r",
            "dashboards": ["d"],
            "alerts": ["a"],
        },
        "business_readiness": {"applicable": False, "controls": []},
        "confidence": {"level": "HIGH"},
        "release_profiles": {
            "local": {"participation": "required", "implementation_floor": "VERIFIED", "productionization_required": False, "environment_gate": "local"},
        },
    }


def run_checks(d: dict) -> list[str]:
    ERRORS.clear()
    feat = feature_from_dict(d)
    check_feature(feat, MODEL, ids={feat.feature_id})
    errs = list(ERRORS)
    ERRORS.clear()
    return errs


def test_turnkey_requiring_source_change_fails():
    d = _base()
    d["activation"] = {
        "state": "CREDENTIAL_WAITING",
        "blockers": [
            {
                "type": "CREDENTIAL_WAITING",
                "description": "x",
                "owner": "o",
                "required_action": "a",
                "source_code_change_expected": True,  # dishonest for a TURNKEY claim
            }
        ],
    }
    errs = run_checks(d)
    assert any("expects a source-code change" in e for e in errs)


def test_external_blocker_reducing_implementation_fails():
    d = _base()
    d["implementation"] = {
        "state": "RUNTIME_INTEGRATED",
        "denominator": "in-scope",
        "controls": [
            {"id": "c1", "weight": 1, "satisfied": True},
            {"id": "c2", "weight": 1, "satisfied": False},
        ],
        "remaining_work": [],  # but incomplete with only an external blocker
    }
    d["repository_ceiling"] = {"type": "CODE_COMPLETE", "achieved": True}
    d["activation"] = {
        "state": "CREDENTIAL_WAITING",
        "blockers": [
            {
                "type": "CREDENTIAL_WAITING",
                "description": "x",
                "owner": "o",
                "required_action": "a",
                "source_code_change_expected": False,
            }
        ],
    }
    errs = run_checks(d)
    assert any("external blocker appears to reduce implementation" in e or "CREDENTIAL_WAITING with implementation" in e for e in errs)


def test_verified_without_repo_evidence_fails():
    d = _base()
    d["environment_evidence"] = {"staging": {"state": "BLOCKED_EXTERNAL", "credentialed": True}}
    errs = run_checks(d)
    assert any("no VERIFIED local/ci environment evidence" in e for e in errs)


def test_offline_evidence_as_production_fails():
    d = _base()
    d["environment_evidence"]["production"] = {"state": "VERIFIED", "credentialed": False}
    errs = run_checks(d)
    assert any("offline evidence presented as production verification" in e for e in errs)


def test_live_verified_without_credentialed_evidence_fails():
    d = _base()
    d["repository_ceiling"] = {"type": "LIVE_VERIFIED", "achieved": True}
    # no credentialed VERIFIED env present
    errs = run_checks(d)
    assert any("without credentialed VERIFIED environment evidence" in e for e in errs)


def test_missing_denominator_fails():
    d = _base()
    d["implementation"]["denominator"] = ""
    errs = run_checks(d)
    assert any("no explicit denominator" in e for e in errs)


def test_production_required_without_ownership_fails():
    d = _base()
    d["release_profiles"]["production-lean"] = {
        "participation": "required",
        "implementation_floor": "TURNKEY",
        "productionization_required": True,
        "environment_gate": "production",
    }
    d["operational_ownership"] = {"team": "platform"}  # no runbook/alerts/dashboards
    errs = run_checks(d)
    assert any("lacks required operational ownership" in e for e in errs)


def test_expired_evidence_counted_as_verified_fails():
    d = _base()
    d["environment_evidence"]["staging"] = {
        "state": "VERIFIED",
        "credentialed": True,
        "expires_at": "2000-01-01T00:00:00Z",
    }
    errs = run_checks(d)
    assert any("is in the past" in e for e in errs)


def test_scope_denominator_signature_changes_with_weights():
    from scripts.validate_readiness_model import _denominator_signature

    a = feature_from_dict(_base())
    d2 = _base()
    d2["implementation"]["controls"][0]["weight"] = 5
    b = feature_from_dict(d2)
    assert _denominator_signature(a) != _denominator_signature(b)


def test_dependency_cycle_detected():
    from scripts.validate_readiness_model import ERRORS as VE, check_cycles

    a = feature_from_dict(_merge_dep("a", "b"))
    b = feature_from_dict(_merge_dep("b", "a"))
    VE.clear()
    check_cycles([a, b])
    found = any("cycle" in e for e in VE)
    VE.clear()
    assert found


def _merge_dep(fid: str, dep: str) -> dict:
    d = copy.deepcopy(_base())
    d["feature_id"] = fid
    d["dependencies"] = {"hard": [{"feature_id": dep, "state": "SATISFIED"}]}
    return d


def test_real_records_pass_validation():
    """The committed feature records must be honest and internally consistent."""
    from scripts.validate_readiness_model import main

    assert main([]) == 0
