"""Intelligence Projection anti-redefinition gate (P0.4, group 11).

The shared projection contracts MUST reuse the canonical primitives rather than
re-declare them: EntityRef, EvidenceRef, PageRequest, PageInfo and
TimeRangeFilter are owned by ``services/operational_intelligence/models.py``
(Python) and by ``./entities`` + ``./operational-intelligence`` (TS). This test
reads the hand-authored ``shared/intelligence_projections`` sources (excluding
the generated registry) and the TS contract file, and fails closed if anyone
reintroduces a duplicate definition.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PROJECTIONS_DIR = (
    REPO_ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "shared"
    / "intelligence_projections"
)
TS_CONTRACTS = REPO_ROOT / "packages" / "shared" / "intelligence-projection.ts"

# Canonical primitives that MUST be imported, never re-declared.
_REUSED_PRIMITIVES = (
    "EntityRef",
    "EvidenceRef",
    "PageRequest",
    "PageInfo",
    "TimeRangeFilter",
)


def _hand_authored_py_sources() -> list[Path]:
    return sorted(
        p
        for p in BACKEND_PROJECTIONS_DIR.glob("*.py")
        if p.name != "generated_registry.py"
    )


def test_no_shared_py_source_redeclares_canonical_primitives() -> None:
    sources = _hand_authored_py_sources()
    assert sources, "no hand-authored shared/intelligence_projections sources found"

    for path in sources:
        source = path.read_text(encoding="utf-8")
        for name in _REUSED_PRIMITIVES:
            assert not re.search(
                rf"^\s*class\s+{name}\b", source, flags=re.MULTILINE
            ), f"{path.name} re-declares class {name}"
            assert not re.search(
                rf"^\s*def\s+{name}\b", source, flags=re.MULTILINE
            ), f"{path.name} re-declares def {name}"


def test_contracts_py_imports_primitives_from_operational_intelligence() -> None:
    contracts = (BACKEND_PROJECTIONS_DIR / "contracts.py").read_text(encoding="utf-8")

    assert (
        "from services.operational_intelligence.models import" in contracts
    ), "contracts.py must import the canonical primitives from services.operational_intelligence.models"

    for name in _REUSED_PRIMITIVES:
        assert re.search(
            rf"^\s*{name},\s*$", contracts, flags=re.MULTILINE
        ), f"contracts.py does not import {name} from operational_intelligence.models"


def test_ts_contract_does_not_redeclare_primitives() -> None:
    source = TS_CONTRACTS.read_text(encoding="utf-8")

    for name in ("EntityRef", "PageRequest", "EvidenceRef", "TimeRangeFilter"):
        assert not re.search(
            rf"\binterface\s+{name}\b", source
        ), f"intelligence-projection.ts re-declares interface {name}"


def test_ts_contract_imports_primitives_from_canonical_modules() -> None:
    source = TS_CONTRACTS.read_text(encoding="utf-8")

    assert "from './entities'" in source
    assert "from './operational-intelligence'" in source
    # SectionState / ProjectionId must derive from the generated registry vocab.
    assert "intelligenceProjectionSectionStates" in source
    assert "intelligenceProjectionIds" in source
