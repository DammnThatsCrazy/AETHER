"""Unit tests for the generated event-registry table's per-event metadata columns.

``gen_event_table_md`` (scripts/generate_contracts.py) renders
docs/_generated/event-registry-table.md from packages/shared/contracts/
event-registry.json. Prose source-of-truth docs (e.g. EVENT_REGISTRY.md)
re-point readers at this generated table as the authoritative per-event list, so
the table's columns are load-bearing: required purposes, privacy class, and
retention class must all survive regeneration exactly as declared on the spine.
These tests pin that contract without depending on the live generated file.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_JSON = ROOT / "packages" / "shared" / "contracts" / "event-registry.json"
GEN_SCRIPT = ROOT / "scripts" / "generate_contracts.py"


def _load_module(script: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_module(GEN_SCRIPT, "generate_contracts")


@pytest.fixture(scope="module")
def event_reg():
    return json.loads(REGISTRY_JSON.read_text())


def _parse_table(md: str) -> tuple[str, str, list[list[str]]]:
    """Return (header, separator, data-rows) from a generated markdown table."""
    lines = [ln for ln in md.splitlines() if ln.startswith("|")]
    assert len(lines) >= 3, "expected header + separator + data rows"
    header, separator = lines[0], lines[1]
    rows = [ln for ln in lines[2:]]
    return header, separator, rows


def test_header_carries_all_six_metadata_columns(gen, event_reg):
    md = gen.gen_event_table_md(event_reg)
    header, separator, _ = _parse_table(md)
    assert header == (
        "| Event Type | Family | Required Purposes | Privacy Class | Retention Class | Description |"
    )
    assert separator == "|---|---|---|---|---|---|"


def test_one_row_per_registry_event_in_registry_order(gen, event_reg):
    md = gen.gen_event_table_md(event_reg)
    _, _, rows = _parse_table(md)
    assert len(rows) == len(event_reg["events"]) == 403
    # type token extracted from each row (strip a trailing *(deprecated)* marker)
    types = []
    for row in rows:
        m = re.match(r"\s*`([a-z0-9_]+)`", row.strip("|"))
        assert m, f"unparseable row: {row!r}"
        types.append(m.group(1))
    assert types == [e["type"] for e in event_reg["events"]]


def test_every_row_reproduces_privacy_and_retention_from_the_spine(gen, event_reg):
    """Privacy class + retention class are the load-bearing WS-A7 columns: each
    must be present and exactly match the registry for all 403 events."""
    md = gen.gen_event_table_md(event_reg)
    _, _, rows = _parse_table(md)
    assert len(rows) == len(event_reg["events"])
    missing = []
    for row, e in zip(rows, event_reg["events"]):
        cells = [c.strip() for c in row.strip("|").split("|")]
        # cells: [type(+marker), family, purposes, privacy, retention, description]
        privacy, retention = cells[3], cells[4]
        if privacy != e.get("privacyClass", "") or retention != e.get("retentionClass", ""):
            missing.append((e["type"], privacy, retention, e.get("privacyClass"), e.get("retentionClass")))
    assert not missing, f"privacy/retention drift ({len(missing)}): {missing[:5]}"


def test_required_purposes_column_matches_registry(gen, event_reg):
    md = gen.gen_event_table_md(event_reg)
    _, _, rows = _parse_table(md)
    for row, e in zip(rows, event_reg["events"]):
        cells = [c.strip() for c in row.strip("|").split("|")]
        purposes = cells[2]
        expected = ", ".join(e.get("requiredPurposes", []) or ["—"])
        assert purposes == expected, f"{e['type']}: {purposes!r} != {expected!r}"


def test_deprecated_rows_carry_the_deprecation_marker(gen, event_reg):
    md = gen.gen_event_table_md(event_reg)
    _, _, rows = _parse_table(md)
    for row, e in zip(rows, event_reg["events"]):
        first_cell = row.strip("|").split("|")[0].strip()
        marked = "*(deprecated)*" in first_cell
        assert marked == (e.get("status") == "deprecated"), e["type"]


def test_title_reports_total_and_contract_version(gen, event_reg):
    md = gen.gen_event_table_md(event_reg)
    assert (
        f"# Aether Event Registry ({len(event_reg['events'])} types, "
        f"contract v{event_reg['contractVersion']})" in md
    )
