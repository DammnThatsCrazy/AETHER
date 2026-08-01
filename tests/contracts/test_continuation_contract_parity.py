"""TS <-> Python parity for the cross-device continuation contract (C1).

`packages/shared/continuation.ts` and `shared/continuation/models.py` are
hand-authored twins; this test fails on drift in the app-kind / source-client /
surface / sensitivity / freshness / selection-mode vocabularies or the field
sets of ContinuationContext / ContinuationCanonicalContext / ContinuationSummary
/ ResourceReference / ContinuationSelection. It also pins the composition rule:
ContinuationCanonicalContext composes the canonical ExplorationContextV1 by
reference (`filters`), never a second context language.

Wire fields are snake_case so the (camelCase-blind) scraper actually captures
them — see reports/mobile-productization/decision-log.md (D6).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.continuation.models import (  # noqa: E402
    CONTINUATION_APP_KINDS,
    CONTINUATION_FRESHNESS,
    CONTINUATION_SENSITIVITIES,
    CONTINUATION_SOURCE_CLIENTS,
    CONTINUATION_SURFACES,
    SELECTION_MODES,
    ContinuationCanonicalContext,
    ContinuationContext,
    ContinuationSelection,
    ContinuationSummary,
    ResourceReference,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "continuation.ts"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in continuation.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(
        rf"export interface {interface}(?:<[^>]+>)?\s*\{{(.*?)\n\}}", text, re.S
    )
    assert m, f"interface {interface} not found in continuation.ts"
    return set(re.findall(r"^\s{2}([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def test_app_kinds_parity():
    assert set(_const_array("continuationAppKinds")) == set(CONTINUATION_APP_KINDS)


def test_source_clients_parity():
    assert set(_const_array("continuationSourceClients")) == set(CONTINUATION_SOURCE_CLIENTS)


def test_surfaces_parity():
    assert set(_const_array("continuationSurfaces")) == set(CONTINUATION_SURFACES)


def test_sensitivities_parity():
    assert set(_const_array("continuationSensitivities")) == set(CONTINUATION_SENSITIVITIES)


def test_freshness_parity():
    assert set(_const_array("continuationFreshness")) == set(CONTINUATION_FRESHNESS)


def test_selection_modes_parity():
    assert set(_const_array("selectionModes")) == set(SELECTION_MODES)


def test_context_field_parity():
    ts_fields = _interface_fields("ContinuationContext")
    py_fields = set(ContinuationContext.model_fields.keys())
    assert ts_fields == py_fields, (
        f"ContinuationContext drift: TS-only={ts_fields - py_fields}, "
        f"PY-only={py_fields - ts_fields}"
    )


def test_canonical_context_field_parity():
    assert _interface_fields("ContinuationCanonicalContext") == set(
        ContinuationCanonicalContext.model_fields
    )


def test_summary_and_reference_parity():
    assert _interface_fields("ContinuationSummary") == set(ContinuationSummary.model_fields)
    assert _interface_fields("ResourceReference") == set(ResourceReference.model_fields)


def test_selection_field_parity():
    assert _interface_fields("ContinuationSelection") == set(
        ContinuationSelection.model_fields
    )


def test_context_composes_exploration_context():
    """A continuation may inline a compact ExplorationContextV1 by reference and
    round-trip it without a second context language."""
    from shared.exploration.models import ExplorationContextV1, TemporalSelection

    ctx = ExplorationContextV1(
        scope={"tenant_id": "t1", "surface": "graph"},
        temporal=TemporalSelection(mode="window", field="occurred_at", timezone="UTC"),
    )
    cont = ContinuationContext(
        id="c1",
        principal_id="p1",
        tenant_id="t1",
        app_kind="aether",
        source_client="desktop",
        surface="graph",
        canonical_context=ContinuationCanonicalContext(filters=ctx),
        summary=ContinuationSummary(title="Resume graph"),
        updated_at="2026-08-01T00:00:00Z",
    )
    rebuilt = ContinuationContext.model_validate(cont.model_dump(mode="json", exclude_none=True))
    assert rebuilt.version == "1"
    assert rebuilt.canonical_context.filters is not None
    assert rebuilt.canonical_context.filters.scope.tenant_id == "t1"


def test_barrel_exports_continuation():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './continuation';" in index
