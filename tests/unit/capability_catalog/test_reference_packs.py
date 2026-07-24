"""Agent-access reference pack tests (AAI-3).

The load-bearing properties proven here are the ones that decide whether a scope
violation gets reported at all:

  1. Every shipped pack loads and satisfies the schema, and the pack directory is
     not empty — a pack that stops loading takes its provider's baselines with it.
  2. A malformed pack **raises, naming the file and field**. It is never skipped:
     ``compute_permission_findings`` defaults a missing grant to ``[]``, so a
     silently dropped pack does not fail closed, it just stops comparing.
  3. ``approved_scope_baselines_for()`` returns the shape
     ``compute_permission_findings`` actually accepts — proven by calling it, not by
     asserting on types — and a grant whose scopes match its baseline produces no
     ``unexpected_new_scope`` finding while one that exceeds it does.
  4. Duplicate pack ids are rejected.
  5. The validator exits non-zero on a bad directory and zero on the real one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from services.agent_access_intelligence.models import CapabilityKind
from services.agent_access_intelligence.reference_packs import (
    PACK_DIR,
    SCHEMA_VERSION,
    ReferencePackError,
    approved_scope_baselines_for,
    clear_pack_cache,
    get_reference_pack,
    load_reference_packs,
    pack_violations,
)
from services.agentic_observability.provider_framework import (
    AuthorizationGrantRecord,
    ProviderActionRecord,
    compute_permission_findings,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / "scripts" / "validate_reference_packs.py"

_KINDS = {k.value for k in CapabilityKind}


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_pack_cache()
    yield
    clear_pack_cache()


def _write_pack(directory: Path, name: str, data: dict) -> Path:
    path = directory / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _valid_pack(pack_id: str = "sample_pack", **overrides) -> dict:
    pack = {
        "schema_version": SCHEMA_VERSION,
        "pack_id": pack_id,
        "pack_version": "1.0.0",
        "pack_status": "example",
        "provider_id": "sample_provider",
        "display_name": "Sample Provider",
        "capability_kind_defaults": {"default": "provider_action"},
        "naming_hints": {"tool_name_fields": ["tool_name"]},
        "baseline_status": "asserted",
        "approved_scope_baselines": {"grant-1": ["sample.read"]},
    }
    pack.update(overrides)
    return pack


# ---------------------------------------------------------------------------
# 1. Every shipped pack loads and validates
# ---------------------------------------------------------------------------


def test_shipped_packs_load_and_validate():
    packs = load_reference_packs()

    assert packs, "no reference packs loaded — the shipped directory must not be empty"
    assert len(packs) == len(
        [p for p in PACK_DIR.iterdir() if p.suffix in (".yaml", ".yml")]
    ), "a pack file on disk did not appear in the loaded set"

    for pack in packs:
        source = f"{pack['pack_id']}.yaml"
        assert pack_violations(pack, source, pack["pack_id"]) == []
        assert pack["schema_version"] == SCHEMA_VERSION
        assert pack["capability_kind_defaults"]["default"] in _KINDS


def test_shipped_pack_ids_are_unique_and_match_filenames():
    ids = [p["pack_id"] for p in load_reference_packs()]
    assert len(ids) == len(set(ids)), f"duplicate pack ids shipped: {ids}"
    for pack_id in ids:
        assert (PACK_DIR / f"{pack_id}.yaml").exists()


def test_grounded_reference_packs_are_shipped():
    """The two grounded packs are the point of the lane; a rename must fail here."""
    packs = {p["pack_id"]: p for p in load_reference_packs()}
    assert packs["x_reference"]["provider_id"] == "x_reference"
    assert packs["mcp_generic"]["provider_id"] == "mcp"
    for pack_id in ("x_reference", "mcp_generic"):
        assert packs[pack_id]["pack_status"] == "reference"
        # A reference pack must say where its claims come from.
        assert packs[pack_id]["grounded_in"]


def test_reference_packs_assert_no_ungrounded_scopes():
    """Neither grounded pack ships an invented third-party scope vocabulary.

    If someone later adds real, verified baselines they must flip baseline_status
    to 'asserted' — which is exactly the review moment this assertion exists to force.
    """
    for pack_id in ("x_reference", "mcp_generic"):
        pack = get_reference_pack(pack_id)
        assert pack["baseline_status"] == "none_asserted"
        assert pack["approved_scope_baselines"] == {}


def test_get_reference_pack_returns_none_for_unknown_id():
    assert get_reference_pack("no_such_pack") is None


def test_loader_returns_copies_so_callers_cannot_corrupt_the_cache():
    first = load_reference_packs()
    first[0]["approved_scope_baselines"]["injected"] = ["evil.write"]
    second = load_reference_packs()
    assert "injected" not in second[0]["approved_scope_baselines"]


# ---------------------------------------------------------------------------
# 2. A malformed pack raises — it is never skipped
# ---------------------------------------------------------------------------


def test_malformed_pack_raises_naming_file_and_field(tmp_path):
    _write_pack(tmp_path, "good_pack.yaml", _valid_pack("good_pack"))
    broken = _valid_pack("bad_pack")
    del broken["approved_scope_baselines"]
    _write_pack(tmp_path, "bad_pack.yaml", broken)

    with pytest.raises(ReferencePackError) as exc:
        load_reference_packs(tmp_path)

    message = str(exc.value)
    assert "bad_pack.yaml" in message, "the error must name the offending file"
    assert "approved_scope_baselines" in message, "the error must name the offending field"


def test_malformed_pack_is_not_silently_skipped(tmp_path):
    """The failure mode this guards: a dropped pack leaves the provider with no
    baselines, and compute_permission_findings then compares against nothing."""
    _write_pack(tmp_path, "good_pack.yaml", _valid_pack("good_pack"))
    _write_pack(tmp_path, "bad_pack.yaml", _valid_pack("bad_pack", schema_version=99))

    with pytest.raises(ReferencePackError):
        load_reference_packs(tmp_path)

    # And no partial result is cached behind the failure.
    with pytest.raises(ReferencePackError):
        approved_scope_baselines_for("sample_provider", tmp_path)


def test_invalid_yaml_raises_naming_the_file(tmp_path):
    (tmp_path / "broken.yaml").write_text("pack_id: [unclosed\n", encoding="utf-8")
    with pytest.raises(ReferencePackError) as exc:
        load_reference_packs(tmp_path)
    assert "broken.yaml" in str(exc.value)


def test_pack_id_must_match_filename(tmp_path):
    _write_pack(tmp_path, "renamed.yaml", _valid_pack("sample_pack"))
    with pytest.raises(ReferencePackError) as exc:
        load_reference_packs(tmp_path)
    assert "renamed.yaml" in str(exc.value)
    assert "filename stem" in str(exc.value)


def test_unknown_capability_kind_rejected(tmp_path):
    _write_pack(
        tmp_path,
        "sample_pack.yaml",
        _valid_pack(capability_kind_defaults={"default": "totally_new_kind"}),
    )
    with pytest.raises(ReferencePackError) as exc:
        load_reference_packs(tmp_path)
    assert "capability_kind_defaults.default" in str(exc.value)


def test_empty_baselines_must_be_declared(tmp_path):
    """An empty baseline map is a real posture; an undeclared one is a truncated file."""
    _write_pack(
        tmp_path,
        "sample_pack.yaml",
        _valid_pack(baseline_status="asserted", approved_scope_baselines={}),
    )
    with pytest.raises(ReferencePackError) as exc:
        load_reference_packs(tmp_path)
    assert "none_asserted" in str(exc.value)


def test_malformed_baseline_values_rejected(tmp_path):
    _write_pack(
        tmp_path,
        "sample_pack.yaml",
        _valid_pack(approved_scope_baselines={"grant-1": "sample.read"}),
    )
    with pytest.raises(ReferencePackError) as exc:
        load_reference_packs(tmp_path)
    assert "approved_scope_baselines" in str(exc.value)


def test_reference_pack_without_grounding_rejected(tmp_path):
    _write_pack(tmp_path, "sample_pack.yaml", _valid_pack(pack_status="reference"))
    with pytest.raises(ReferencePackError) as exc:
        load_reference_packs(tmp_path)
    assert "grounded_in" in str(exc.value)


def test_missing_directory_raises(tmp_path):
    with pytest.raises(ReferencePackError):
        load_reference_packs(tmp_path / "does_not_exist")


# ---------------------------------------------------------------------------
# 3. Duplicate pack ids are rejected
# ---------------------------------------------------------------------------


def test_duplicate_pack_ids_rejected(tmp_path):
    # .yaml and .yml share a filename stem, so both satisfy the pack_id/filename
    # rule while colliding on pack_id. Both suffixes are read on purpose: an
    # ignored .yml file would be a silently dropped pack.
    _write_pack(tmp_path, "dup_pack.yaml", _valid_pack("dup_pack"))
    _write_pack(tmp_path, "dup_pack.yml", _valid_pack("dup_pack"))

    with pytest.raises(ReferencePackError) as exc:
        load_reference_packs(tmp_path)
    assert "duplicate pack_id" in str(exc.value)
    assert "dup_pack" in str(exc.value)


def test_conflicting_provider_baselines_rejected(tmp_path):
    _write_pack(
        tmp_path,
        "pack_a.yaml",
        _valid_pack("pack_a", approved_scope_baselines={"grant-1": ["a.read"]}),
    )
    _write_pack(
        tmp_path,
        "pack_b.yaml",
        _valid_pack("pack_b", approved_scope_baselines={"grant-1": ["a.read", "a.write"]}),
    )
    with pytest.raises(ReferencePackError) as exc:
        approved_scope_baselines_for("sample_provider", tmp_path)
    assert "conflicting approved_scope_baselines" in str(exc.value)


# ---------------------------------------------------------------------------
# 4. The returned shape is one compute_permission_findings accepts
# ---------------------------------------------------------------------------


def _grant(grant_id: str, scopes: list[str]) -> AuthorizationGrantRecord:
    return AuthorizationGrantRecord(
        grant_id=grant_id,
        tenant_id="tenant-1",
        provider_id="example_provider",
        agent_id="agent-1",
        scopes=scopes,
        granted_at="2026-01-01T00:00:00+00:00",
    )


def _action(scopes_used: list[str]) -> ProviderActionRecord:
    return ProviderActionRecord(
        action_id="action-1",
        provider_id="example_provider",
        agent_id="agent-1",
        action_type="observed",
        scopes_used=scopes_used,
        observed_at="2026-01-02T00:00:00+00:00",
    )


@pytest.mark.parametrize("provider_id", ["x_reference", "mcp", "example_provider"])
def test_baselines_are_accepted_by_compute_permission_findings(provider_id):
    baselines = approved_scope_baselines_for(provider_id)
    assert isinstance(baselines, dict)
    # Call it for real — the contract is "this argument works", not "this looks right".
    compute_permission_findings(
        tenant_id="tenant-1",
        grants=[_grant("grant-x", ["example.accounts.read"])],
        actions=[_action(["example.accounts.read"])],
        approved_scope_baselines=baselines,
    )


def test_baseline_keys_are_grant_ids_and_suppress_expected_scopes():
    """Proves the key semantics: the baseline is looked up by grant_id, and a grant
    inside its baseline produces no unexpected_new_scope finding."""
    baselines = approved_scope_baselines_for("example_provider")
    assert baselines, "the example pack must ship the one non-empty baseline"
    grant_id, approved = next(iter(sorted(baselines.items())))

    findings = compute_permission_findings(
        tenant_id="tenant-1",
        grants=[_grant(grant_id, list(approved))],
        actions=[_action(list(approved))],
        approved_scope_baselines=baselines,
    )
    assert [f for f in findings if f.finding_type == "unexpected_new_scope"] == []

    escalated = compute_permission_findings(
        tenant_id="tenant-1",
        grants=[_grant(grant_id, [*approved, "example.admin.write"])],
        actions=[_action(list(approved))],
        approved_scope_baselines=baselines,
    )
    unexpected = [f for f in escalated if f.finding_type == "unexpected_new_scope"]
    assert len(unexpected) == 1
    assert unexpected[0].scopes == ["example.admin.write"]


def test_unknown_provider_yields_empty_baselines_not_an_error():
    """Empty means every scope is reported for review — the safe direction — and is
    distinguishable from a broken load only because a broken load raises."""
    assert approved_scope_baselines_for("no_such_provider") == {}


def test_example_pack_scopes_never_leak_to_a_real_provider():
    example = get_reference_pack("example_provider")["approved_scope_baselines"]
    assert example
    for real_provider in ("x_reference", "mcp"):
        assert approved_scope_baselines_for(real_provider) == {}


# ---------------------------------------------------------------------------
# 5. The validator gate
# ---------------------------------------------------------------------------


def _run_validator(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_validator_exits_zero_on_the_real_pack_directory():
    result = _run_validator()
    assert result.returncode == 0, result.stdout + result.stderr


def test_validator_exits_non_zero_on_a_bad_fixture(tmp_path):
    _write_pack(tmp_path, "good_pack.yaml", _valid_pack("good_pack"))
    bad = _valid_pack("bad_pack", schema_version=99, provider_id="")
    _write_pack(tmp_path, "bad_pack.yaml", bad)

    result = _run_validator("--dir", str(tmp_path))
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "bad_pack.yaml" in output
    # Every violation is listed, not just the first.
    assert "schema_version" in output
    assert "provider_id" in output


def test_validator_reports_duplicate_pack_ids(tmp_path):
    _write_pack(tmp_path, "dup_pack.yaml", _valid_pack("dup_pack"))
    _write_pack(tmp_path, "dup_pack.yml", _valid_pack("dup_pack"))

    result = _run_validator("--dir", str(tmp_path))
    assert result.returncode != 0
    assert "duplicate pack_id" in result.stdout + result.stderr


def test_validator_fails_on_an_empty_directory(tmp_path):
    result = _run_validator("--dir", str(tmp_path))
    assert result.returncode != 0
    assert "no packs found" in result.stdout + result.stderr


def test_validator_does_not_mutate_the_pack_directory():
    before = {p.name: p.read_bytes() for p in PACK_DIR.iterdir() if p.is_file()}
    assert _run_validator().returncode == 0
    after = {p.name: p.read_bytes() for p in PACK_DIR.iterdir() if p.is_file()}
    assert before == after, "the validator must be read-only"
