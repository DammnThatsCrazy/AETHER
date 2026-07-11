"""TS <-> Python parity for the Tenant Import Engine contract.

`packages/shared/imports.ts` and `services/imports/contracts.py` are
hand-authored twins; this test fails if their canonical vocabularies drift
(statuses, primitives, transforms, column types), and if the TS module is not
exported from the shared barrel.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.imports.contracts import (  # noqa: E402
    IMPORT_COLUMN_TYPES,
    IMPORT_PRIMITIVE_FIELDS,
    IMPORT_PRIMITIVES,
    IMPORT_STATUSES,
    IMPORT_TERMINAL_STATUSES,
    IMPORT_TRANSFORMS,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "imports.ts"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export const {name}\b[^=]*=\s*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in imports.ts"
    return re.findall(r"'([a-z0-9_]+)'", m.group(1))


def test_statuses_parity():
    ts = _const_array("importStatuses")
    assert ts == list(IMPORT_STATUSES), (
        f"import status drift: TS={ts} PY={list(IMPORT_STATUSES)}"
    )


def test_primitives_parity():
    ts = _const_array("importPrimitives")
    assert ts == list(IMPORT_PRIMITIVES), (
        f"primitive drift: TS={ts} PY={list(IMPORT_PRIMITIVES)}"
    )


def test_transforms_parity():
    ts = _const_array("importTransforms")
    assert set(ts) == set(IMPORT_TRANSFORMS), (
        f"transform drift: TS-only={set(ts) - set(IMPORT_TRANSFORMS)}, "
        f"PY-only={set(IMPORT_TRANSFORMS) - set(ts)}"
    )


def test_column_types_parity():
    ts = _const_array("importColumnTypes")
    assert set(ts) == set(IMPORT_COLUMN_TYPES), (
        f"column-type drift: TS-only={set(ts) - set(IMPORT_COLUMN_TYPES)}, "
        f"PY-only={set(IMPORT_COLUMN_TYPES) - set(ts)}"
    )


def test_terminal_statuses_are_valid_statuses():
    assert IMPORT_TERMINAL_STATUSES <= set(IMPORT_STATUSES), (
        "every terminal status must be a declared status"
    )


def test_primitive_fields_cover_every_primitive():
    assert set(IMPORT_PRIMITIVE_FIELDS) == set(IMPORT_PRIMITIVES), (
        "every primitive must have a field list (and vice-versa)"
    )
    for primitive, fields in IMPORT_PRIMITIVE_FIELDS.items():
        assert fields, f"primitive {primitive!r} has no target fields"


def test_barrel_exports_imports_contract():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './imports';" in index
