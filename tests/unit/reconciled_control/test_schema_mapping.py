"""Unit tests for the Phase-3 schema/mapping drift-automation engine.

Exercises ``services.managed_integrations.schema_mapping`` (§25 fingerprints,
§8.1 review-state policy + candidate persistence, §38 auto-promotion gates)
over the module-local in-memory stores with ``get_pool`` pinned to None — the
same columnar path the engine uses without a live Postgres.

Coverage anchors:

* §25 — deterministic canonical fingerprints; unknown component keys raise;
  the event_registry + field_definitions required set is enforced; missing
  optional components are absent (never defaulted); the release/runtime/
  desired invariant and its drift classification.
* §8.1 — exact confidence boundaries (.98 inclusive auto-propose, review band
  [0.80, 0.98), <0.80 unresolved) with the sensitive override; candidate
  persistence + list filters.
* §38 — promotion only when all eight gates hold (7-gate verdicts fail
  closed), unknown gate keys raise, and the promote/review/action decision
  mapping.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from services.managed_integrations.contracts import (
    MAPPING_REVIEW_STATES,
    SCHEMA_MAPPING_AUTO_PROMOTE_GATES,
)
from services.managed_integrations.schema_mapping import (
    FINGERPRINT_INPUTS,
    auto_promote_decision,
    canonical_schema_fingerprint,
    evaluate_auto_promotion,
    is_drifted,
    record_candidate,
    review_state_for,
    schema_fingerprint_status,
)
from services.managed_integrations.schema_mapping_repository import (
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

S25_INPUTS = (
    "event_registry",
    "field_definitions",
    "required_optional_state",
    "enums",
    "event_family_bindings",
    "consent_purpose_bindings",
    "contract_versions",
    "extension_registry",
    "mapping_contract_version",
)


@pytest.fixture(autouse=True)
def _schema_mapping_db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``get_pool`` to None and empty the schema-mapping stores.

    Mirrors the sibling ``db_free`` fixture: the in-memory path is the
    unit-test reference for the SQL path's tenancy WHERE clauses.
    """

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


def _all_true_gates(**overrides: bool) -> dict[str, bool]:
    gates = {key: True for key in SCHEMA_MAPPING_AUTO_PROMOTE_GATES}
    gates.update(overrides)
    return gates


def _components(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_registry": {
            "created": {"fields": ["id", "at"], "kind": "business"},
            "updated": {"fields": ["id", "at", "by"], "kind": "business"},
        },
        "field_definitions": {
            "id": {"type": "string", "required": True},
            "amount": {"type": "decimal", "required": True},
        },
        "enums": {"status": ["active", "paused"]},
        "mapping_contract_version": "v1",
    }
    base.update(overrides)
    return base


async def _record_candidate(candidate_id: str, **overrides: Any) -> dict:
    kwargs: dict[str, Any] = {
        "candidate_id": candidate_id,
        "source_ref": "src/checkout@v2",
        "source_path": "checkout.order.total",
        "canonical_target": "canonical/commerce/order.total",
        "mapping_method": "heuristic",
        "confidence": 0.99,
        "sensitivity_class": None,
        "tenant_id": TENANT_A,
        "environment_id": ENV_1,
        "created_at": NOW,
    }
    kwargs.update(overrides)
    return await record_candidate(**kwargs)


# ── §25 fingerprint inputs + deterministic canonicalization ─────────────────


def test_fingerprint_inputs_are_exactly_the_s25_list() -> None:
    assert FINGERPRINT_INPUTS == S25_INPUTS
    assert len(FINGERPRINT_INPUTS) == len(set(FINGERPRINT_INPUTS))


