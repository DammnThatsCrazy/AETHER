"""Canonical-enum parity: incentive_context constants vs the M1 JSON $defs.

The M1 contract ``packages/shared/contracts/incentive-context.schema.json`` is
the source of truth for the enum members this milestone's runtime carries.
These tests fail loudly if the Python carrier in
``services/incentive_context/canonical.py`` drifts from the JSON (the M1
contract tests assert the JSON's own layout; this file asserts the runtime
carrier mirrors it).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
SCHEMA_PATH = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "incentive-context.schema.json"
)

from services.incentive_context.canonical import (  # noqa: E402
    CONFIDENCE_KINDS,
    EVIDENCE_BASIS,
    INCENTIVE_CONTEXT_SCHEMA_VERSION,
    INCENTIVE_STATUSES,
    INCENTIVE_WINDOW,
    POST_INCENTIVE,
    PRE_INCENTIVE,
    SOURCE_SCOPES,
    TEMPORAL_SEGMENTS,
)


@pytest.fixture(scope="module")
def schema() -> dict:
    assert SCHEMA_PATH.exists(), f"missing M1 contract {SCHEMA_PATH}"
    with SCHEMA_PATH.open() as fh:
        return json.load(fh)


def test_schema_path_resolution() -> None:
    # Guard the parents-index assumption above so a file move fails loudly.
    assert (REPO_ROOT / "packages" / "shared" / "contracts").exists()


def test_schema_version_matches(schema: dict) -> None:
    declared = schema["properties"]["schema_version"]["const"]
    assert declared == "1.0.0"
    assert INCENTIVE_CONTEXT_SCHEMA_VERSION == declared


def test_status_enum_parity(schema: dict) -> None:
    declared = schema["$defs"]["incentiveStatus"]["enum"]
    assert set(INCENTIVE_STATUSES) == set(declared)
    assert len(INCENTIVE_STATUSES) == len(declared)


def test_temporal_segment_enum_parity(schema: dict) -> None:
    declared = schema["$defs"]["temporalSegment"]["properties"]["segment"]["enum"]
    assert list(TEMPORAL_SEGMENTS) == list(declared)
    # canonical ordering is PRE < INCENTIVE_WINDOW < POST_INCENTIVE
    assert list(TEMPORAL_SEGMENTS) == [PRE_INCENTIVE, INCENTIVE_WINDOW, POST_INCENTIVE]


def test_confidence_kind_enum_parity(schema: dict) -> None:
    declared = schema["properties"]["confidence_kind"]["enum"]
    assert set(CONFIDENCE_KINDS) == set(declared)


def test_source_scope_parity(schema: dict) -> None:
    declared = schema["$defs"]["sourceScope"]["enum"]
    assert set(SOURCE_SCOPES) == set(declared)
    # Doctrine: sourceScope has no unknown member (a guessable scope is refused).
    assert "unknown" not in SOURCE_SCOPES


def test_evidence_basis_parity(schema: dict) -> None:
    declared = schema["$defs"]["evidenceBasis"]["enum"]
    assert set(EVIDENCE_BASIS) == set(declared)


def test_no_organic_anywhere(schema: dict) -> None:
    # Release-blocking honesty invariant: "organic" is not a status this carrier
    # or the M1 schema exposes, and none_observed NEVER converts to organic.
    assert "organic" not in schema["$defs"]["incentiveStatus"]["enum"]
    assert "organic" not in INCENTIVE_STATUSES
    assert "none_observed" in INCENTIVE_STATUSES
