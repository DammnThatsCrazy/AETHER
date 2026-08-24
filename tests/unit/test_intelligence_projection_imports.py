"""Intelligence Projection anti-redefinition gate (P0.4, group 11).

The shared projection contracts MUST reuse the canonical primitives rather than
re-declare them. Python ownership lives in
``services/operational_intelligence/models.py`` (EvidenceRef, PageRequest,
PageInfo, TimeRangeFilter); TS ownership lives in ``./operational-intelligence``
(PageRequest, EvidenceRef, TimeRangeFilter, PageInfo). ``EntityRef`` is no longer
referenced by the contracts at all (replaced by the projection-plane
``ProjectionSubject``) — it must simply never be re-declared.

The gate scans every hand-authored source under
``shared/intelligence_projections/**`` (recursively, excluding the generated
registry and ``__pycache__``) for ``class``/``def``/assignment/TypeAlias/type
re-declarations, and ``packages/shared/intelligence-projection.ts`` for
``interface``/``type``/``declare`` re-declarations, using word-boundary regexes
so derived names like ``ProjectionSubjectKind`` or ``EntityRefLike`` never
false-positive. Negative fixtures at the bottom prove the gate would catch a
reintroduced duplicate definition.
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
_PY_PRIMITIVES = (
    "EntityRef",
    "EvidenceRef",
    "PageRequest",
    "PageInfo",
    "TimeRangeFilter",
)
_TS_PRIMITIVES = _PY_PRIMITIVES

# The primitives the contracts actually use — each must come from the canonical
# module. EntityRef is intentionally absent: the projection plane uses
# ProjectionSubject, so EntityRef is not imported (only required to never be
# re-declared).
_PY_REQUIRED_IMPORTS = ("EvidenceRef", "PageRequest", "PageInfo", "TimeRangeFilter")
_TS_REQUIRED_IMPORTS = ("EvidenceRef", "PageRequest", "PageInfo", "TimeRangeFilter")


def _hand_authored_py_sources() -> list[Path]:
    return sorted(
        p
        for p in BACKEND_PROJECTIONS_DIR.rglob("*.py")
        if p.name != "generated_registry.py" and "__pycache__" not in p.parts
    )


def _py_redeclared(source: str, name: str) -> bool:
    """True if ``source`` re-declares ``name`` in any Python form."""
    return re.search(
        rf"^\s*(?:class|def)\s+{name}\b"  # class X( ... / def X( ...
        rf"|^\s*{name}\s*="  # X = ...
        rf"|^\s*{name}\s*:\s*TypeAlias\s*="  # X: TypeAlias = ...
        rf"|^\s*type\s+{name}\b",  # type X = ... (PEP 695)
        source,
        flags=re.MULTILINE,
    ) is not None


def _ts_redeclared(source: str, name: str) -> bool:
    """True if ``source`` re-declares ``name`` as an interface, type, or declare."""
    return (
        re.search(rf"\b(?:interface|type|declare)\s+{name}\b", source) is not None
    )


def _ts_import_from(source: str, module: str) -> str:
    match = re.search(r"import[^;]*?from\s+'\./" + re.escape(module) + r"'", source)
    return match.group(0) if match else ""


def _py_models_import_block(source: str) -> str:
    match = re.search(
        r"from services\.operational_intelligence\.models import \(([^)]*)\)",
        source,
        flags=re.DOTALL,
    )
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Positive gate — the CURRENT (correct) files must pass
# ---------------------------------------------------------------------------

def test_no_py_source_redeclares_canonical_primitives() -> None:
    sources = _hand_authored_py_sources()
    assert sources, "no hand-authored shared/intelligence_projections sources found"

    for path in sources:
        source = path.read_text(encoding="utf-8")
        for name in _PY_PRIMITIVES:
            assert not _py_redeclared(source, name), f"{path.name} re-declares {name}"


def test_used_py_primitives_come_from_operational_intelligence_models() -> None:
    contracts = (BACKEND_PROJECTIONS_DIR / "contracts.py").read_text(encoding="utf-8")

    block = _py_models_import_block(contracts)
    assert block, (
        "contracts.py has no 'from services.operational_intelligence.models import (...)' block"
    )

    for name in _PY_REQUIRED_IMPORTS:
        assert re.search(
            rf"^\s*{name},\s*$", block, flags=re.MULTILINE
        ), f"contracts.py does not import {name} from operational_intelligence.models"


def test_ts_contract_does_not_redeclare_primitives() -> None:
    source = TS_CONTRACTS.read_text(encoding="utf-8")

    for name in _TS_PRIMITIVES:
        assert not _ts_redeclared(source, name), (
            f"intelligence-projection.ts re-declares {name}"
        )


def test_ts_contract_imports_used_primitives_from_operational_intelligence() -> None:
    source = TS_CONTRACTS.read_text(encoding="utf-8")

    import_line = _ts_import_from(source, "operational-intelligence")
    assert import_line, (
        "intelligence-projection.ts has no './operational-intelligence' import"
    )

    for name in _TS_REQUIRED_IMPORTS:
        assert re.search(
            rf"\b{name}\b", import_line
        ), f"{name} not imported from ./operational-intelligence"

    # The typed vocabularies must derive from the generated registry, never be
    # re-declared by hand.
    assert "intelligenceProjectionSectionStates" in source
    assert "intelligenceProjectionIds" in source
    assert "intelligenceProjectionImplementationStates" in source
    assert "intelligenceProjectionSubjectKinds" in source


# ---------------------------------------------------------------------------
# Negative fixtures — prove the gate catches reintroduced duplicates
# ---------------------------------------------------------------------------

def test_py_gate_catches_class_redeclaration() -> None:
    assert _py_redeclared("class EntityRef(ContractModel):\n    kind: str\n", "EntityRef")
    assert _py_redeclared("class PageRequest(ContractModel):\n    cursor: str\n", "PageRequest")


def test_py_gate_catches_constructor_like_def() -> None:
    assert _py_redeclared("def PageRequest(cursor=None):\n    ...\n", "PageRequest")
    assert _py_redeclared("def TimeRangeFilter(from_=None):\n    ...\n", "TimeRangeFilter")


def test_py_gate_catches_assignment_redeclaration() -> None:
    assert _py_redeclared("EvidenceRef = dict\n", "EvidenceRef")
    assert _py_redeclared("PageInfo = {}\n", "PageInfo")


def test_py_gate_catches_typealias_redeclaration() -> None:
    assert _py_redeclared("PageRequest: TypeAlias = dict\n", "PageRequest")
    assert _py_redeclared("TimeRangeFilter: TypeAlias = dict\n", "TimeRangeFilter")


def test_py_gate_catches_pep695_type_alias() -> None:
    assert _py_redeclared("type EvidenceRef = dict\n", "EvidenceRef")


def test_py_gate_does_not_false_positive_on_import_block_or_derived_literals() -> None:
    import_block = (
        "from services.operational_intelligence.models import (\n"
        "    ContractModel,\n"
        "    EvidenceRef,\n"
        "    PageInfo,\n"
        "    PageRequest,\n"
        "    TimeRangeFilter,\n"
        ")\n"
    )
    derived = (
        "SectionState = Literal[tuple(PROJECTION_SECTION_STATES)]\n"
        "ProjectionId = Literal[tuple(INTELLIGENCE_PROJECTION_IDS)]\n"
        "ProjectionSubjectKind = Literal[tuple(sorted({...}))]\n"
    )
    for name in _PY_PRIMITIVES:
        assert not _py_redeclared(import_block, name), (
            f"import block false-flagged as redefinition of {name}"
        )
        assert not _py_redeclared(derived, name), (
            f"derived literal false-flagged as redefinition of {name}"
        )


def test_ts_gate_catches_interface_redeclaration() -> None:
    assert _ts_redeclared("export interface EntityRef { kind: string; id: string; }", "EntityRef")
    assert _ts_redeclared("export interface PageRequest { cursor?: string; }", "PageRequest")


def test_ts_gate_catches_type_alias_redeclaration() -> None:
    assert _ts_redeclared("export type EvidenceRef = { id: string };", "EvidenceRef")
    assert _ts_redeclared("export type TimeRangeFilter = { from?: string };", "TimeRangeFilter")


def test_ts_gate_catches_declare_redeclaration() -> None:
    assert _ts_redeclared("declare interface PageInfo { hasNextPage: boolean; }", "PageInfo")
    assert _ts_redeclared("declare type EntityRef = { kind: string };", "EntityRef")


def test_ts_gate_does_not_false_positive_on_derived_or_similar_names() -> None:
    derived = (
        "export type ProjectionSubjectKind = { [K in keyof typeof "
        "intelligenceProjectionDefinitions]: string }[keyof typeof "
        "intelligenceProjectionDefinitions];"
    )
    assert not _ts_redeclared(derived, "EntityRef")
    assert not _ts_redeclared(derived, "PageRequest")

    assert not _ts_redeclared("export type EntityRefLike = { kind: string };", "EntityRef")
    assert not _ts_redeclared("export type PageRequestEnvelope = { cursor?: string };", "PageRequest")
