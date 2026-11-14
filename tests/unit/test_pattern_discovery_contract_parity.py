"""TS <-> Python parity for the pattern discovery vocabularies.

``packages/shared/pattern-discovery.ts`` is the hand-authored twin of
``services/api/intelligence/pattern_discovery/contracts.py``. This fails on
drift in either direction for: pattern kinds (and their order), confidence
caps, lifecycle statuses, verdicts and the verdict -> status map. The Python
side is imported (the contracts module has no heavy dependencies); the TS side
is parsed as text.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
TS = (REPO_ROOT / "packages" / "shared" / "pattern-discovery.ts").read_text(encoding="utf-8")
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from intelligence.pattern_discovery import contracts  # noqa: E402


def _ts_tuple(name: str) -> list[str]:
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", TS, re.S)
    assert match, f"{name} not found in pattern-discovery.ts"
    return re.findall(r"'([a-z_]+)'", match.group(1))


def _ts_record(name: str) -> dict[str, str]:
    match = re.search(rf"export const {name}:[^=]*= \{{(.*?)\}};", TS, re.S)
    assert match, f"{name} not found in pattern-discovery.ts"
    return dict(re.findall(r"([a-z_]+):\s*'?([a-z_0-9.]+)'?", match.group(1)))


def test_kinds_match_in_order():
    assert _ts_tuple("PATTERN_KINDS") == list(contracts.PATTERN_KINDS)


def test_confidence_caps_match():
    ts = {k: float(v) for k, v in _ts_record("PATTERN_CONFIDENCE_CAPS").items()}
    assert ts == contracts.CONFIDENCE_CAPS


def test_statuses_match():
    assert _ts_tuple("PATTERN_STATUSES") == list(contracts.PATTERN_STATUSES)


def test_verdicts_and_their_statuses_match():
    assert _ts_tuple("PATTERN_VERDICTS") == list(contracts.VERDICT_STATUS)
    assert _ts_record("PATTERN_VERDICT_STATUS") == contracts.VERDICT_STATUS
