from __future__ import annotations

import json
import sys

from scripts import validate_canonical_ingestion_trees as gate


def _load_registry() -> list[dict[str, str]]:
    data = json.loads(gate.REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return [entry for entry in data if isinstance(entry, dict) and entry.get("path")]


def test_registry_present_and_entries_well_formed() -> None:
    registry = _load_registry()
    assert registry, "repo_tree_ownership.json must be committed and non-empty"
    for entry in registry:
        assert entry["path"]
        assert entry["role"] in gate._VALID_ROLES, entry
        assert entry["owner"]
        assert entry["note"]
        if entry["role"] == "deprecated":
            assert entry["deprecated_at"], entry
            assert entry["disposition"], entry


def test_canonical_units_registered() -> None:
    paths = {entry["path"] for entry in _load_registry()}
    assert "services/backend" in paths
    assert "packages" in paths
    by_path = {entry["path"]: entry for entry in _load_registry()}
    assert by_path["services/backend"]["role"] == "canonical"
    assert by_path["packages"]["role"] == "canonical"


def test_deprecated_duplicate_stacks_registered() -> None:
    by_path = {entry["path"]: entry for entry in _load_registry()}
    for tree in (
        "docs/archive/legacy-architecture/data-ingestion-layer",
        "docs/archive/legacy-architecture/data-lake-architecture",
    ):
        assert by_path[tree]["role"] == "deprecated"
        assert tree in gate._DEPRECATED_ROOT_TREES


def test_agent_layer_role_is_registered_not_deployable() -> None:
    """The agent worker service is canonical internally, but not independently deployable."""
    by_path = {entry["path"]: entry for entry in _load_registry()}
    assert by_path["services/agents"]["role"] == "registered-not-deployable"


def test_orphan_modules_match_deprecation_enumeration() -> None:
    """The deprecated backend orphans mirror the Ticket C enumeration exactly."""
    by_path = {entry["path"]: entry for entry in _load_registry()}
    orphan_modules = {
        "auth.py",
        "cache.py",
        "common.py",
        "events.py",
        "graph.py",
        "limiter.py",
        "logger.py",
        "repos.py",
        "routes.py",
        "settings.py",
        "migrations",
        "mnt",
        "services/delegation",
        "services/journey-service",
        "services/web3",
    }
    expected = {f"docs/archive/legacy-architecture/backend/{m}" for m in orphan_modules}
    registered_orphans = {
        p for p, e in by_path.items() if p.startswith("docs/archive/legacy-architecture/backend/") and e["role"] == "deprecated"
    }
    assert registered_orphans == expected


def test_backend_orphan_unit_mapping_from_synthetic_files() -> None:
    files = {
        "docs/archive/legacy-architecture/backend/auth.py",
        "docs/archive/legacy-architecture/backend/migrations/2026_07_x.sql",
        "docs/archive/legacy-architecture/backend/mnt/user-data/out.txt",
        "docs/archive/legacy-architecture/backend/services/delegation/middleware.py",
        "docs/archive/legacy-architecture/backend/services/journey-service/main.py",
        "docs/archive/legacy-architecture/backend/services/web3/web3_service.py",
        "services/backend/services/ingestion/batch.py",
        "docs/archive/legacy-architecture/backend/README.md",
        "packages/web/src/index.ts",
    }
    units = gate._backend_orphan_units(files)
    assert units == {
        "docs/archive/legacy-architecture/backend/auth.py",
        "docs/archive/legacy-architecture/backend/migrations",
        "docs/archive/legacy-architecture/backend/mnt",
        "docs/archive/legacy-architecture/backend/services/delegation",
        "docs/archive/legacy-architecture/backend/services/journey-service",
        "docs/archive/legacy-architecture/backend/services/web3",
    }


def test_present_detects_registered_missing() -> None:
    files = {"packages/web/src/index.ts", "docs/README.md"}
    assert gate._present("packages", files)
    assert gate._present("docs", files)
    assert not gate._present("scripts", files)
    assert not gate._present("docs/archive/legacy-architecture/data-ingestion-layer", files)


def test_validate_mode_passes_against_live_tree(monkeypatch) -> None:
    """Default check mode must exit 0 while the registry matches the tree.

    gate.main() parses sys.argv (argparse), so isolate it from pytest's own
    argv — otherwise parse_args errors on the runner arguments.
    """
    monkeypatch.setattr(sys, "argv", ["validate_canonical_ingestion_trees"])
    assert gate.main() == 0


def test_registry_round_trips_through_seed() -> None:
    """build_registry must equal the committed registry (shrink-only contract)."""
    seeded = {entry["path"]: entry for entry in gate.build_registry()}
    committed = {entry["path"]: entry for entry in _load_registry()}
    assert seeded == committed, "run python scripts/validate_canonical_ingestion_trees.py --seed and review"
