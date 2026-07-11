"""TS <-> Python parity for the dimension-state contract.

`packages/shared/dimension-state.ts` and `shared/dimension_state.py` are
hand-authored twins; this test fails if they drift (states, reason codes, or
precedence ordering), and if the TS module is not exported from the barrel.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.dimension_state import (  # noqa: E402
    DIMENSION_REASON_CODES,
    DIMENSION_STATE_PRECEDENCE,
    DIMENSION_STATES,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "dimension-state.ts"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in dimension-state.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def test_states_parity():
    ts_states = _const_array("dimensionStates")
    assert set(ts_states) == set(DIMENSION_STATES), (
        f"dimension state drift: TS-only={set(ts_states) - set(DIMENSION_STATES)}, "
        f"PY-only={set(DIMENSION_STATES) - set(ts_states)}"
    )


def test_reason_codes_parity():
    ts_codes = _const_array("dimensionReasonCodes")
    assert set(ts_codes) == set(DIMENSION_REASON_CODES), (
        f"reason-code drift: TS-only={set(ts_codes) - set(DIMENSION_REASON_CODES)}, "
        f"PY-only={set(DIMENSION_REASON_CODES) - set(ts_codes)}"
    )


def test_precedence_parity_and_order():
    ts_prec = _const_array("dimensionStatePrecedence")
    # Same order in both languages (worst-wins rollup must agree).
    assert ts_prec == list(DIMENSION_STATE_PRECEDENCE), (
        "precedence ordering differs between TS and Python"
    )


def test_precedence_covers_every_state():
    assert set(DIMENSION_STATE_PRECEDENCE) == set(DIMENSION_STATES), (
        "every dimension state must appear exactly once in the precedence order"
    )
    assert len(DIMENSION_STATE_PRECEDENCE) == len(DIMENSION_STATES)


def test_barrel_exports_dimension_state():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './dimension-state';" in index
