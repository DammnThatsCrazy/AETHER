"""Grounded-synthesis plan-gate tests (ADR-008 Commit 9).

Covers the allowlist and proposal model owned by the synthesis team: a model
may propose ONLY one of the five allowlisted structured plan kinds -- never an
arbitrary tool call.  Unlisted kinds fail closed with
:class:`PlanNotAllowlisted`; rationale/target_schema carrying a secret marker
or a URL-typed target_schema fail with :class:`PlanUnsafe`.  Also covers the
default :class:`PlanRegistry` resolution and frozen/extra-``forbid`` proposal
behavior.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.model_runtime.synthesis.plans import (
    ALLOWED_PLAN_KINDS,
    PlanNotAllowlisted,
    PlanProposal,
    PlanRegistry,
    PlanUnsafe,
)


def _raises(exc_type, fn, *args, **kwargs) -> bool:
    """Return True when ``fn(*args, **kwargs)`` raises ``exc_type``."""
    try:
        fn(*args, **kwargs)
    except exc_type:
        return True
    return False


# ---------------------------------------------------------------------------
# PlanProposal -- allowlisted kinds
# ---------------------------------------------------------------------------


def test_allowlist_contains_exactly_the_five_kinds():
    assert ALLOWED_PLAN_KINDS == (
        "classify",
        "summarize",
        "recommend",
        "extract",
        "decide",
    )


def test_each_allowlisted_kind_is_valid():
    for kind in ALLOWED_PLAN_KINDS:
        proposal = PlanProposal(plan_kind=kind, rationale=f"because {kind}")
        assert proposal.plan_kind == kind
        assert proposal.target_schema is None
        assert proposal.rationale == f"because {kind}"


def test_proposal_carries_target_schema_and_rationale():
    proposal = PlanProposal(
        plan_kind="extract",
        target_schema="ledger_extraction",
        rationale="pull vendor rows",
    )
    assert proposal.target_schema == "ledger_extraction"
    assert proposal.rationale == "pull vendor rows"


# ---------------------------------------------------------------------------
# PlanProposal -- unallowlisted kinds fail closed
# ---------------------------------------------------------------------------


def test_unlisted_kinds_raise_plan_not_allowlisted():
    for kind in ("write_sql", "delete", "http_get"):
        assert _raises(PlanNotAllowlisted, PlanProposal, plan_kind=kind), kind


def test_unlisted_kind_is_not_a_validation_error():
    # The custom exception must propagate directly, not be wrapped in a
    # pydantic ValidationError, so the control plane can catch it distinctly.
    with pytest.raises(PlanNotAllowlisted):
        PlanProposal(plan_kind="write_sql")


def test_empty_plan_kind_raises_plan_not_allowlisted():
    assert _raises(PlanNotAllowlisted, PlanProposal, plan_kind="")


# ---------------------------------------------------------------------------
# PlanProposal -- secret markers -> PlanUnsafe
# ---------------------------------------------------------------------------


def test_rationale_with_secret_marker_raises_plan_unsafe():
    for rationale in ("handled via sk-abc123", "token eyJhbGciOiJIUzI1NiJ9"):
        assert _raises(PlanUnsafe, PlanProposal, plan_kind="classify", rationale=rationale), (
            rationale
        )


def test_target_schema_with_secret_marker_raises_plan_unsafe():
    assert _raises(PlanUnsafe, PlanProposal, plan_kind="classify", target_schema="sk-live-abc")


def test_clean_proposal_passes_secret_screen():
    proposal = PlanProposal(
        plan_kind="summarize",
        rationale="no secrets here",
        target_schema="summary",
    )
    assert proposal.rationale == "no secrets here"


def test_secret_markers_match_case_insensitively_in_rationale():
    # Case variants that bypassed the old case-sensitive substring check must
    # all fail closed: "SK-..." (marker "sk-" is stored lowercase), "akia..."
    # (marker "AKIA" is stored uppercase), and "bearer ..." (marker "Bearer "
    # is stored capitalized).
    for rationale in (
        "rotated to SK-live-1234",
        "credential akiaEXAMPLE123",
        "authorize via bearer abc123",
    ):
        assert _raises(PlanUnsafe, PlanProposal, plan_kind="classify", rationale=rationale), rationale


def test_secret_markers_match_case_insensitively_in_target_schema():
    for target in ("SK-live-1234", "akiaEXAMPLE123", "Bearer abc123"):
        assert _raises(PlanUnsafe, PlanProposal, plan_kind="classify", target_schema=target), target


# ---------------------------------------------------------------------------
# PlanProposal -- target_schema URL rejection
# ---------------------------------------------------------------------------


def test_target_schema_url_raises_plan_unsafe():
    for target in (
        "schema://http",
        "https://evil.example/schema",
        "file:///etc/passwd",
    ):
        assert _raises(PlanUnsafe, PlanProposal, plan_kind="classify", target_schema=target), target


def test_target_schema_none_and_plain_name_are_valid():
    assert PlanProposal(plan_kind="classify").target_schema is None
    assert (
        PlanProposal(plan_kind="classify", target_schema="ledger_extraction").target_schema
        == "ledger_extraction"
    )


# ---------------------------------------------------------------------------
# PlanProposal -- frozen / extra-forbid
# ---------------------------------------------------------------------------


def test_plan_proposal_is_frozen():
    proposal = PlanProposal(plan_kind="classify")
    assert _raises(ValueError, setattr, proposal, "rationale", "changed")
    assert _raises(ValueError, setattr, proposal, "target_schema", "other")
    assert proposal.rationale == ""


def test_plan_proposal_forbids_extra_fields():
    assert _raises(ValidationError, PlanProposal, plan_kind="classify", tools=["cat"])
    assert _raises(ValidationError, PlanProposal, plan_kind="classify", arbitrary_tool="ls")


# ---------------------------------------------------------------------------
# PlanRegistry
# ---------------------------------------------------------------------------


def test_default_registry_resolves_all_five_kinds():
    registry = PlanRegistry.default()
    for kind in ALLOWED_PLAN_KINDS:
        definition = registry.require(kind)
        assert definition["description"]
        assert definition["output_schema"]


def test_default_registry_output_schemas():
    registry = PlanRegistry.default()
    assert {kind: registry.require(kind)["output_schema"] for kind in ALLOWED_PLAN_KINDS} == {
        "classify": "classification",
        "summarize": "summary",
        "recommend": "recommendation",
        "extract": "extraction",
        "decide": "decision",
    }


def test_get_unknown_returns_none():
    registry = PlanRegistry.default()
    assert registry.get("write_sql") is None
    assert registry.get("http_get") is None
    assert registry.get("") is None


def test_require_unknown_raises_plan_not_allowlisted():
    registry = PlanRegistry.default()
    assert _raises(PlanNotAllowlisted, registry.require, "write_sql")
    assert _raises(PlanNotAllowlisted, registry.require, "delete")
    assert _raises(PlanNotAllowlisted, registry.require, "http_get")


def test_custom_registry_uses_supplied_definitions():
    registry = PlanRegistry({"decide": {"description": "d", "output_schema": "s"}})
    assert registry.require("decide") == {"description": "d", "output_schema": "s"}
    assert registry.get("classify") is None
    assert _raises(PlanNotAllowlisted, registry.require, "classify")


def test_registry_definitions_are_not_mutated_by_callers():
    definitions = {"decide": {"description": "d", "output_schema": "s"}}
    registry = PlanRegistry(definitions)
    definitions["decide"]["description"] = "mutated"
    assert registry.require("decide")["description"] == "d"


def test_registry_get_returns_a_copy():
    registry = PlanRegistry.default()
    definition = registry.require("classify")
    definition["description"] = "tampered"
    assert registry.require("classify")["description"] != "tampered"