def test_canonical_fingerprint_is_deterministic_across_orderings() -> None:
    first = canonical_schema_fingerprint(_components())
    # Same components inserted in a different order (top-level + nested) must
    # produce the identical digest across calls and insertion orders.
    reordered = canonical_schema_fingerprint(
        {
            "mapping_contract_version": "v1",
            "field_definitions": {
                "amount": {"type": "decimal", "required": True},
                "id": {"type": "string", "required": True},
            },
            "event_registry": {
                "updated": {"fields": ["id", "at", "by"], "kind": "business"},
                "created": {"fields": ["id", "at"], "kind": "business"},
            },
            "enums": {"status": ["active", "paused"]},
        }
    )
    again = canonical_schema_fingerprint(_components())
    assert first == reordered == again
    assert len(first) == 64  # sha256 hex digest
    assert all(c in "0123456789abcdef" for c in first)


def test_canonical_fingerprint_rejects_unknown_component_key() -> None:
    with pytest.raises(ValueError, match="§25"):
        canonical_schema_fingerprint(
            _components(provider_specific_payload={"oops": True})
        )


def test_canonical_fingerprint_requires_event_registry_and_field_definitions() -> None:
    with pytest.raises(ValueError, match="§25"):
        canonical_schema_fingerprint({"event_registry": {"created": {}}})
    with pytest.raises(ValueError, match="§25"):
        canonical_schema_fingerprint({"field_definitions": {"id": {}}})
    with pytest.raises(ValueError, match="§25"):
        canonical_schema_fingerprint({})


def test_canonical_fingerprint_absent_optional_components_never_defaulted() -> None:
    # The §25 required pair alone is a valid fingerprint input set.
    required_only = canonical_schema_fingerprint(
        {"event_registry": {"created": {}}, "field_definitions": {"id": {}}}
    )
    assert required_only == canonical_schema_fingerprint(
        {"field_definitions": {"id": {}}, "event_registry": {"created": {}}}
    )
    # Absent optional components are absent: they must not be defaulted in.
    # (An optional key present with a null value changes the digest, proving
    # the key-set is the semantic unit — absence is not "null".)
    with_null = canonical_schema_fingerprint(
        {
            "event_registry": {"created": {}},
            "field_definitions": {"id": {}},
            "enums": None,
        }
    )
    assert with_null != required_only


# ── §25 release / runtime / desired invariant ────────────────────────────────


def test_schema_fingerprint_status_all_equal_and_not_drifted() -> None:
    fp = canonical_schema_fingerprint(_components())
    status = schema_fingerprint_status(fp, fp, fp)
    assert status == {
        "release_runtime_match": True,
        "runtime_desired_match": True,
        "release_desired_match": True,
    }
    assert is_drifted(fp, fp, fp) is False


def test_schema_fingerprint_status_any_mismatch_is_drift() -> None:
    release = canonical_schema_fingerprint(_components())
    runtime = canonical_schema_fingerprint(_components(enums={"status": ["x"]}))
    desired = canonical_schema_fingerprint(
        _components(mapping_contract_version="v2")
    )
    assert is_drifted(release, runtime, desired) is True
    # Every pairwise comparison that differs must read False.
    status = schema_fingerprint_status(release, runtime, desired)
    assert status["release_runtime_match"] is False
    assert status["release_desired_match"] is False
    assert status["runtime_desired_match"] is False

    # A single disagreement is still drift.
    assert is_drifted(release, runtime, runtime) is True
    assert is_drifted(release, release, desired) is True
    status_pair = schema_fingerprint_status(release, release, desired)
    assert status_pair["release_runtime_match"] is True
    assert status_pair["release_desired_match"] is False
    assert status_pair["runtime_desired_match"] is False


def test_is_drifted_present_vs_missing_is_mismatch() -> None:
    fp = canonical_schema_fingerprint(_components())
    # None never equals a fingerprint: a missing authority is drift.
    assert is_drifted(None, fp, fp) is True
    assert is_drifted(fp, None, fp) is True
    assert is_drifted(fp, fp, None) is True
    assert is_drifted(None, None, None) is True
    status = schema_fingerprint_status(None, fp, None)
    assert status["release_runtime_match"] is False
    assert status["runtime_desired_match"] is False
    assert status["release_desired_match"] is False


