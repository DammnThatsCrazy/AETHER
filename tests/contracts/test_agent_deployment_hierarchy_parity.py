"""Parity: agent identity hierarchy, packages/shared/agent-deployment.ts <-> actions/agent/identity_hierarchy.py."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))

TS = (ROOT / "packages/shared/agent-deployment.ts").read_text(encoding="utf-8")


def _array(name: str) -> list[str]:
    m = re.search(rf"export const {name}\b[^=]*=\s*\[(.*?)\]\s*as const", TS, re.DOTALL)
    assert m, name
    return re.findall(r"'([a-z_]+)'", m.group(1))


def test_levels_match():
    from actions.agent.identity_hierarchy import HIERARCHY_LEVELS

    assert _array("agentIdentityHierarchyLevels") == list(HIERARCHY_LEVELS)


def test_logical_identity_levels_match():
    from actions.agent.identity_hierarchy import LOGICAL_IDENTITY_LEVELS

    assert set(_array("agentLogicalIdentityLevels")) == set(LOGICAL_IDENTITY_LEVELS)


def test_edges_match():
    from actions.agent.identity_hierarchy import HIERARCHY_EDGES

    m = re.search(r"export const agentIdentityHierarchyEdges = \[(.*?)\] as const", TS, re.DOTALL)
    ts_edges = re.findall(r"from: '(\w+)', edge: '(\w+)', to: '(\w+)'", m.group(1))
    assert ts_edges == list(HIERARCHY_EDGES)


def test_id_columns_match():
    from actions.agent.identity_hierarchy import HIERARCHY_ID_COLUMNS

    m = re.search(r"agentIdentityHierarchyIdColumns[^=]*=\s*\{(.*?)\};", TS, re.DOTALL)
    assert dict(re.findall(r"(\w+): '(\w+)'", m.group(1))) == HIERARCHY_ID_COLUMNS


def test_non_identity_evidence_fields_match():
    from actions.agent.identity_hierarchy import NON_IDENTITY_EVIDENCE_FIELDS

    assert set(_array("agentNonIdentityEvidenceFields")) == set(NON_IDENTITY_EVIDENCE_FIELDS)
