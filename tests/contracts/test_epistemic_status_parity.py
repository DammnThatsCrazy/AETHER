"""TS <-> Python parity for the consolidated epistemic-status vocabulary.

``packages/shared/epistemic-status.ts`` and
``shared/contracts_models/epistemic.py`` are hand-authored twins (the
``graph-contract.ts`` / ``dimension-state.ts`` hand-mirror pattern). This test
fails on vocabulary drift (values, order), if the TS module leaves the barrel,
and if any consolidated mapping table drifts from its fragmented source
vocabulary (``OBSERVATION_CLASS_VALUES``, ``CAUSALITY_CLASSES``,
``LIFECYCLE_STATE_VALUES``, ``ResultStatus``, ``ConflictStatus``,
``PROJECTION_SECTION_STATES``).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.computation.result import ResultStatus  # noqa: E402
from shared.contracts_models.epistemic import (  # noqa: E402
    CAUSALITY_CLASS_TO_EPISTEMIC,
    CONFLICT_STATUS_TO_EPISTEMIC,
    EPISTEMIC_STATUS_VALUES,
    EpistemicStatus,
    LIFECYCLE_STATE_TO_EPISTEMIC,
    OBSERVATION_CLASS_TO_EPISTEMIC,
    PROJECTION_SECTION_STATE_TO_EPISTEMIC,
    RESULT_STATUS_TO_EPISTEMIC,
)
from shared.graph.edge_properties import CAUSALITY_CLASSES  # noqa: E402
from shared.graph.graph_contract import (  # noqa: E402
    LIFECYCLE_STATE_VALUES,
    OBSERVATION_CLASS_VALUES,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    PROJECTION_SECTION_STATES,
)
from services.identity.models import ConflictStatus  # noqa: E402

TS_PATH = REPO_ROOT / "packages" / "shared" / "epistemic-status.ts"

# The canonical 15 values (from the Risk360/Fraud360 convergence plan).
_CANONICAL_VALUES = {
    "observed",
    "verified",
    "resolved",
    "derived",
    "inferred",
    "predicted",
    "correlated",
    "attributed",
    "causally_supported",
    "disputed",
    "superseded",
    "stale",
    "unknown",
    "unavailable",
    "not_applicable",
}

# Every mapping table and the source vocabulary it must cover exactly.
_MAPPING_TABLES = (
    (OBSERVATION_CLASS_TO_EPISTEMIC, OBSERVATION_CLASS_VALUES),
    (CAUSALITY_CLASS_TO_EPISTEMIC, CAUSALITY_CLASSES),
    (LIFECYCLE_STATE_TO_EPISTEMIC, LIFECYCLE_STATE_VALUES),
    (RESULT_STATUS_TO_EPISTEMIC, {s.value for s in ResultStatus}),
    (CONFLICT_STATUS_TO_EPISTEMIC, {s.value for s in ConflictStatus}),
    (PROJECTION_SECTION_STATE_TO_EPISTEMIC, set(PROJECTION_SECTION_STATES)),
)


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in epistemic-status.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def test_canonical_values_are_exactly_the_plan_set():
    assert set(EPISTEMIC_STATUS_VALUES) == _CANONICAL_VALUES, (
        f"epistemic status drift: extra={set(EPISTEMIC_STATUS_VALUES) - _CANONICAL_VALUES}, "
        f"missing={_CANONICAL_VALUES - set(EPISTEMIC_STATUS_VALUES)}"
    )
    assert len(EPISTEMIC_STATUS_VALUES) == 15


def test_enum_members_and_values_agree():
    assert [m.value for m in EpistemicStatus] == list(EPISTEMIC_STATUS_VALUES)
    assert {m.value for m in EpistemicStatus} == _CANONICAL_VALUES


def test_ts_parity_values_and_order():
    ts_values = _const_array("EPISTEMIC_STATUSES")
    assert ts_values == list(EPISTEMIC_STATUS_VALUES), (
        "EPISTEMIC_STATUSES differs from EPISTEMIC_STATUS_VALUES in values or order"
    )


def test_ts_parity_type_and_count():
    text = TS_PATH.read_text(encoding="utf-8")
    assert "export type EpistemicStatus = typeof EPISTEMIC_STATUSES[number];" in text
    assert len(_const_array("EPISTEMIC_STATUSES")) == 15


def test_barrel_exports_epistemic_status():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './epistemic-status';" in index


def test_mapping_tables_cover_their_source_vocabularies():
    """Every fragmented value has a canonical status; no table drifted."""
    for table, source_values in _MAPPING_TABLES:
        assert set(table) == set(source_values), (
            f"{table.__name__} keys drifted from its source vocabulary: "
            f"extra={set(table) - set(source_values)}, "
            f"missing={set(source_values) - set(table)}"
        )


def test_mapping_tables_values_are_canonical_members():
    for table, _ in _MAPPING_TABLES:
        for source_value, status in table.items():
            assert isinstance(status, EpistemicStatus), (
                f"{table.__name__}[{source_value!r}] is not an EpistemicStatus member"
            )
