from __future__ import annotations

import json

from scripts import validate_sdk_import_boundary as gate


def _load_allowlist() -> list[str]:
    data = json.loads(gate.ALLOWLIST.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return [entry for entry in data if isinstance(entry, str)]


def test_allowlist_seeded_empty() -> None:
    """SDK surfaces scan clean today, so the committed allowlist is empty."""
    assert _load_allowlist() == []


def test_forbidden_internal_targets_derived_from_legacy_trees() -> None:
    targets = gate.forbidden_internal_targets()
    # Duplicate-stack root package names (Data Ingestion Layer root is literally
    # "aether-backend"; Data Lake root is "aether-datalake-backend").
    assert "aether-backend" in targets
    assert "aether-datalake-backend" in targets
    # Scoped internal subpackages in both legacy stacks.
    for name in ("@aether/logger", "@aether/cache", "@aether/auth", "@aether/events",
                 "@aether/ingestion", "@aether/data-lake"):
        assert name in targets, name


def test_target_is_internal_detects_legacy_scoped_and_root_names() -> None:
    forbidden = {"@aether/ingestion", "aether-backend", "aether-datalake-backend"}
    assert gate._target_is_internal("@aether/ingestion", forbidden)
    assert gate._target_is_internal("@aether/ingestion/outbox", forbidden)
    assert gate._target_is_internal("aether-backend", forbidden)
    assert gate._target_is_internal("aether-datalake-backend", forbidden)
    assert not gate._target_is_internal("@aether/shared", forbidden)
    assert not gate._target_is_internal("react", forbidden)
    assert not gate._target_is_internal("node:path", forbidden)


def test_allowed_sibling_sdk_specifiers_are_permitted() -> None:
    for spec in ("@aether/shared", "@aether/shared/consent", "@aether/web",
                 "@aether/react-native", "@aether/mobile-core", "@aether/mobile-ui",
                 "@aether/server"):
        assert gate._is_allowed_bare(spec), spec
    assert gate._is_relative("./base-tracker")
    assert gate._is_relative("../../../shared/events")


def test_ts_scan_flags_internal_import_and_ignores_relative(tmp_path) -> None:
    source = tmp_path / "sdk.ts"
    source.write_text(
        'import { tracker } from "./base-tracker";\n'
        'import type { T } from "@aether/shared";\n'
        'const x = require("aether-backend");\n'
        'void import("@aether/logger").catch(() => {});\n',
        encoding="utf-8",
    )
    offenders = gate._scan_file(source, "packages/web/src/sdk.ts", {"aether-backend", "@aether/logger"})
    kinds = [o.split(": ", 1)[1] for o in offenders]
    assert any("aether-backend" in k for k in kinds)
    assert any("@aether/logger" in k for k in kinds)
    # The relative and allowed @aether/shared imports must not be offenders.
    assert not any("base-tracker" in k for k in kinds)
    assert not any("@aether/shared" in k for k in kinds)


def test_package_deps_scan_flags_internal_dependency(tmp_path) -> None:
    pkg = tmp_path / "package.json"
    pkg.write_text(
        json.dumps({"name": "@aether/web", "dependencies": {"@aether/ingestion": "^1.0.0"}}),
        encoding="utf-8",
    )
    offenders = gate._scan_package_deps(str(pkg), {"@aether/ingestion"})
    assert any("@aether/ingestion" in o for o in offenders)


def test_validate_mode_passes_against_live_tree() -> None:
    """Default check mode must exit 0 while today's SDK surfaces scan clean."""
    assert gate.main() == 0


def test_scan_is_empty_for_current_sdk_surfaces() -> None:
    """SDK thinness holds today — no surface references an internal target."""
    assert gate.scan() == set()