# ── §8.1 review-state policy ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("confidence", "sensitivity_class", "expected"),
    [
        (0.98, None, "auto_propose"),  # 0.98 inclusive — auto band opens here
        (0.99, None, "auto_propose"),
        (1.0, None, "auto_propose"),
        (0.97, None, "review"),  # review band [0.80, 0.98)
        (0.80, None, "review"),  # 0.80 inclusive in the review band
        (0.79, None, "unresolved"),
        (0.5, None, "unresolved"),
        (0.0, None, "unresolved"),
        # §8.1 sensitive override: authorization is always required, so a
        # sensitive candidate never auto-proposes regardless of confidence.
        (0.99, "pii", "review"),
        (0.98, "pii", "review"),
        (0.80, "pii", "review"),
        (0.79, "pii", "unresolved"),
        (0.5, "pii", "unresolved"),
    ],
)
def test_review_state_for_boundaries(
    confidence: float, sensitivity_class: Any, expected: str
) -> None:
    state = review_state_for(confidence, sensitivity_class)
    assert state == expected
    assert state in MAPPING_REVIEW_STATES


@pytest.mark.asyncio
async def test_record_candidate_computes_review_state_and_lists_filtered() -> None:
    repo = get_mapping_candidate_repository()
    created = await _record_candidate("rcsmc_a")
    assert created["candidate_id"] == "rcsmc_a"
    assert created["review_state"] == "auto_propose"  # 0.99, non-sensitive
    assert created["mapping_method"] == "heuristic"
    assert created["source_ref"] == "src/checkout@v2"
    assert created["canonical_target"] == "canonical/commerce/order.total"
    assert created["tenant_id"] == TENANT_A
    assert created["environment_id"] == ENV_1

    # Low-confidence + sensitive: computed state stays in review/unresolved.
    await _record_candidate(
        "rcsmc_sensitive_low",
        confidence=0.5,
        sensitivity_class="pii",
        created_at=NOW.replace(minute=2),
    )
    await _record_candidate(
        "rcsmc_b",
        confidence=0.85,
        created_at=NOW.replace(minute=1),
    )
    # Another tenant's candidate must never leak into tenant A's list.
    await _record_candidate(
        "rcsmc_tenant_b",
        tenant_id=TENANT_B,
        created_at=NOW.replace(minute=3),
    )

    rows = await repo.list(tenant_id=TENANT_A, environment_id=ENV_1)
    # Newest-created first.
    assert [r["candidate_id"] for r in rows] == [
        "rcsmc_sensitive_low",
        "rcsmc_b",
        "rcsmc_a",
    ]
    auto = await repo.list(
        tenant_id=TENANT_A, environment_id=ENV_1, review_state="auto_propose"
    )
    assert [r["candidate_id"] for r in auto] == ["rcsmc_a"]
    unresolved = await repo.list(
        tenant_id=TENANT_A, environment_id=ENV_1, review_state="unresolved"
    )
    assert [r["candidate_id"] for r in unresolved] == ["rcsmc_sensitive_low"]
    assert unresolved[0]["sensitivity_class"] == "pii"
    assert unresolved[0]["review_state"] == "unresolved"

    limited = await repo.list(
        tenant_id=TENANT_A, environment_id=ENV_1, limit=2
    )
    assert [r["candidate_id"] for r in limited] == [
        "rcsmc_sensitive_low",
        "rcsmc_b",
    ]
    tenant_b = await repo.list(tenant_id=TENANT_B)
    assert [r["candidate_id"] for r in tenant_b] == ["rcsmc_tenant_b"]


