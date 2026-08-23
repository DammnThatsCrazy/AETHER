"""Output-schema validation tests -- SchemaOutputValidator, OutputValidation.

Covers ADR-008 Commit 7 output-kind enforcement: every declared output kind
(``query_plan``, ``grounded_answer``, ``classification``, ``evidence_set``,
``structured_json``) accepts a well-formed sample and fails closed on a
malformed sample; unknown kinds are rejected; query plans reject embedded raw
query text; grounded answers must cite evidence (or be marked unsupported).
"""
from __future__ import annotations

from services.model_runtime.task_profiles.output_schema import (
    OutputValidation,
    OutputValidationError,
    OutputValidator,
    SchemaOutputValidator,
)
from shared.model_governance.generated_task_profiles import OUTPUT_KINDS

VALID_QUERY_PLAN = {
    "steps": [
        {"intent": "Find active tenant accounts", "mode": "allowlisted"},
        {"intent": "Join accounts to recent transactions", "mode": "deterministic"},
    ]
}

VALID_GROUNDED_ANSWER = {
    "answer": (
        "The account is active [ref:acct-1] and was last billed on the 1st "
        "[ref:bill-9]."
    ),
    "evidence": [
        {"reference_id": "acct-1", "source": "accounts/ACME-100"},
        {"reference_id": "bill-9", "source": "billing/INV-2026"},
    ],
}


# ---------------------------------------------------------------------------
# query_plan
# ---------------------------------------------------------------------------
def test_query_plan_valid_sample_passes():
    result = SchemaOutputValidator().validate("query_plan", VALID_QUERY_PLAN)
    assert result.valid is True
    assert result.errors == ()


def test_query_plan_rejects_non_dict_output():
    result = SchemaOutputValidator().validate("query_plan", ["SELECT * FROM users"])
    assert result.valid is False
    assert any("dict" in error for error in result.errors)


def test_query_plan_rejects_missing_steps():
    result = SchemaOutputValidator().validate("query_plan", {"intent": "nope"})
    assert result.valid is False
    assert any("steps" in error for error in result.errors)


def test_query_plan_rejects_step_missing_intent():
    plan = {"steps": [{"mode": "allowlisted"}]}
    result = SchemaOutputValidator().validate("query_plan", plan)
    assert result.valid is False
    assert any("intent" in error for error in result.errors)


def test_query_plan_rejects_free_text_mode():
    plan = {"steps": [{"intent": "Find accounts", "mode": "freeform"}]}
    result = SchemaOutputValidator().validate("query_plan", plan)
    assert result.valid is False
    assert any("mode" in error for error in result.errors)


def test_query_plan_rejects_embedded_sql():
    plan = {
        "steps": [
            {
                "intent": "SELECT * FROM accounts WHERE status = 'active'",
                "mode": "allowlisted",
            }
        ]
    }
    result = SchemaOutputValidator().validate("query_plan", plan)
    assert result.valid is False
    assert any("raw query text" in error for error in result.errors)


def test_query_plan_rejects_gremlin_cypher_and_graphql():
    fragments = (
        "g.V('Account').out('owns')",
        "MATCH (a)-[:OWNS]->(b) RETURN a -- cypher",
        "subscription { graphql { onEvent } }",
    )
    for fragment in fragments:
        plan = {"steps": [{"intent": fragment, "mode": "allowlisted"}]}
        result = SchemaOutputValidator().validate("query_plan", plan)
        assert result.valid is False, f"expected rejection for {fragment!r}"
        assert any("raw query text" in error for error in result.errors)


# ---------------------------------------------------------------------------
# grounded_answer
# ---------------------------------------------------------------------------
def test_grounded_answer_valid_sample_passes():
    result = SchemaOutputValidator().validate("grounded_answer", VALID_GROUNDED_ANSWER)
    assert result.valid is True
    assert result.errors == ()


def test_grounded_answer_unsupported_passes_without_citation():
    answer = {
        "answer": "No evidence supports this claim.",
        "evidence": [],
        "unsupported": True,
    }
    result = SchemaOutputValidator().validate("grounded_answer", answer)
    assert result.valid is True
    assert result.errors == ()


def test_grounded_answer_unsupported_false_still_requires_citation():
    answer = {
        "answer": "No citation marker here.",
        "evidence": [],
        "unsupported": False,
    }
    result = SchemaOutputValidator().validate("grounded_answer", answer)
    assert result.valid is False
    assert any("cite an evidence" in error for error in result.errors)


def test_grounded_answer_citation_mismatch_fails():
    answer = {
        "answer": "The account is active [ref:acct-1].",
        "evidence": [{"reference_id": "bill-9", "source": "billing/INV-2026"}],
    }
    result = SchemaOutputValidator().validate("grounded_answer", answer)
    assert result.valid is False
    assert any("cite an evidence" in error for error in result.errors)


