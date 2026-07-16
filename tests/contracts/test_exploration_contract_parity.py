"""TS <-> Python parity for the Unified Exploration Fabric contract.

`packages/shared/exploration-contract.ts` and `shared/exploration/models.py`
are hand-authored twins; this test fails on drift in the disposition/view/
temporal-mode vocabularies or the context/envelope field sets. It also pins
the composition rule: ExplorationContextV1 composes the canonical FilterGroup
(moved to `shared/contracts_models/filters.py`, re-exported unchanged from
`services/operational_intelligence/models.py`).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.exploration.models import (  # noqa: E402
    EXPLORATION_TEMPORAL_FIELDS,
    EXPLORATION_TEMPORAL_MODES,
    EXPLORATION_VIEWS,
    FILTER_DISPOSITIONS,
    ApplicabilityReport,
    ContextLink,
    ExplorationContextV1,
    ExplorationResultEnvelope,
    FilterApplicabilityEntry,
    TemporalSelection,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "exploration-contract.ts"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in exploration-contract.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(
        rf"export interface {interface}(?:<[^>]+>)?\s*\{{(.*?)\n\}}", text, re.S
    )
    assert m, f"interface {interface} not found in exploration-contract.ts"
    return set(re.findall(r"^\s{2}([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def test_filter_dispositions_parity():
    assert set(_const_array("filterDispositions")) == set(FILTER_DISPOSITIONS)


def test_views_parity():
    assert set(_const_array("explorationViews")) == set(EXPLORATION_VIEWS)


def test_temporal_modes_parity():
    assert set(_const_array("explorationTemporalModes")) == set(EXPLORATION_TEMPORAL_MODES)


def test_temporal_fields_parity():
    assert set(_const_array("explorationTemporalFields")) == set(EXPLORATION_TEMPORAL_FIELDS)


def test_context_field_parity():
    ts_fields = _interface_fields("ExplorationContextV1")
    py_fields = set(ExplorationContextV1.model_fields.keys())
    assert ts_fields == py_fields, (
        f"ExplorationContextV1 drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_result_envelope_field_parity():
    ts_fields = _interface_fields("ExplorationResultEnvelope")
    py_fields = set(ExplorationResultEnvelope.model_fields.keys())
    assert ts_fields == py_fields, (
        f"ExplorationResultEnvelope drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_temporal_selection_and_link_parity():
    assert _interface_fields("TemporalSelection") == set(TemporalSelection.model_fields)
    assert _interface_fields("ContextLink") == set(ContextLink.model_fields)
    assert _interface_fields("FilterApplicabilityEntry") == set(
        FilterApplicabilityEntry.model_fields
    )


def test_context_composes_canonical_filter_group():
    """The fabric composes the ONE filter language — from its shared home and
    (identically) from the legacy operational_intelligence re-export."""
    from services.operational_intelligence.models import FilterGroup as LegacyFilterGroup
    from shared.contracts_models.filters import FilterExpression, FilterGroup

    assert LegacyFilterGroup is FilterGroup  # re-export, not a copy

    context = ExplorationContextV1(
        scope={"tenant_id": "t1", "surface": "graph"},
        population=FilterGroup(
            logic="AND",
            expressions=[FilterExpression(field="entity.type", op="eq", value="human")],
        ),
        temporal=TemporalSelection(
            mode="window", field="occurred_at", timezone="America/New_York"
        ),
    )
    dumped = context.model_dump(mode="json", exclude_none=True)
    rebuilt = ExplorationContextV1.model_validate(dumped)
    assert rebuilt.population.expressions[0].field == "entity.type"
    assert rebuilt.version == "1"


def test_applicability_report_roundtrip():
    report = ApplicabilityReport(
        entries=[
            FilterApplicabilityEntry(field="geography.city", disposition="suppressed",
                                     reason="minimum_cohort_not_met"),
            FilterApplicabilityEntry(field="entity.type", disposition="applied"),
        ]
    )
    assert {e.disposition for e in report.entries} <= set(FILTER_DISPOSITIONS)


def test_barrel_exports_exploration():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './exploration-contract';" in index