@pytest.mark.asyncio
async def test_record_candidate_explicit_review_state_is_respected() -> None:
    created = await _record_candidate(
        "rcsmc_explicit",
        confidence=0.99,
        review_state="review",
        rationale="operator already flagged this source for review",
    )
    assert created["review_state"] == "review"
    row = await get_mapping_candidate_repository().get(
        TENANT_A, ENV_1, "rcsmc_explicit"
    )
    assert row is not None
    assert row["review_state"] == "review"
    assert row["rationale"] == "operator already flagged this source for review"


@pytest.mark.asyncio
async def test_candidate_get_and_list_for_source_are_scoped() -> None:
    repo = get_mapping_candidate_repository()
    await _record_candidate("rcsmc_a")
    await _record_candidate(
        "rcsmc_late",
        created_at=NOW.replace(minute=2),
    )
    await _record_candidate(
        "rcsmc_other_source",
        source_ref="src/identity@v1",
        created_at=NOW.replace(minute=1),
    )
    await _record_candidate(
        "rcsmc_tenant_b",
        tenant_id=TENANT_B,
        created_at=NOW.replace(minute=3),
    )

    # Cross-scope get returns None — the in-memory twin of the SQL WHERE
    # tenant_id=$1 AND environment_id=$2 clause.
    assert await repo.get(TENANT_B, ENV_1, "rcsmc_a") is None
    assert await repo.get(TENANT_A, ENV_2, "rcsmc_a") is None
    assert await repo.get(TENANT_A, ENV_1, "rcsmc_absent") is None
    row = await repo.get(TENANT_A, ENV_1, "rcsmc_a")
    assert row is not None
    assert row["source_path"] == "checkout.order.total"

    by_source = await repo.list_for_source(
        tenant_id=TENANT_A, environment_id=ENV_1, source_ref="src/checkout@v2"
    )
    assert [r["candidate_id"] for r in by_source] == ["rcsmc_late", "rcsmc_a"]
    other_source = await repo.list_for_source(
        tenant_id=TENANT_A, environment_id=ENV_1, source_ref="src/identity@v1"
    )
    assert [r["candidate_id"] for r in other_source] == ["rcsmc_other_source"]
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


# ── §38 auto-promotion gates ─────────────────────────────────────────────────


def _gates_for(decision_hint: str) -> dict[str, bool]:
    if decision_hint == "promote":
        return _all_true_gates()
    if decision_hint == "review_required":
        return _all_true_gates(high_confidence=False)
    return _all_true_gates(no_new_sensitive_field=False)


def test_schema_mapping_has_exactly_eight_auto_promote_gates() -> None:
    assert len(SCHEMA_MAPPING_AUTO_PROMOTE_GATES) == 8
    assert set(SCHEMA_MAPPING_AUTO_PROMOTE_GATES) == {
        "high_confidence",
        "no_new_data_category",
        "no_new_sensitive_field",
        "no_new_processing_purpose",
        "no_new_platform_provider_permission",
        "no_material_semantic_loss",
        "shadow_result_passes",
        "health_within_gates",
    }