def test_grounded_answer_no_citation_fails():
    answer = {
        "answer": "The account is active.",
        "evidence": [{"reference_id": "acct-1", "source": "accounts/ACME-100"}],
    }
    result = SchemaOutputValidator().validate("grounded_answer", answer)
    assert result.valid is False
    assert any("cite an evidence" in error for error in result.errors)


def test_grounded_answer_missing_answer_fails():
    answer = {"evidence": [{"reference_id": "acct-1", "source": "accounts/ACME-100"}]}
    result = SchemaOutputValidator().validate("grounded_answer", answer)
    assert result.valid is False
    assert any("answer" in error for error in result.errors)


def test_grounded_answer_evidence_missing_source_fails():
    answer = {
        "answer": "Active [ref:acct-1].",
        "evidence": [{"reference_id": "acct-1"}],
    }
    result = SchemaOutputValidator().validate("grounded_answer", answer)
    assert result.valid is False
    assert any("source" in error for error in result.errors)


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------
def test_classification_valid_sample_passes():
    result = SchemaOutputValidator().validate(
        "classification", {"label": "high_risk", "confidence": 0.92}
    )
    assert result.valid is True
    assert result.errors == ()


def test_classification_boundary_confidences_pass():
    validator = SchemaOutputValidator()
    assert validator.validate("classification", {"label": "a", "confidence": 0.0}).valid
    assert validator.validate("classification", {"label": "a", "confidence": 1.0}).valid


def test_classification_confidence_out_of_range_fails():
    validator = SchemaOutputValidator()
    for confidence in (-0.1, 1.5):
        result = validator.validate("classification", {"label": "a", "confidence": confidence})
        assert result.valid is False
        assert any("confidence" in error for error in result.errors)


def test_classification_confidence_bool_fails():
    result = SchemaOutputValidator().validate(
        "classification", {"label": "a", "confidence": True}
    )
    assert result.valid is False
    assert any("confidence" in error for error in result.errors)


def test_classification_missing_label_fails():
    result = SchemaOutputValidator().validate("classification", {"confidence": 0.9})
    assert result.valid is False
    assert any("label" in error for error in result.errors)


# ---------------------------------------------------------------------------
# evidence_set
# ---------------------------------------------------------------------------
def test_evidence_set_valid_sample_passes():
    evidence = [
        {"reference_id": "e-1", "content": "source line one"},
        {"reference_id": "e-2", "content": "source line two"},
    ]
    result = SchemaOutputValidator().validate("evidence_set", evidence)
    assert result.valid is True
    assert result.errors == ()


def test_evidence_set_rejects_non_list():
    result = SchemaOutputValidator().validate("evidence_set", {"reference_id": "e-1"})
    assert result.valid is False
    assert any("list" in error for error in result.errors)


def test_evidence_set_rejects_missing_reference_id():
    result = SchemaOutputValidator().validate(
        "evidence_set", [{"content": "some source text"}]
    )
    assert result.valid is False
    assert any("reference_id" in error for error in result.errors)


def test_evidence_set_rejects_empty_content():
    result = SchemaOutputValidator().validate(
        "evidence_set", [{"reference_id": "e-1", "content": ""}]
    )
    assert result.valid is False
    assert any("content" in error for error in result.errors)


def test_evidence_set_rejects_non_dict_item():
    result = SchemaOutputValidator().validate("evidence_set", ["not-a-dict"])
    assert result.valid is False
    assert any("dict" in error for error in result.errors)


# ---------------------------------------------------------------------------
# structured_json
# ---------------------------------------------------------------------------
def test_structured_json_valid_dict_passes():
    result = SchemaOutputValidator().validate(
        "structured_json", {"count": 3, "tags": ["a", "b"]}
    )
    assert result.valid is True
    assert result.errors == ()


def test_structured_json_valid_list_passes():
    result = SchemaOutputValidator().validate(
        "structured_json", [1, {"x": 2}, ["nested"]]
    )
    assert result.valid is True
    assert result.errors == ()


def test_structured_json_rejects_set():
    result = SchemaOutputValidator().validate("structured_json", {1, 2, 3})
    assert result.valid is False
    assert any("JSON" in error for error in result.errors)


def test_structured_json_rejects_raw_string():
    result = SchemaOutputValidator().validate("structured_json", "just some text")
    assert result.valid is False
    assert any("JSON" in error for error in result.errors)


