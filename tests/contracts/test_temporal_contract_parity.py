"""TS <-> Python parity for the canonical temporal contract.

`packages/shared/temporal.ts` and `shared/temporal/` are hand-authored twins;
this test fails on drift in reason codes, temporal states, timezone/clock
sources, precisions, authorities, or DST policies — and if the TS module is
not exported from the barrel. It also pins the Python `TemporalEnvelope`
mirror to the TS `TemporalEnvelope` interface in `graph-contract.ts`
(closing the parity gap documented by `UNIVERSAL_GRAPH_CONTRACT.md`).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.temporal.authority import TEMPORAL_AUTHORITIES  # noqa: E402
from shared.temporal.envelope import (  # noqa: E402
    CLOCK_SOURCES,
    TEMPORAL_PRECISIONS,
    TEMPORAL_STATES,
    TIME_ZONE_SOURCES,
    EventTemporalEnvelope,
    TemporalEnvelope,
)
from shared.temporal.instant import TEMPORAL_REASON_CODES  # noqa: E402
from shared.temporal.windows import GAP_POLICIES, OVERLAP_POLICIES  # noqa: E402

TS_PATH = REPO_ROOT / "packages" / "shared" / "temporal.ts"
GRAPH_CONTRACT_TS = REPO_ROOT / "packages" / "shared" / "graph-contract.ts"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in temporal.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _interface_fields(path: Path, interface: str) -> set[str]:
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"export interface {interface}\s*\{{(.*?)\n\}}", text, re.S)
    assert m, f"interface {interface} not found in {path.name}"
    return set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def test_reason_codes_parity():
    assert set(_const_array("temporalReasonCodes")) == set(TEMPORAL_REASON_CODES)


def test_temporal_states_parity():
    assert set(_const_array("temporalStates")) == set(TEMPORAL_STATES)


def test_time_zone_sources_parity():
    assert set(_const_array("timeZoneSources")) == set(TIME_ZONE_SOURCES)


def test_clock_sources_parity():
    assert set(_const_array("clockSources")) == set(CLOCK_SOURCES)


def test_precisions_parity():
    assert set(_const_array("temporalPrecisions")) == set(TEMPORAL_PRECISIONS)


def test_authorities_parity():
    assert set(_const_array("temporalAuthorities")) == set(TEMPORAL_AUTHORITIES)


def test_dst_policy_parity():
    assert set(_const_array("dstGapPolicies")) == set(GAP_POLICIES)
    assert set(_const_array("dstOverlapPolicies")) == set(OVERLAP_POLICIES)


def test_event_envelope_field_parity():
    ts_fields = _interface_fields(TS_PATH, "EventTemporalEnvelope")
    py_fields = set(EventTemporalEnvelope.model_fields.keys())
    assert ts_fields == py_fields, (
        f"EventTemporalEnvelope drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_bitemporal_envelope_mirrors_graph_contract():
    ts_fields = _interface_fields(GRAPH_CONTRACT_TS, "TemporalEnvelope")
    py_fields = set(TemporalEnvelope.model_fields.keys())
    assert ts_fields == py_fields, (
        f"TemporalEnvelope drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_barrel_exports_temporal():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './temporal';" in index
