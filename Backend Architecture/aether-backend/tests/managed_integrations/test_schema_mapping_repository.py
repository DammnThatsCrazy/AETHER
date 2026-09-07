"""DB-free tests for the Reconciled Control Plane schema-mapping stores (Phase 3).

Exercises ``MappingCandidateRepository`` and ``SchemaMappingRunRepository``
(both in ``services/managed_integrations/schema_mapping_repository.py``) over
the module-local in-memory fallback with ``get_pool`` pinned to None — the
same pattern as ``test_execution_records_repository.py``.

The in-memory path is the unit-test reference: it mirrors the SQL path's
tenancy WHERE clauses and the vocabularies the module enforces. Vocabularies
the module checks (candidate ``mapping_method`` + ``review_state`` over the
§8.1 values at ``create``, ``review_state`` filters on ``list``) are asserted
exactly; the confidence→review-state *policy* that chooses the state lives in
the ``schema_mapping`` engine, so this file stores whatever state a caller
supplies and only rejects non-vocabulary values.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.managed_integrations.schema_mapping_repository import (  # noqa: E402
    MappingCandidateRow,
    SchemaMappingRunRow,
    get_mapping_candidate_repository,
    get_schema_mapping_run_repository,
    reset_schema_mapping_stores,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENV_1 = "env-1"
ENV_2 = "env-2"
INTEGRATION = "mi-sdk-1"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr(
        "services.managed_integrations.schema_mapping_repository.get_pool",
        _no_pool,
    )
    reset_schema_mapping_stores()
    yield
    reset_schema_mapping_stores()


def _json_ts(dt: datetime) -> str:
    """Timestamp string ``model_dump(mode="json")`` renders (trailing Z)."""
    return dt.isoformat().replace("+00:00", "Z")


def _candidate(**overrides: Any) -> MappingCandidateRow:
    base: dict[str, Any] = dict(
        candidate_id="rcsmc_a",
        source_ref="src/checkout@v2",
        source_path="checkout.order.total",
        canonical_target="canonical/commerce/order.total",
        mapping_method="heuristic",
        confidence=0.99,
        rationale="decimal precision widened to match canonical",
        sensitivity_class=None,
        transform_ref="transform/round-decimal",
        review_state="auto_propose",
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        created_at=NOW,
    )
    base.update(overrides)
    return MappingCandidateRow(**base)


def _run(**overrides: Any) -> SchemaMappingRunRow:
    base: dict[str, Any] = dict(
        run_id="smrun_1",
        managed_integration_ref=INTEGRATION,
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        observed_schema_fingerprint="fp-observed-v2",
        desired_schema_fingerprint="fp-observed-v2",
        diff_summary={"changed_fields": ["order.total.precision"]},
        candidate_ids=["rcsmc_a"],
        gate_results={
            "high_confidence": True,
            "no_new_data_category": True,
            "no_new_sensitive_field": True,
            "no_new_processing_purpose": True,
            "no_new_platform_provider_permission": True,
            "no_material_semantic_loss": True,
            "shadow_result_passes": True,
            "health_within_gates": True,
        },
        promoted=True,
        action_required_ref=None,
        created_at=NOW,
    )
    base.update(overrides)
    return SchemaMappingRunRow(**base)


# ── §8.1 mapping candidates ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_candidate_create_get_round_trip_preserves_every_field() -> None:
    repo = get_mapping_candidate_repository()
    created = await repo.create(_candidate())
    assert created["candidate_id"] == "rcsmc_a"
    assert created["source_ref"] == "src/checkout@v2"
    assert created["source_path"] == "checkout.order.total"
    assert created["canonical_target"] == "canonical/commerce/order.total"
    assert created["mapping_method"] == "heuristic"
    assert created["confidence"] == 0.99
    assert created["rationale"] == "decimal precision widened to match canonical"
    assert created["sensitivity_class"] is None
    assert created["transform_ref"] == "transform/round-decimal"
    assert created["review_state"] == "auto_propose"
    assert created["tenant_id"] == TENANT_A
    assert created["environment_id"] == ENV_1
    assert created["created_at"] == _json_ts(NOW)

    row = await repo.get(TENANT_A, ENV_1, "rcsmc_a")
    assert row is not None
    assert row["source_path"] == "checkout.order.total"
    assert row["mapping_method"] == "heuristic"
    assert row["confidence"] == 0.99
    assert row["review_state"] == "auto_propose"
    assert row["rationale"] == "decimal precision widened to match canonical"
    assert row["transform_ref"] == "transform/round-decimal"


@pytest.mark.asyncio
async def test_candidate_create_enforces_s81_vocabularies() -> None:
    repo = get_mapping_candidate_repository()
    with pytest.raises(ValueError, match="§8.1"):
        await repo.create(_candidate(mapping_method="guessed"))
    with pytest.raises(ValueError, match="§8.1"):
        await repo.create(_candidate(review_state="approved_anyway"))
    # Nothing was stored by the rejected creates.
    assert await repo.get(TENANT_A, ENV_1, "rcsmc_a") is None


@pytest.mark.asyncio
async def test_candidate_create_accepts_every_s81_vocabulary_value() -> None:
    repo = get_mapping_candidate_repository()
    for method in ("static", "provider_known", "heuristic", "model_assisted",
                   "human"):
        created = await repo.create(
            _candidate(candidate_id=f"rcsmc_{method}", mapping_method=method)
        )
        assert created["mapping_method"] == method
    for state in ("auto_propose", "review", "unresolved"):
        created = await repo.create(
            _candidate(
                candidate_id=f"rcsmc_state_{state}",
                review_state=state,
                confidence=0.9,
            )
        )
        assert created["review_state"] == state


@pytest.mark.asyncio
async def test_candidate_list_filters_and_orders_newest_created() -> None:
    repo = get_mapping_candidate_repository()
    await repo.create(
        _candidate(candidate_id="rcsmc_a", created_at=NOW)
    )
    await repo.create(
        _candidate(
            candidate_id="rcsmc_late",
            review_state="review",
            confidence=0.85,
            created_at=NOW.replace(minute=2),
        )
    )
    await repo.create(
        _candidate(
            candidate_id="rcsmc_mid",
            review_state="unresolved",
            confidence=0.4,
            sensitivity_class="pii",
            created_at=NOW.replace(minute=1),
        )
    )
    await repo.create(
        _candidate(
            candidate_id="rcsmc_tenant_b",
            tenant_id=TENANT_B,
            created_at=NOW.replace(minute=3),
        )
    )
    await repo.create(
        _candidate(
            candidate_id="rcsmc_other_env",
            environment_id=ENV_2,
            created_at=NOW.replace(minute=4),
        )
    )

    rows = await repo.list(tenant_id=TENANT_A, environment_id=ENV_1)
    # Newest-created first; other tenant/env rows never leak in.
    assert [r["candidate_id"] for r in rows] == [
        "rcsmc_late",
        "rcsmc_mid",
        "rcsmc_a",
    ]
    assert rows[0]["created_at"] == _json_ts(NOW.replace(minute=2))

    review = await repo.list(
        tenant_id=TENANT_A, environment_id=ENV_1, review_state="review"
    )
    assert [r["candidate_id"] for r in review] == ["rcsmc_late"]
    assert review[0]["confidence"] == 0.85
    unresolved = await repo.list(
        tenant_id=TENANT_A, environment_id=ENV_1, review_state="unresolved"
    )
    assert [r["candidate_id"] for r in unresolved] == ["rcsmc_mid"]
    assert unresolved[0]["sensitivity_class"] == "pii"

    limited = await repo.list(
        tenant_id=TENANT_A, environment_id=ENV_1, limit=2
    )
    assert [r["candidate_id"] for r in limited] == ["rcsmc_late", "rcsmc_mid"]

    unfiltered = await repo.list()
    assert len(unfiltered) == 5
    assert unfiltered[0]["candidate_id"] == "rcsmc_other_env"


@pytest.mark.asyncio
async def test_candidate_list_review_state_filter_enforces_s81_vocabulary() -> None:
    repo = get_mapping_candidate_repository()
    with pytest.raises(ValueError, match="§8.1"):
        await repo.list(review_state="not_a_review_state")


@pytest.mark.asyncio
async def test_candidate_list_for_source_is_scoped_and_newest_first() -> None:
    repo = get_mapping_candidate_repository()
    await repo.create(
        _candidate(
            candidate_id="rcsmc_a",
            source_ref="src/checkout@v2",
            created_at=NOW,
        )
    )
    await repo.create(
        _candidate(
            candidate_id="rcsmc_late",
            source_ref="src/checkout@v2",
            created_at=NOW.replace(minute=2),
        )
    )
    await repo.create(
        _candidate(
            candidate_id="rcsmc_other_source",
            source_ref="src/identity@v1",
            created_at=NOW.replace(minute=3),
        )
    )
    await repo.create(
        _candidate(
            candidate_id="rcsmc_tenant_b",
            tenant_id=TENANT_B,
            source_ref="src/checkout@v2",
            created_at=NOW.replace(minute=4),
        )
    )

    rows = await repo.list_for_source(
        tenant_id=TENANT_A, environment_id=ENV_1, source_ref="src/checkout@v2"
    )
    assert [r["candidate_id"] for r in rows] == ["rcsmc_late", "rcsmc_a"]
    other = await repo.list_for_source(
        tenant_id=TENANT_A, environment_id=ENV_1, source_ref="src/identity@v1"
    )
    assert [r["candidate_id"] for r in other] == ["rcsmc_other_source"]
    # Tenant A's checkout-source list above contained exactly its two rows —
    # tenant B's same-source row never leaked across the scope. Tenant B sees
    # its own row under its own scope, and an absent source is empty.
    tenant_b_rows = await repo.list_for_source(
        tenant_id=TENANT_B, environment_id=ENV_1, source_ref="src/checkout@v2"
    )
    assert [r["candidate_id"] for r in tenant_b_rows] == ["rcsmc_tenant_b"]
    assert (
        await repo.list_for_source(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            source_ref="src/never_registered",
        )
        == []
    )


@pytest.mark.asyncio
async def test_candidate_get_refuses_cross_tenant_and_cross_env() -> None:
    repo = get_mapping_candidate_repository()
    await repo.create(_candidate())
    assert await repo.get(TENANT_B, ENV_1, "rcsmc_a") is None
    assert await repo.get(TENANT_A, ENV_2, "rcsmc_a") is None
    assert await repo.get(TENANT_A, ENV_1, "rcsmc_absent") is None


@pytest.mark.asyncio
async def test_candidate_rows_validate_back_into_typed_view_without_loss() -> None:
    repo = get_mapping_candidate_repository()
    await repo.create(
        _candidate(
            candidate_id="rcsmc_typed",
            confidence=0.5,
            sensitivity_class="pii",
            review_state="unresolved",
        )
    )
    row = await repo.get(TENANT_A, ENV_1, "rcsmc_typed")
    assert row is not None
    reloaded = MappingCandidateRow.model_validate(row)
    assert reloaded.candidate_id == "rcsmc_typed"
    assert reloaded.confidence == 0.5
    assert reloaded.sensitivity_class == "pii"
    assert reloaded.review_state == "unresolved"
    assert reloaded.created_at == NOW
    assert reloaded.tenant_id == TENANT_A
    assert reloaded.environment_id == ENV_1


# ── §38 schema-mapping runs ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_create_get_round_trip_preserves_json_columns() -> None:
    repo = get_schema_mapping_run_repository()
    created = await repo.create(_run())
    assert created["run_id"] == "smrun_1"
    assert created["managed_integration_ref"] == INTEGRATION
    assert created["tenant_id"] == TENANT_A
    assert created["environment_id"] == ENV_1
    assert created["observed_schema_fingerprint"] == "fp-observed-v2"
    assert created["desired_schema_fingerprint"] == "fp-observed-v2"
    assert created["diff_summary"] == {
        "changed_fields": ["order.total.precision"]
    }
    assert created["candidate_ids"] == ["rcsmc_a"]
    assert created["gate_results"] == _run().gate_results
    assert created["gate_results"]["shadow_result_passes"] is True
    assert created["promoted"] is True
    assert created["action_required_ref"] is None
    assert created["created_at"] == _json_ts(NOW)

    row = await repo.get(TENANT_A, ENV_1, "smrun_1")
    assert row is not None
    assert row["run_id"] == "smrun_1"
    assert row["diff_summary"] == {"changed_fields": ["order.total.precision"]}
    assert row["candidate_ids"] == ["rcsmc_a"]
    assert row["gate_results"] == _run().gate_results
    assert row["promoted"] is True
    assert row["created_at"] == _json_ts(NOW)

    # A non-promoted run keeps its per-gate verdicts and its action ref.
    blocked = await repo.create(
        _run(
            run_id="smrun_blocked",
            promoted=False,
            gate_results={
                "high_confidence": False,
                "no_new_data_category": True,
                "no_new_sensitive_field": True,
                "no_new_processing_purpose": True,
                "no_new_platform_provider_permission": True,
                "no_material_semantic_loss": True,
                "shadow_result_passes": True,
                "health_within_gates": True,
            },
            action_required_ref="rcact_review_required",
        )
    )
    assert blocked["promoted"] is False
    assert blocked["gate_results"]["high_confidence"] is False
    assert blocked["action_required_ref"] == "rcact_review_required"


@pytest.mark.asyncio
async def test_run_list_for_integration_orders_newest_created() -> None:
    repo = get_schema_mapping_run_repository()
    await repo.create(_run(run_id="smrun_1", created_at=NOW))
    await repo.create(
        _run(run_id="smrun_late", created_at=NOW.replace(minute=2))
    )
    await repo.create(
        _run(run_id="smrun_mid", created_at=NOW.replace(minute=1))
    )
    await repo.create(
        _run(
            run_id="smrun_tenant_b",
            tenant_id=TENANT_B,
            created_at=NOW.replace(minute=3),
        )
    )
    await repo.create(
        _run(
            run_id="smrun_other_env",
            environment_id=ENV_2,
            created_at=NOW.replace(minute=4),
        )
    )
    await repo.create(
        _run(
            run_id="smrun_other_mi",
            managed_integration_ref="mi-other",
            created_at=NOW.replace(minute=5),
        )
    )

    rows = await repo.list_for_integration(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
    )
    # Newest-created first, scoped to (tenant, env, integration).
    assert [r["run_id"] for r in rows] == ["smrun_late", "smrun_mid", "smrun_1"]
    assert rows[0]["created_at"] == _json_ts(NOW.replace(minute=2))
    assert rows[0]["gate_results"]["high_confidence"] is True

    limited = await repo.list_for_integration(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
        limit=2,
    )
    assert [r["run_id"] for r in limited] == ["smrun_late", "smrun_mid"]

    other_mi = await repo.list_for_integration(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref="mi-other",
    )
    assert [r["run_id"] for r in other_mi] == ["smrun_other_mi"]
    tenant_b = await repo.list_for_integration(
        tenant_id=TENANT_B,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
    )
    assert [r["run_id"] for r in tenant_b] == ["smrun_tenant_b"]


@pytest.mark.asyncio
async def test_run_get_refuses_cross_tenant_and_cross_env() -> None:
    repo = get_schema_mapping_run_repository()
    await repo.create(_run())
    assert await repo.get(TENANT_B, ENV_1, "smrun_1") is None
    assert await repo.get(TENANT_A, ENV_2, "smrun_1") is None
    assert await repo.get(TENANT_A, ENV_1, "smrun_absent") is None
    # The refused reads never mutated the stored row.
    row = await repo.get(TENANT_A, ENV_1, "smrun_1")
    assert row is not None
    assert row["promoted"] is True


@pytest.mark.asyncio
async def test_run_rows_validate_back_into_typed_view_without_loss() -> None:
    repo = get_schema_mapping_run_repository()
    await repo.create(
        _run(
            run_id="smrun_typed",
            observed_schema_fingerprint="fp-observed",
            desired_schema_fingerprint="fp-desired-v3",
            diff_summary={"added_fields": ["order.discount.code"]},
            candidate_ids=["rcsmc_typed", "rcsmc_other"],
            gate_results={k: False for k in _run().gate_results},
            promoted=False,
            action_required_ref="rcact_review_required",
        )
    )
    row = await repo.get(TENANT_A, ENV_1, "smrun_typed")
    assert row is not None
    reloaded = SchemaMappingRunRow.model_validate(row)
    assert reloaded.run_id == "smrun_typed"
    assert reloaded.observed_schema_fingerprint == "fp-observed"
    assert reloaded.desired_schema_fingerprint == "fp-desired-v3"
    assert reloaded.diff_summary == {"added_fields": ["order.discount.code"]}
    assert reloaded.candidate_ids == ["rcsmc_typed", "rcsmc_other"]
    assert reloaded.gate_results == {k: False for k in reloaded.gate_results}
    assert reloaded.promoted is False
    assert reloaded.action_required_ref == "rcact_review_required"
    assert reloaded.created_at == NOW