def test_structured_json_rejects_nonserializable_value():
    result = SchemaOutputValidator().validate(
        "structured_json", {"count": 3, "tags": {"a", "b"}}
    )
    assert result.valid is False
    assert any("JSON" in error for error in result.errors)


# ---------------------------------------------------------------------------
# secret-marker sweep (applies to EVERY output kind, fail-closed)
# ---------------------------------------------------------------------------
def test_evidence_set_with_secret_shaped_content_fails():
    evidence = [
        {"reference_id": "e-1", "content": "the api key is sk-live-1234567890abcdef"},
    ]
    result = SchemaOutputValidator().validate("evidence_set", evidence)
    assert result.valid is False
    assert any("credential" in error for error in result.errors)
    # Content-free: the matched secret is never echoed into an error string.
    assert all("sk-live" not in error for error in result.errors)


def test_classification_label_with_secret_shaped_value_fails():
    result = SchemaOutputValidator().validate(
        "classification", {"label": "sk-live-1234567890abcdef", "confidence": 0.9}
    )
    assert result.valid is False
    assert any("credential" in error for error in result.errors)
    assert all("sk-live" not in error for error in result.errors)


def test_structured_json_with_secret_shaped_field_fails():
    payload = {"credentials": {"access": "AKIAIOSFODNN7EXAMPLE"}}
    result = SchemaOutputValidator().validate("structured_json", payload)
    assert result.valid is False
    assert any("credential" in error for error in result.errors)
    assert all("AKIA" not in error for error in result.errors)


def test_structured_json_nested_secret_in_list_fails():
    payload = {"items": ["plain", {"token": "-----BEGIN PRIVATE KEY-----"}]}
    result = SchemaOutputValidator().validate("structured_json", payload)
    assert result.valid is False
    assert any("credential" in error for error in result.errors)


def test_query_plan_with_secret_shaped_intent_fails():
    plan = {
        "steps": [
            {"intent": "lookup access key AKIAIOSFODNN7EXAMPLE", "mode": "allowlisted"},
        ]
    }
    result = SchemaOutputValidator().validate("query_plan", plan)
    assert result.valid is False
    assert any("credential" in error for error in result.errors)


def test_grounded_answer_with_secret_shaped_answer_fails():
    answer = {
        "answer": "the token is sk-live-1234567890abcdef [ref:acct-1]",
        "evidence": [{"reference_id": "acct-1", "source": "accounts/ACME-100"}],
    }
    result = SchemaOutputValidator().validate("grounded_answer", answer)
    assert result.valid is False
    assert any("credential" in error for error in result.errors)


# ---------------------------------------------------------------------------
# unknown kinds / error paths / public surface
# ---------------------------------------------------------------------------
def test_unknown_kind_fails():
    result = SchemaOutputValidator().validate("freeform", {"anything": 1})
    assert result.valid is False
    assert result.errors == ("unknown output kind",)


def test_output_validation_carries_declared_fields():
    result = OutputValidation(kind="classification", valid=True, errors=())
    assert result.kind == "classification"
    assert result.valid is True
    assert result.errors == ()
    # Default errors tuple is empty.
    assert OutputValidation(kind="x", valid=True).errors == ()


def test_output_validation_is_frozen():
    result = OutputValidation(kind="x", valid=False)
    assert result.model_config.get("frozen") is True
    try:
        result.valid = True  # type: ignore[misc]
        frozen = False
    except Exception:
        frozen = True
    assert frozen is True


def test_output_validation_error_raised_for_non_string_kind():
    try:
        SchemaOutputValidator().validate(123, {"a": 1})  # type: ignore[arg-type]
        raised = False
    except OutputValidationError:
        raised = True
    assert raised is True


def test_output_validation_error_is_exception():
    assert issubclass(OutputValidationError, Exception)


def test_schema_validator_satisfies_output_validator_protocol():
    def require(v: OutputValidator) -> OutputValidator:
        return v

    validator = require(SchemaOutputValidator())
    result = validator.validate("classification", {"label": "a", "confidence": 0.5})
    assert isinstance(result, OutputValidation)
    assert result.valid is True


def test_every_registry_output_kind_is_known():
    validator = SchemaOutputValidator()
    for kind in OUTPUT_KINDS:
        result = validator.validate(kind, None)  # None is structurally invalid
        assert result.kind == kind
        assert result.errors != ("unknown output kind",)
        assert "unknown output kind" not in result.errors
        assert result.valid is False


def test_every_task_profile_output_kind_is_known():
    from services.model_runtime.routing.profiles import ProfileRegistry

    validator = SchemaOutputValidator()
    for profile in ProfileRegistry().all():
        result = validator.validate(profile.output_kind, None)
        assert result.kind == profile.output_kind
        assert "unknown output kind" not in result.errors
