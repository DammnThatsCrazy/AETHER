from __future__ import annotations

import json

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
    assert "Backend Architecture/aether-backend" in paths
    assert "packages" in paths
    by_path = {entry["path"]: entry for entry in _load_registry()}
    assert by_path["Backend Architecture/aether-backend"]["role"] == "canonical"
    assert by_path["packages"]["role"] == "canonical"


def test_deprecated_duplicate_stacks_registered() -> None:
    by_path = {entry["path"]: entry for entry in _load_registry()}
    for tree in ("Data Ingestion Layer", "Data Lake Architecture"):
        assert by_path[tree]["role"] == "deprecated"
        assert tree in gate._DEPRECATED_ROOT_TREES


def test_agent_layer_role_is_registered_not_deployable() -> None:
    """Agent Layer is live broker-coupled workers: never canonical/deprecated."""
    by_path = {entry["path"]: entry for entry in _load_registry()}
    assert by_path["Agent Layer"]["role"] == "registered-not-deployable"


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
    expected = {f"Backend Architecture/{m}" for m in orphan_modules}
    registered_orphans = {
        p for p, e in by_path.items() if p.startswith("Backend Architecture/") and e["role"] == "deprecated"
    }
    assert registered_orphans == expected


def test_backend_orphan_unit_mapping_from_synthetic_files() -> None:
    files = {
        "Backend Architecture/auth.py",
        "Backend Architecture/migrations/2026_07_x.sql",
        "Backend Architecture/mnt/user-data/out.txt",
        "Backend Architecture/services/delegation/middleware.py",
        "Backend Architecture/services/journey-service/main.py",
        "Backend Architecture/services/web3/web3_service.py",
        "Backend Architecture/aether-backend/services/ingestion/batch.py",
        "Backend Architecture/README.md",
        "packages/web/src/index.ts",
    }
    units = gate._backend_orphan_units(files)
    assert units == {
        "Backend Architecture/auth.py",
        "Backend Architecture/migrations",
        "Backend Architecture/mnt",
        "Backend Architecture/services/delegation",
        "Backend Architecture/services/journey-service",
        "Backend Architecture/services/web3",
    }


def test_present_detects_registered_missing() -> None:
    files = {"packages/web/src/index.ts", "docs/README.md"}
    assert gate._present("packages", files)
    assert gate._present("docs", files)
    assert not gate._present("scripts", files)
    assert not gate._present("Data Ingestion Layer", files)


def test_validate_mode_passes_against_live_tree() -> None:
    """Default check mode must exit 0 while the registry matches the tree."""
    assert gate.main() == 0


def test_registry_round_trips_through_seed() -> None:
    """build_registry must equal the committed registry (shrink-only contract)."""
    seeded = {entry["path"]: entry for entry in gate.build_registry()}
    committed = {entry["path"]: entry for entry in _load_registry()}
    assert seeded == committed, "run python scripts/validate_canonical_ingestion_trees.py --seed and review"
