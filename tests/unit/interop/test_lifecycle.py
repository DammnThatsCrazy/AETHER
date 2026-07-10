"""Lifecycle FSM: exact parity with the TypeScript source of truth, legal
transition behavior, out-of-order tolerance, terminal immutability."""

from __future__ import annotations

import re
from pathlib import Path

from services.interop.lifecycle import (
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    LifecycleEngine,
)

REPO_ROOT = Path(__file__).parents[3]
TS_CONTRACT = REPO_ROOT / "packages" / "shared" / "interoperability.ts"


def _parse_ts_transitions() -> dict[str, tuple[str, ...]]:
    text = TS_CONTRACT.read_text()
    match = re.search(
        r"export const INTEROP_LEGAL_TRANSITIONS = \{(.*?)\n\} as const",
        text, re.S,
    )
    assert match, "INTEROP_LEGAL_TRANSITIONS not found in interoperability.ts"
    transitions: dict[str, tuple[str, ...]] = {}
    for line in match.group(1).splitlines():
        entry = re.match(r"\s*(\w+):\s*\[(.*?)\],", line)
        if entry:
            state = entry.group(1)
            targets = tuple(
                t.strip().strip("'") for t in entry.group(2).split(",") if t.strip()
            )
            transitions[state] = targets
    return transitions


def _parse_ts_terminal_states() -> tuple[str, ...]:
    text = TS_CONTRACT.read_text()
    match = re.search(
        r"INTEROP_TERMINAL_STATES:[^=]*=\s*\[(.*?)\]", text, re.S,
    )
    assert match
    return tuple(t.strip().strip("'") for t in match.group(1).split(",") if t.strip())


def test_python_fsm_matches_typescript_exactly():
    ts = _parse_ts_transitions()
    assert set(ts) == set(LEGAL_TRANSITIONS), (
        set(ts) ^ set(LEGAL_TRANSITIONS)
    )
    for state, targets in ts.items():
        assert set(targets) == set(LEGAL_TRANSITIONS[state]), (
            f"{state}: TS={sorted(targets)} PY={sorted(LEGAL_TRANSITIONS[state])}"
        )


def test_terminal_states_match_typescript():
    assert set(_parse_ts_terminal_states()) == set(TERMINAL_STATES)
    for terminal in TERMINAL_STATES:
        assert LEGAL_TRANSITIONS[terminal] == ()


def test_legal_transition_produces_append_only_record():
    result = LifecycleEngine.apply("t-a", "msg-1", "verified", "delivered", "2026-07-08T12:00:00Z")
    assert result.applied
    record = result.transition_record
    assert record["from_status"] == "verified"
    assert record["to_status"] == "delivered"
    assert record["execution_by_aether"] is False
    # Deterministic identity for replay safety.
    again = LifecycleEngine.apply("t-a", "msg-1", "verified", "delivered", "2026-07-08T12:00:00Z")
    assert again.transition_record["transition_id"] == record["transition_id"]


def test_late_lower_rank_evidence_attaches_without_regression():
    result = LifecycleEngine.apply("t-a", "msg-1", "delivered", "source_confirmed")
    assert not result.applied
    assert result.reason == "late_evidence_attached"
    assert result.new_status == "delivered"


def test_illegal_forward_jump_is_an_anomaly():
    result = LifecycleEngine.apply("t-a", "msg-1", "discovered", "delivered")
    assert not result.applied
    assert result.reason == "illegal_transition"


def test_terminal_states_are_immutable():
    for terminal in TERMINAL_STATES:
        result = LifecycleEngine.apply("t-a", "msg-1", terminal, "delivered")
        assert not result.applied
        assert result.reason == "terminal_state"


def test_retry_regression_is_legal():
    # delivery_failed -> delivery_pending is an explicit retry edge.
    result = LifecycleEngine.apply("t-a", "msg-1", "delivery_failed", "delivery_pending")
    assert result.applied


def test_reorg_is_a_legal_regression():
    result = LifecycleEngine.apply("t-a", "msg-1", "source_confirmed", "reorged")
    assert result.applied