@pytest.mark.asyncio
async def test_evaluate_auto_promotion_all_eight_gates_promotes() -> None:
    run = await evaluate_auto_promotion(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
        run_id="smrun_all_green",
        gates=_all_true_gates(),
        candidates=["rcsmc_a"],
        observed_fingerprint=canonical_schema_fingerprint(_components()),
        desired_fingerprint=canonical_schema_fingerprint(_components()),
        diff_summary={"changed_fields": ["order.total.precision"]},
        now=NOW,
    )
    assert run["run_id"] == "smrun_all_green"
    assert run["promoted"] is True
    assert run["tenant_id"] == TENANT_A
    assert run["environment_id"] == ENV_1
    assert run["managed_integration_ref"] == INTEGRATION
    assert run["gate_results"] == _all_true_gates()
    assert len(run["gate_results"]) == 8
    assert run["candidate_ids"] == ["rcsmc_a"]
    assert run["diff_summary"] == {"changed_fields": ["order.total.precision"]}
    assert run["observed_schema_fingerprint"] == run["desired_schema_fingerprint"]
    assert run["action_required_ref"] is None

    # Durable under the run's own id, scoped.
    row = await get_schema_mapping_run_repository().get(
        TENANT_A, ENV_1, "smrun_all_green"
    )
    assert row is not None
    assert row["promoted"] is True
    assert row["created_at"] == NOW.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_evaluate_auto_promotion_missing_gate_fails_closed() -> None:
    seven_gates = _all_true_gates()
    assert seven_gates.pop("health_within_gates") is True  # 8th gate removed
    assert len(seven_gates) == 7
    run = await evaluate_auto_promotion(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
        run_id="smrun_seven_gates",
        gates=seven_gates,
        candidates=["rcsmc_a"],
        observed_fingerprint="fp-obs",
        desired_fingerprint="fp-des",
        now=NOW,
    )
    # Fail closed: a missing gate is a failed gate — never promoted even
    # though every supplied gate is true.
    assert run["promoted"] is False
    assert len(run["gate_results"]) == 7


@pytest.mark.asyncio
async def test_evaluate_auto_promotion_any_false_gate_is_not_promoted() -> None:
    run = await evaluate_auto_promotion(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
        run_id="smrun_gate_false",
        gates=_all_true_gates(shadow_result_passes=False),
        candidates=["rcsmc_a"],
        observed_fingerprint="fp-obs",
        desired_fingerprint="fp-des",
        action_required_ref="rcact_shadow_failed",
        now=NOW,
    )
    assert run["promoted"] is False
    assert run["gate_results"]["shadow_result_passes"] is False
    assert run["action_required_ref"] == "rcact_shadow_failed"


@pytest.mark.asyncio
async def test_evaluate_auto_promotion_unknown_gate_key_raises_s38() -> None:
    with pytest.raises(ValueError, match="§38"):
        await evaluate_auto_promotion(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            managed_integration_ref=INTEGRATION,
            gates=_all_true_gates(also_no_semantic_loss=True),  # made-up gate
            candidates=["rcsmc_a"],
            observed_fingerprint="fp-obs",
            desired_fingerprint="fp-des",
        )


@pytest.mark.parametrize(
    ("decision_hint", "expected"),
    [
        ("promote", "promote"),
        ("review_required", "review_required"),
        ("action_required", "action_required"),
    ],
)
def test_auto_promote_decision_mapping(
    decision_hint: str, expected: str
) -> None:
    gates = _gates_for(decision_hint)
    decision = auto_promote_decision(gates)
    assert decision == expected
    # Decision and persisted-verdict agree: only an all-eight-true run
    # promotes.
    promoted = (
        len(gates) == len(SCHEMA_MAPPING_AUTO_PROMOTE_GATES)
        and all(v is True for v in gates.values())
    )
    assert (decision == "promote") == promoted


def test_auto_promote_decision_missing_gate_fails_closed_to_non_promote() -> None:
    seven_gates = _all_true_gates()
    seven_gates.pop("no_material_semantic_loss")
    assert auto_promote_decision(seven_gates) == "action_required"
    # A missing high_confidence is a review-required verdict, not promotion.
    no_confidence = _all_true_gates()
    no_confidence.pop("high_confidence")
    assert auto_promote_decision(no_confidence) == "review_required"


def test_auto_promote_decision_unknown_gate_key_raises_s38() -> None:
    with pytest.raises(ValueError, match="§38"):
        auto_promote_decision(_all_true_gates(fake_gate=True))


