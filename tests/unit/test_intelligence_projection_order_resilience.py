"""Intelligence Projection order-resilience tests (P0.8, group 10).

The user's two hard requirements, proven mechanically:

- **Skip-ahead**: a later projection may declare a projection dependency on an
  earlier projection that is not yet implemented — WITH a declared pending
  entry it is legal; WITHOUT it errors; once the earlier projection lands the
  pending declaration is dangling and errors ("remove it").
- **Tetris**: generated artifacts are order-stable — reordering registry rows /
  shuffling key order yields byte-identical output; removing one projection
  changes ONLY that projection's blocks; adding a new pending projection never
  disturbs the placed (existing) rows.

Also proves the "implemented cannot lie" positive: an implemented projection
with zero pending and converged bindings passes the dependency-DAG gate.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.intelligence_projection_validation import validate_dependency_dag  # noqa: E402
from scripts.generate_platform_contracts import (  # noqa: E402
    gen_intelligence_projection_py,
    gen_intelligence_projection_ts,
)

_REGISTRY_JSON = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "intelligence-projection-registry.json"
)

_EXISTING_IDS = (
    "profile360", "agent360", "relationship360", "social360", "episode360",
    "communication360", "execution360", "temporal360", "geographic360",
    "population360", "cluster360", "outcome360", "economic360", "campaign360",
    "risk360", "fraud360", "source360", "connection360",
)


def _real_registry() -> dict:
    return json.loads(_REGISTRY_JSON.read_text(encoding="utf-8"))


# --- skip-ahead fixtures ----------------------------------------------------


def _mk_dag_reg(entries: list[dict]) -> dict:
    return {
        "schemaVersion": "1.0.0",
        "contractVersion": "1.0.0",
        "projections": entries,
    }


def _dag_entry(
    pid: str,
    deps: list[str] | None = None,
    state: str = "in_flight",
    pending_auth: list[dict] | None = None,
    pending_ref: list[dict] | None = None,
) -> dict:
    return {
        "id": pid,
        "implementationState": state,
        "projectionDependencies": deps or [],
        "optionalProjectionDependencies": [],
        "pendingAuthority": pending_auth or [],
        "pendingReference": pending_ref or [],
    }


def _pending_projection_decl(target: str, projection: str) -> dict:
    return {
        "id": target,
        "kind": "projection",
        "reason": "skip-ahead: earlier projection not yet implemented",
        "resolvesInProjection": projection,
    }


def test_skip_ahead_with_declared_pending_ok() -> None:
    # cluster360-style "later" projection depends on a population360-style
    # "earlier" projection that is NOT yet implemented; the dependency is
    # declared pending (kind:"projection") → legal.
    pending = _pending_projection_decl("population360", "cluster360")
    reg = _mk_dag_reg([_dag_entry("cluster360", deps=["population360"], pending_auth=[pending])])
    assert validate_dependency_dag(reg) == []


def test_skip_ahead_without_pending_reported() -> None:
    # Same skip-ahead, but the dependency is NOT declared pending → fail-closed.
    reg = _mk_dag_reg([_dag_entry("cluster360", deps=["population360"])])
    violations = validate_dependency_dag(reg)
    assert any(
        v.severity == "error"
        and "neither a registry id nor declared pending" in v.message
        and "population360" in v.message
        for v in violations
    )


def test_skip_ahead_dangling_pending_when_target_lands_reported() -> None:
    # population360 now EXISTS (implemented), but cluster360 still carries a
    # pending declaration for it → dangling declaration error ("remove it").
    pending = _pending_projection_decl("population360", "cluster360")
    reg = _mk_dag_reg(
        [
            _dag_entry("population360", state="implemented"),
            _dag_entry("cluster360", deps=["population360"], pending_auth=[pending]),
        ]
    )
    violations = validate_dependency_dag(reg)
    errors = [v for v in violations if v.severity == "error"]
    assert any(
        v.rule == "order_resilience"
        and "dangling pending projection" in v.message
        and "population360" in v.message
        for v in errors
    )


# --- order-stable generation (tetris proofs) --------------------------------


def _reverse_keys(obj: object) -> object:
    """Deep-copy an object with every dict's key order reversed (shuffle)."""
    if isinstance(obj, dict):
        return {k: _reverse_keys(v) for k, v in reversed(list(obj.items()))}
    if isinstance(obj, list):
        return [_reverse_keys(v) for v in obj]
    return obj


def _shuffled_copy(reg: dict) -> dict:
    """A registry copy with the projections array order AND every object's key
    order shuffled. Emitters must normalize both (sort by id + fixed field
    order) so the output is byte-identical."""
    shuffled = copy.deepcopy(reg)
    shuffled["projections"] = list(reversed(shuffled["projections"]))
    return _reverse_keys(shuffled)  # type: ignore[return-value]


def test_row_reorder_and_key_shuffle_byte_identical_ts() -> None:
    reg = _real_registry()
    shuffled = _shuffled_copy(reg)
    assert gen_intelligence_projection_ts(reg) == gen_intelligence_projection_ts(shuffled)


def test_row_reorder_and_key_shuffle_byte_identical_py() -> None:
    reg = _real_registry()
    shuffled = _shuffled_copy(reg)
    assert gen_intelligence_projection_py(reg) == gen_intelligence_projection_py(shuffled)


