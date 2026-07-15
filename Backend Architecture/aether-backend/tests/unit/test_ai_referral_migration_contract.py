"""Static migration/runtime parity for AI referral attribution extensions.

The migration is parsed as Python source so this contract remains runnable in
the lightweight unit-test environment where Alembic itself is optional.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from services.measurement.contracts import (
    AttributionCredit,
    AttributionRun,
    CanonicalActivity,
    CanonicalTouchpoint,
    JourneyStep,
)
from services.measurement.repositories.attribution_run_repo import (
    _CREDIT_COLUMNS,
    _RUN_MUTABLE_COLUMNS,
)
from services.measurement.repositories.touchpoint_repo import (
    _CLASSIFICATION_FIELDS,
    _TOUCHPOINT_COLUMNS,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260725_ai_referral_attribution.py"
)


def _migration_literals() -> dict[str, Any]:
    tree = ast.parse(MIGRATION_PATH.read_text(encoding="utf-8"))
    values: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            try:
                values[target.id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return values


def _added_columns(ddl: str) -> set[str]:
    return set(re.findall(r"ADD COLUMN IF NOT EXISTS\s+(\w+)", ddl))


TOUCHPOINT_DIMENSIONS = {
    "source_class",
    "referral_mediation_type",
    "ai_provider",
    "ai_product",
    "actor_type",
    "journey_role",
    "evidence_confidence",
    "verification_level",
    "source_classifier_version",
    "source_classified_at",
    "normalized_referrer_domain",
    "referrer_path_hash",
    "source_classification_evidence",
    "source_classification_id",
    "attribution_eligible",
    "verified_referral_link_id",
}

DOWNSTREAM_DIMENSIONS = {
    "source_class",
    "referral_mediation_type",
    "ai_provider",
    "ai_product",
    "journey_role",
    "evidence_confidence",
    "verification_level",
    "source_classifier_version",
    "normalized_referrer_domain",
    "source_classification_id",
    "attribution_eligible",
    "verified_referral_link_id",
}

CREDIT_DIMENSIONS = DOWNSTREAM_DIMENSIONS | {"actor_type"}


def test_migration_is_linear_extension_of_current_ingestion_head() -> None:
    values = _migration_literals()

    assert values["revision"] == "20260725_ai_referral_attribution"
    assert values["down_revision"] == "20260724_ingestion_v2"


def test_touchpoint_migration_and_runtime_repository_have_identical_dimensions() -> None:
    values = _migration_literals()

    assert _added_columns(values["TOUCHPOINT_CLASSIFICATION_COLUMNS_DDL"]) == (
        TOUCHPOINT_DIMENSIONS
    )
    assert TOUCHPOINT_DIMENSIONS <= set(_TOUCHPOINT_COLUMNS)
    assert TOUCHPOINT_DIMENSIONS <= set(CanonicalTouchpoint.model_fields)
    # The current-projection updater also includes the pre-existing display
    # fields channel/source/medium/referrer.
    assert TOUCHPOINT_DIMENSIONS <= set(_CLASSIFICATION_FIELDS)


def test_activity_journey_and_credit_dimensions_match_migration_and_models() -> None:
    values = _migration_literals()

    assert _added_columns(values["CANONICAL_ACTIVITY_COLUMNS_DDL"]) == (
        DOWNSTREAM_DIMENSIONS
    )
    assert _added_columns(values["JOURNEY_STEP_COLUMNS_DDL"]) == DOWNSTREAM_DIMENSIONS
    assert _added_columns(values["ATTRIBUTION_CREDIT_COLUMNS_DDL"]) == CREDIT_DIMENSIONS

    assert DOWNSTREAM_DIMENSIONS <= set(CanonicalActivity.model_fields)
    assert DOWNSTREAM_DIMENSIONS <= set(JourneyStep.model_fields)
    assert CREDIT_DIMENSIONS <= set(AttributionCredit.model_fields)
    assert CREDIT_DIMENSIONS <= set(_CREDIT_COLUMNS)


def test_attribution_run_recompute_lineage_matches_schema_repository_and_contract() -> None:
    values = _migration_literals()
    expected = {
        "trigger_reason",
        "source_classifier_version",
        "model_config_snapshot",
        "prior_attribution_run_id",
    }

    assert _added_columns(values["ATTRIBUTION_RUN_COLUMNS_DDL"]) == expected
    assert expected <= set(AttributionRun.model_fields)
    assert expected - {"model_config_snapshot"} <= set(_RUN_MUTABLE_COLUMNS)
    # A run's effective policy snapshot is immutable evidence captured at creation.
    assert "model_config_snapshot" not in _RUN_MUTABLE_COLUMNS
    assert "attribution_runs_prior_run_fk" in values["ATTRIBUTION_RUN_COLUMNS_DDL"]
    assert "FOREIGN KEY (tenant_id, prior_attribution_run_id)" in values[
        "ATTRIBUTION_RUN_COLUMNS_DDL"
    ]


def test_revision_ledger_is_append_only_replay_safe_and_tenant_linked() -> None:
    values = _migration_literals()
    ddl = values["TOUCHPOINT_CLASSIFICATION_REVISIONS_DDL"]
    indexes = "\n".join(values["INDEXES"])

    for field in (
        "classification_id",
        "tenant_id",
        "touchpoint_id",
        "classifier_version",
        "input_hash",
        "prior_classification",
        "classification",
        "evidence",
        "confidence",
        "verification_level",
        "reason",
        "job_id",
        "previous_classification_id",
        "superseded_by",
        "is_current",
        "classified_at",
    ):
        assert re.search(rf"\b{field}\b", ddl)
    assert "FOREIGN KEY (tenant_id, touchpoint_id)" in ddl
    assert "ux_tsc_revisions_replay" in indexes
    assert "(tenant_id, touchpoint_id, classifier_version, input_hash)" in indexes
    assert "ux_tsc_revisions_current" in indexes
    assert "WHERE is_current IS TRUE" in indexes


def test_repair_checkpoint_and_verified_link_schema_match_runtime_security_contract() -> None:
    values = _migration_literals()
    repair_ddl = values["SOURCE_CLASSIFICATION_REPAIR_RUNS_DDL"]
    link_ddl = values["VERIFIED_REFERRAL_LINKS_DDL"]

    for field in (
        "run_id",
        "tenant_id",
        "job_id",
        "target_classifier_version",
        "status",
        "phase",
        "filters",
        "cursor_occurred_at",
        "cursor_touchpoint_id",
        "counters",
        "errors",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    ):
        assert re.search(rf"\b{field}\b", repair_ddl)
    assert (
        "FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id)"
        in repair_ddl
    )
    assert "UNIQUE (tenant_id, id)" in values["JOBS_TENANT_REFERENCE_KEY_DDL"]

    assert re.search(r"\btoken_hash\s+TEXT\s+NOT NULL", link_ddl)
    assert not re.search(r"\btoken\s+TEXT", link_ddl)
    assert "UNIQUE (token_hash)" in link_ddl
    assert "UNIQUE (tenant_id, verified_referral_link_id)" in link_ddl


def test_active_attribution_recompute_is_deduplicated_before_unique_index() -> None:
    values = _migration_literals()
    dedupe = values["DEDUPLICATE_ACTIVE_ATTRIBUTION_RUNS_DDL"]
    indexes = "\n".join(values["INDEXES"])

    assert "ROW_NUMBER() OVER" in dedupe
    assert "PARTITION BY tenant_id, conversion_id" in dedupe
    assert "SET is_active = FALSE" in dedupe
    assert "ux_attribution_runs_active_conversion" in indexes
    assert "(tenant_id, conversion_id) WHERE is_active IS TRUE" in indexes