@pytest.mark.asyncio
async def test_run_rows_list_for_integration_newest_first_and_scoped() -> None:
    repo = get_schema_mapping_run_repository()
    await evaluate_auto_promotion(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
        run_id="smrun_1",
        gates=_all_true_gates(),
        candidates=["rcsmc_a"],
        observed_fingerprint="fp-obs",
        desired_fingerprint="fp-obs",
        now=NOW,
    )
    await evaluate_auto_promotion(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
        run_id="smrun_2",
        gates=_all_true_gates(),
        candidates=["rcsmc_a", "rcsmc_b"],
        observed_fingerprint="fp-obs-v2",
        desired_fingerprint="fp-obs-v2",
        now=NOW.replace(minute=2),
    )
    await evaluate_auto_promotion(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
        run_id="smrun_3",
        gates=_all_true_gates(high_confidence=False),
        candidates=[],
        observed_fingerprint="fp-obs",
        desired_fingerprint="fp-obs-v3",
        now=NOW.replace(minute=1),
    )
    # Other-tenant / other-env / other-integration runs must never appear.
    await evaluate_auto_promotion(
        tenant_id=TENANT_B,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
        run_id="smrun_tenant_b",
        gates=_all_true_gates(),
        candidates=[],
        observed_fingerprint="fp-b",
        desired_fingerprint="fp-b",
        now=NOW.replace(minute=5),
    )
    await evaluate_auto_promotion(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref="mi-other",
        run_id="smrun_other_mi",
        gates=_all_true_gates(),
        candidates=[],
        observed_fingerprint="fp-o",
        desired_fingerprint="fp-o",
        now=NOW.replace(minute=6),
    )
    await evaluate_auto_promotion(
        tenant_id=TENANT_A,
        environment_id=ENV_2,
        managed_integration_ref=INTEGRATION,
        run_id="smrun_other_env",
        gates=_all_true_gates(),
        candidates=[],
        observed_fingerprint="fp-e",
        desired_fingerprint="fp-e",
        now=NOW.replace(minute=7),
    )

    rows = await repo.list_for_integration(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
    )
    # Newest-created first, scoped to the integration.
    assert [r["run_id"] for r in rows] == ["smrun_2", "smrun_3", "smrun_1"]
    assert rows[0]["promoted"] is True
    assert rows[1]["promoted"] is False
    assert rows[1]["gate_results"]["high_confidence"] is False
    assert rows[1]["candidate_ids"] == []

    limited = await repo.list_for_integration(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
        limit=2,
    )
    assert [r["run_id"] for r in limited] == ["smrun_2", "smrun_3"]

    # Cross-scope get reads as None; scoped get reads the row back typed.
    assert await repo.get(TENANT_B, ENV_1, "smrun_1") is None
    assert await repo.get(TENANT_A, ENV_2, "smrun_1") is None
    row = await repo.get(TENANT_A, ENV_1, "smrun_2")
    assert row is not None
    reloaded = SchemaMappingRunRow.model_validate(row)
    assert reloaded.run_id == "smrun_2"
    assert reloaded.gate_results["health_within_gates"] is True
    assert reloaded.candidate_ids == ["rcsmc_a", "rcsmc_b"]
    assert reloaded.created_at == NOW.replace(minute=2)


@pytest.mark.asyncio
async def test_candidate_rows_validate_back_into_typed_storage_view() -> None:
    # ``created_at`` omitted: the engine defaults it to now (never None).
    created = await _record_candidate(
        "rcsmc_typed",
        mapping_method="provider_known",
        confidence=0.5,
        sensitivity_class="pii",
        transform_ref="transform/round-decimal",
        created_at=None,
    )
    assert created["created_at"] is not None
    assert created["review_state"] == "unresolved"  # 0.5 + sensitive
    row = await get_mapping_candidate_repository().get(
        TENANT_A, ENV_1, "rcsmc_typed"
    )
    assert row is not None
    reloaded = MappingCandidateRow.model_validate(row)
    assert reloaded.candidate_id == "rcsmc_typed"
    assert reloaded.mapping_method == "provider_known"
    assert reloaded.sensitivity_class == "pii"
    assert reloaded.transform_ref == "transform/round-decimal"
    assert reloaded.confidence == 0.5
