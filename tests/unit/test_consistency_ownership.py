from __future__ import annotations

import json

from scripts import validate_consistency_ownership as ownership


def test_ownership_map_has_required_categories() -> None:
    data = json.loads(ownership.MAP_PATH.read_text(encoding="utf-8"))
    ids = {category["id"] for category in data["change_categories"]}
    assert {
        "canonical_version",
        "backend_routes",
        "event_schema",
        "consent_tenant_auth",
        "sdk_public_api",
        "package_public_type",
        "profile360",
        "kyber_operator",
        "generated_docs_source",
        "source_linked_docs",
        "workflow_check_command",
    } <= ids


def test_glob_negation_excludes_sync_managed_docs() -> None:
    patterns = ["docs/**/*.md", "!docs/REPO-INDEX.md", "!docs/AUTOMATION.md"]
    assert ownership._matches("docs/SDK-WEB.md", patterns)
    assert not ownership._matches("docs/REPO-INDEX.md", patterns)
    assert not ownership._matches("docs/AUTOMATION.md", patterns)


def test_release_train_categories_present() -> None:
    data = json.loads(ownership.MAP_PATH.read_text(encoding="utf-8"))
    ids = {category["id"] for category in data["change_categories"]}
    assert {"jobs_platform", "import_engine", "measurement_integrity"} <= ids


def test_all_required_commands_available() -> None:
    """Every declared validator/remediation command must be resolvable."""
    data = json.loads(ownership.MAP_PATH.read_text(encoding="utf-8"))
    for category in data["change_categories"]:
        for command in category.get("required_commands", []):
            assert ownership._command_available(command), (
                f"{category['id']}: command not available: {command}"
            )


def test_required_commands_are_available() -> None:
    assert ownership._command_available("python scripts/repo_doctor.py --check")
    assert ownership._command_available("make ci-check")
