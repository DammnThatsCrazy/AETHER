"""Static contract checks for the AI-referral attribution migration."""

from __future__ import annotations

import ast
import re
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "Backend Architecture"
    / "aether-backend"
    / "alembic"
    / "versions"
    / "20260725_ai_referral_attribution.py"
)


def _source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _ddl(name: str) -> str:
    match = re.search(rf'{name} = """\n(.*?)"""', _source(), re.DOTALL)
    assert match, f"missing DDL constant {name}"
    return match.group(1)


def _assignment(name: str) -> str:
    tree = ast.parse(_source())
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            assert isinstance(node.value, ast.Constant)
            return str(node.value.value)
    raise AssertionError(f"missing assignment {name}")


def test_ai_referral_migration_extends_current_head() -> None:
    assert _assignment("revision") == "20260725_ai_referral_attribution"
    assert _assignment("down_revision") == "20260724_ingestion_v2"


def test_touchpoint_projection_contains_required_classification_dimensions() -> None:
    ddl = _ddl("TOUCHPOINT_CLASSIFICATION_COLUMNS_DDL")
    required = {
        "source_class TEXT",
        "referral_mediation_type TEXT",
        "ai_provider TEXT",
        "ai_product TEXT",
        "actor_type TEXT",
        "journey_role TEXT",
        "evidence_confidence NUMERIC(5,4)",
        "verification_level TEXT",
        "source_classifier_version TEXT",
        "source_classified_at TIMESTAMPTZ",
        "normalized_referrer_domain TEXT",
        "referrer_path_hash TEXT",
        "source_classification_evidence JSONB",
        "source_classification_id UUID",
        "attribution_eligible BOOLEAN",
        "verified_referral_link_id UUID",
    }
    assert all(column in ddl for column in required)


def test_revision_and_repair_checkpoint_contracts_match_runtime_identifiers() -> None:
    revisions = _ddl("TOUCHPOINT_CLASSIFICATION_REVISIONS_DDL")
    for column in (
        "classification_id UUID",
        "tenant_id TEXT",
        "touchpoint_id UUID",
        "classifier_version TEXT",
        "input_hash TEXT",
        "prior_classification JSONB",
        "classification JSONB",
        "evidence JSONB",
        "confidence NUMERIC(5,4)",
        "verification_level TEXT",
        "reason TEXT",
        "job_id TEXT",
        "previous_classification_id UUID",
        "superseded_by UUID",
        "is_current BOOLEAN",
        "classified_at TIMESTAMPTZ",
    ):
        assert column in revisions

    repair_runs = _ddl("SOURCE_CLASSIFICATION_REPAIR_RUNS_DDL")
    for column in (
        "run_id UUID",
        "tenant_id TEXT",
        "job_id TEXT",
        "target_classifier_version TEXT",
        "status TEXT",
        "phase TEXT",
        "filters JSONB",
        "cursor_occurred_at TIMESTAMPTZ",
        "cursor_touchpoint_id UUID",
        "counters JSONB",
        "errors JSONB",
        "started_at TIMESTAMPTZ",
        "completed_at TIMESTAMPTZ",
        "created_at TIMESTAMPTZ",
        "updated_at TIMESTAMPTZ",
    ):
        assert column in repair_runs

    source = _source()
    assert "(tenant_id, touchpoint_id, classifier_version, input_hash)" in source
    assert "WHERE is_current IS TRUE" in source


def test_journey_and_attribution_surfaces_receive_classification_snapshots() -> None:
    query_dimensions = (
        "source_class TEXT",
        "referral_mediation_type TEXT",
        "ai_provider TEXT",
        "ai_product TEXT",
        "journey_role TEXT",
        "evidence_confidence NUMERIC(5,4)",
        "verification_level TEXT",
        "source_classifier_version TEXT",
        "normalized_referrer_domain TEXT",
        "source_classification_id UUID",
        "attribution_eligible BOOLEAN",
        "verified_referral_link_id UUID",
    )
    for ddl_name in ("CANONICAL_ACTIVITY_COLUMNS_DDL", "JOURNEY_STEP_COLUMNS_DDL"):
        ddl = _ddl(ddl_name)
        assert all(column in ddl for column in query_dimensions)

    credits = _ddl("ATTRIBUTION_CREDIT_COLUMNS_DDL")
    assert all(column in credits for column in (*query_dimensions, "actor_type TEXT"))
    assert "excluded_source_noise_count INTEGER" in _ddl("JOURNEY_VERSION_COLUMNS_DDL")

    runs = _ddl("ATTRIBUTION_RUN_COLUMNS_DDL")
    assert "trigger_reason TEXT" in runs
    assert "source_classifier_version TEXT" in runs
    assert "prior_attribution_run_id UUID" in runs


def test_verified_links_persist_only_a_token_hash() -> None:
    ddl = _ddl("VERIFIED_REFERRAL_LINKS_DDL")
    assert "token_hash TEXT NOT NULL" in ddl
    assert "UNIQUE (token_hash)" in ddl
    assert "plaintext" not in ddl.lower()
    assert "raw_token" not in ddl.lower()
    assert " ai_provider TEXT" in ddl
    assert " campaign_id TEXT" in ddl


def test_active_attribution_runs_are_deduplicated_before_unique_index() -> None:
    dedupe = _ddl("DEDUPLICATE_ACTIVE_ATTRIBUTION_RUNS_DDL")
    source = _source()
    upgrade = source[source.index("def upgrade()") : source.index("_INDEX_NAMES =")]
    assert "PARTITION BY tenant_id, conversion_id" in dedupe
    assert "created_at DESC" in dedupe
    assert "SET is_active = FALSE" in dedupe
    assert upgrade.index("op.execute(DEDUPLICATE_ACTIVE_ATTRIBUTION_RUNS_DDL)") < upgrade.index(
        "for index_ddl in INDEXES"
    )
    assert "ON attribution_runs (tenant_id, conversion_id) WHERE is_active IS TRUE" in source


def test_downgrade_is_explicit_and_non_cascading() -> None:
    source = _source()
    downgrade = source[source.index("def downgrade()") :]
    assert "DROP TABLE IF EXISTS touchpoint_source_classification_revisions" in downgrade
    assert "DROP TABLE IF EXISTS source_classification_repair_runs" in downgrade
    assert "DROP TABLE IF EXISTS verified_referral_links" in downgrade
    assert (
        "DROP TABLE IF EXISTS touchpoint_source_classification_revisions CASCADE"
        not in downgrade
    )
    assert "DROP TABLE IF EXISTS source_classification_repair_runs CASCADE" not in downgrade
    assert "DROP TABLE IF EXISTS verified_referral_links CASCADE" not in downgrade