def _ts_per_id_sections(text: str) -> dict[str, dict[str, list[str]]]:
    """Split generated TS into per-projection-id line blocks per section.

    Sections carrying per-id entries: intelligenceProjectionDefinitions,
    projectionDependencyGraph, pendingAuthorities, pendingReferences. A block
    runs from its 2-space-indented ``  <id>:`` key line through the matching
    2-space-indented closer (``  },`` for object literals, ``  ],`` for pending
    list literals; dependency-graph entries are single lines).
    """
    sections: dict[str, dict[str, list[str]]] = {}
    lines = text.splitlines()
    section: str | None = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line == "};":
            section = None
        elif line.startswith("export const intelligenceProjectionDefinitions"):
            section = "definitions"
        elif line.startswith("export const projectionDependencyGraph"):
            section = "depgraph"
        elif line.startswith("export const pendingAuthorities"):
            section = "pending_authority"
        elif line.startswith("export const pendingReferences"):
            section = "pending_reference"
        elif section is not None and re.match(r"^  [a-z0-9_]+:", line):
            pid = line.split(":", 1)[0].strip()
            if section == "depgraph":
                sections.setdefault(section, {})[pid] = [line]
                i += 1
                continue
            block = [line]
            i += 1
            while i < n:
                cur = lines[i]
                block.append(cur)
                if cur in ("  },", "  ],"):
                    i += 1
                    break
                i += 1
            sections.setdefault(section, {})[pid] = block
            continue
        i += 1
    return sections


def _per_id_blocks(text: str) -> dict[str, dict[str, list[str]]]:
    """Flatten section blocks into {projection_id: {section: [lines]}}."""
    out: dict[str, dict[str, list[str]]] = {}
    for section, mapping in _ts_per_id_sections(text).items():
        for pid, lines in mapping.items():
            out.setdefault(pid, {})[section] = lines
    return out


def test_one_entry_removal_localized_diff() -> None:
    # Removing campaign360 changes ONLY campaign360's blocks; every other
    # projection's per-id block (definitions, dependency graph, pending maps)
    # stays byte-identical. (No other projection depends on campaign360.)
    reg = _real_registry()
    removed = copy.deepcopy(reg)
    removed["projections"] = [p for p in removed["projections"] if p["id"] != "campaign360"]
    assert len(removed["projections"]) == 17

    full_blocks = _per_id_blocks(gen_intelligence_projection_ts(reg))
    removed_blocks = _per_id_blocks(gen_intelligence_projection_ts(removed))

    differing = {
        pid
        for pid in set(full_blocks) | set(removed_blocks)
        if full_blocks.get(pid) != removed_blocks.get(pid)
    }
    assert differing == {"campaign360"}, differing


def test_adding_pending_projection_keeps_existing_blocks_identical() -> None:
    # A follow-up blueprint adds a NEW projection (registered, with pending
    # surface + metric refs). None of the 18 existing projections' blocks move:
    # new work drops into place without disturbing placed pieces (tetris).
    reg = _real_registry()
    plus = copy.deepcopy(reg)
    plus["projections"].append(_new_registered_projection())
    assert len(plus["projections"]) == 19

    base_blocks = _per_id_blocks(gen_intelligence_projection_ts(reg))
    plus_blocks = _per_id_blocks(gen_intelligence_projection_ts(plus))

    for pid in _EXISTING_IDS:
        assert base_blocks.get(pid) == plus_blocks.get(pid), f"placed block for {pid} drifted"
    assert "audience360" in plus_blocks


def _new_registered_projection() -> dict:
    """A realistic follow-up projection: registered, with pending refs."""
    return {
        "id": "audience360",
        "displayName": "Audience 360",
        "projectionKind": "operational_workbench",
        "implementationState": "registered",
        "implementationBlueprint": "docs/blueprints/audience360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ["population", "entity"],
        "canonicalAuthorities": ["population", "graph"],
        "hardDependencies": ["contract_spine", "identity_resolution"],
        "projectionDependencies": ["population360", "cluster360"],
        "optionalProjectionDependencies": [],
        "inputRefs": ["EntityRef", "GraphSnapshotRef"],
        "outputSections": ["summary", "state"],
        "supportedTemporalModes": ["window", "relative"],
        "surfaceIds": ["audience_workbench"],
        "capabilityKeys": ["audience360.read", "audience360.explore"],
        "metricRefs": ["audience_reach"],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": False,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True,
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "high",
        },
        "costProfile": {"class": "moderate", "supportsAsync": False},
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": [],
        },
        "legacyBindings": {
            "routes": [],
            "surfaceIds": ["audience_workbench"],
            "services": [],
            "migrationMode": "none",
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": [
            {
                "id": "audience_workbench",
                "kind": "surface",
                "reason": "audience workbench surface not yet in the surface registry",
                "resolvesInProjection": "audience360",
            },
            {
                "id": "audience_reach",
                "kind": "metric",
                "reason": "audience reach metric not yet in metric-registry.json",
                "resolvesInProjection": "audience360",
            },
        ],
    }


# --- implemented cannot lie (positive) --------------------------------------


def test_implemented_zero_pending_converged_dag_ok() -> None:
    reg = _mk_dag_reg(
        [
            {
                "id": "a",
                "implementationState": "implemented",
                "projectionDependencies": [],
                "optionalProjectionDependencies": [],
                "pendingAuthority": [],
                "pendingReference": [],
                "legacyBindings": {
                    "routes": [],
                    "surfaceIds": [],
                    "services": [],
                    "migrationMode": "converged",
                },
            }
        ]
    )
    assert validate_dependency_dag(reg) == []
