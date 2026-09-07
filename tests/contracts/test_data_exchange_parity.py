"""TS <-> Python parity for the Data Exchange Plane contract.

``packages/shared/data-exchange.ts`` and
``services/data_exchange/contracts.py`` are hand-authored twins; this test
fails if their canonical vocabularies drift (directions, artifact statuses,
terminal statuses, ingress/egress formats, source types, classifications),
and if the TS module is not exported from the shared barrel.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.data_exchange.contracts import (  # noqa: E402
    DATA_ARTIFACT_STATUSES,
    DATA_ARTIFACT_TERMINAL_STATUSES,
    DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS,
    DATA_EXCHANGE_CLASSIFICATIONS,
    DATA_EXCHANGE_DIRECTIONS,
    DATA_EXCHANGE_EGRESS_FORMATS,
    DATA_EXCHANGE_INGRESS_FORMATS,
    DATA_EXCHANGE_SOURCE_TYPES,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "data-exchange.ts"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export const {name}\b[^=]*=\s*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in data-exchange.ts"
    return re.findall(r"'([a-z0-9_]+)'", m.group(1))


def test_directions_parity():
    ts = _const_array("dataExchangeDirections")
    assert ts == list(DATA_EXCHANGE_DIRECTIONS), (
        f"direction drift: TS={ts} PY={list(DATA_EXCHANGE_DIRECTIONS)}"
    )


def test_artifact_statuses_parity():
    ts = _const_array("dataArtifactStatuses")
    assert ts == list(DATA_ARTIFACT_STATUSES), (
        f"artifact status drift: TS={ts} PY={list(DATA_ARTIFACT_STATUSES)}"
    )


def test_terminal_statuses_parity():
    ts = _const_array("dataArtifactTerminalStatuses")
    assert ts == list(DATA_ARTIFACT_TERMINAL_STATUSES), (
        f"terminal status drift: TS={ts} PY={list(DATA_ARTIFACT_TERMINAL_STATUSES)}"
    )


def test_ingress_formats_parity():
    ts = _const_array("dataExchangeIngressFormats")
    assert ts == list(DATA_EXCHANGE_INGRESS_FORMATS), (
        f"ingress format drift: TS={ts} PY={list(DATA_EXCHANGE_INGRESS_FORMATS)}"
    )


def test_egress_formats_parity():
    ts = _const_array("dataExchangeEgressFormats")
    assert ts == list(DATA_EXCHANGE_EGRESS_FORMATS), (
        f"egress format drift: TS={ts} PY={list(DATA_EXCHANGE_EGRESS_FORMATS)}"
    )


def test_source_types_parity():
    ts = _const_array("dataExchangeSourceTypes")
    assert ts == list(DATA_EXCHANGE_SOURCE_TYPES), (
        f"source-type drift: TS={ts} PY={list(DATA_EXCHANGE_SOURCE_TYPES)}"
    )


def test_classifications_parity():
    ts = _const_array("dataExchangeClassifications")
    assert ts == list(DATA_EXCHANGE_CLASSIFICATIONS), (
        f"classification drift: TS={ts} PY={list(DATA_EXCHANGE_CLASSIFICATIONS)}"
    )


def test_blocked_classifications_parity():
    ts = _const_array("dataExchangeBlockedClassifications")
    assert ts == list(DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS), (
        f"blocked-classification drift: TS={ts} PY={list(DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS)}"
    )


def test_terminal_statuses_are_valid_statuses():
    assert set(DATA_ARTIFACT_TERMINAL_STATUSES) <= set(DATA_ARTIFACT_STATUSES), (
        "every terminal artifact status must be a declared status"
    )


def test_blocked_classifications_are_valid_classifications():
    assert set(DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS) <= set(DATA_EXCHANGE_CLASSIFICATIONS), (
        "every blocked classification must be a declared classification"
    )


def test_barrel_exports_data_exchange_contract():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './data-exchange';" in index
