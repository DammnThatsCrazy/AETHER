"""Guards for the capability-matrix join layer (config/capability_matrix.yaml).

scripts/staging_capability_matrix.py joins config/deploy_profile.yaml's
capability matrix to every other release facet by key: route_registry prefixes,
runtime roles, founding-release flags, deploy_profile dependencies, and
deployment-readiness control evidence. These tests pin the properties that make
the join trustworthy: the real matrix resolves completely, a dangling reference
into any facet fails, and coverage between deploy_profile and the join layer is
bidirectional — a capability missing from either side is an error, never a
silent narrowing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import staging_capability_matrix as scm  # noqa: E402


# ── Fixture data: a minimal, fully valid join world ───────────────────────────

FACETS = {
    "routes": {"/v1/batch", "/ready"},
    "roles": {"api", "graph-writer", "lean-worker"},
    "flags": {"ROUTE_REGISTRY_ENFORCED", "ingestion_v2"},
    "readiness_ids": {"LEAN-RUNTIME-TOPOLOGY", "STG-SMOKE"},
    "known_profiles": {"local", "staging", "production-lean"},
}

DEPLOY_CAPABILITIES = {"api": "present", "graph": "present", "traces": "gap"}


def _entry(cid: str, **overrides) -> dict:
    base = {
        "id": cid,
        "route": None,
        "runtime_role": None,
        "release_flag": None,
        "depends_on": [],
        "control_evidence": "LEAN-RUNTIME-TOPOLOGY",
        "states": {
            "local": "required_enabled",
            "staging": "required_enabled",
            "production-lean": "required_enabled",
        },
    }
    base.update(overrides)
    return base


def _doc(entries: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "canonical_source": "config/capability_matrix.yaml",
        "profiles": ["local", "staging", "production-lean"],
        "capabilities": entries,
    }


def _errors(doc: dict, deploy=None) -> list[str]:
    return scm.join_errors(
        doc,
        deploy_capabilities=dict(deploy if deploy is not None else DEPLOY_CAPABILITIES),
        routes=set(FACETS["routes"]),
        roles=set(FACETS["roles"]),
        flags=set(FACETS["flags"]),
        readiness_ids=set(FACETS["readiness_ids"]),
        known_profiles=set(FACETS["known_profiles"]),
    )


def _valid_entries() -> list[dict]:
    return [
        _entry(
            "api",
            route="/v1/batch",
            runtime_role="api",
            release_flag="ROUTE_REGISTRY_ENFORCED",
            depends_on=["graph"],
        ),
        _entry("graph", runtime_role="graph-writer"),
        _entry(
            "traces",
            control_evidence=None,
            states={
                "local": "not_in_release",
                "staging": "not_in_release",
                "production-lean": "not_in_release",
            },
        ),
    ]


# ── The real repo matrix must resolve completely ──────────────────────────────

def test_real_repo_matrix_passes() -> None:
    result = scm.check()
    assert result["passed"], result["errors"]
    # The join layer covers exactly the deploy_profile capability set.
    assert result["counts"]["join_entries"] == result["counts"]["capabilities"]


# ── Synthetic matrix: valid / dangling / missing ──────────────────────────────

def test_valid_synthetic_matrix_has_no_errors() -> None:
    assert _errors(_doc(_valid_entries())) == []


def test_dangling_route_reference_fails() -> None:
    entries = _valid_entries()
    entries[0]["route"] = "/v1/does-not-exist"
    errors = _errors(_doc(entries))
    assert any("route '/v1/does-not-exist'" in e for e in errors), errors


def test_dangling_runtime_role_fails() -> None:
    entries = _valid_entries()
    entries[1]["runtime_role"] = "phantom-worker"
    errors = _errors(_doc(entries))
    assert any("runtime_role 'phantom-worker'" in e for e in errors), errors


def test_dangling_release_flag_fails() -> None:
    entries = _valid_entries()
    entries[0]["release_flag"] = "NO_SUCH_FLAG"
    errors = _errors(_doc(entries))
    assert any("release_flag 'NO_SUCH_FLAG'" in e for e in errors), errors


def test_dangling_control_evidence_fails() -> None:
    entries = _valid_entries()
    entries[1]["control_evidence"] = "CTRL-NOT-REAL"
    errors = _errors(_doc(entries))
    assert any("control_evidence 'CTRL-NOT-REAL'" in e for e in errors), errors


def test_dangling_dependency_fails() -> None:
    entries = _valid_entries()
    entries[0]["depends_on"] = ["not-a-capability"]
    errors = _errors(_doc(entries))
    assert any("depends_on 'not-a-capability'" in e for e in errors), errors


def test_missing_capability_fails_bidirectionally() -> None:
    # deploy_profile declares "graph" but the join layer omits it.
    entries = [e for e in _valid_entries() if e["id"] != "graph"]
    errors = _errors(_doc(entries))
    assert any("missing from" in e and "graph" in e for e in errors), errors

    # The join layer declares a capability deploy_profile does not know.
    entries = _valid_entries() + [_entry("phantom")]
    errors = _errors(_doc(entries))
    assert any(
        "capability_matrix[phantom]" in e and "deploy_profile" in e for e in errors
    ), errors


# ── Enum / honesty rules ──────────────────────────────────────────────────────

def test_off_enum_state_fails() -> None:
    entries = _valid_entries()
    entries[0]["states"]["staging"] = "probably_fine"
    errors = _errors(_doc(entries))
    assert any("'probably_fine'" in e for e in errors), errors


def test_gap_capability_cannot_claim_enabled_state() -> None:
    entries = _valid_entries()
    entries[2]["states"]["production-lean"] = "required_enabled"
    entries[2]["control_evidence"] = "STG-SMOKE"
    errors = _errors(_doc(entries))
    assert any("status is 'gap'" in e for e in errors), errors


def test_required_enabled_without_control_evidence_fails() -> None:
    entries = _valid_entries()
    entries[0]["control_evidence"] = None
    errors = _errors(_doc(entries))
    assert any("control_evidence is null" in e for e in errors), errors


def test_states_must_cover_declared_profiles() -> None:
    entries = _valid_entries()
    del entries[0]["states"]["staging"]
    errors = _errors(_doc(entries))
    assert any("states missing declared profile(s)" in e for e in errors), errors


def test_unknown_entry_key_fails() -> None:
    entries = _valid_entries()
    entries[0]["rout"] = "/v1/batch"  # typo must fail loudly, never default
    errors = _errors(_doc(entries))
    assert any("unknown key(s)" in e for e in errors), errors
