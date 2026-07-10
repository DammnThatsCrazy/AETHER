"""Order/position state machine correctness: legal transitions, illegal
rejection, out-of-order tolerance, terminal finality."""

from __future__ import annotations

from services.derivatives.state_machines import (
    ORDER_LEGAL_TRANSITIONS,
    ORDER_TERMINAL_STATES,
    POSITION_LEGAL_TRANSITIONS,
    POSITION_TERMINAL_STATES,
    OrderStateMachine,
    PositionStateMachine,
)


def test_every_order_transition_target_is_a_known_state():
    for state, targets in ORDER_LEGAL_TRANSITIONS.items():
        assert state in ORDER_LEGAL_TRANSITIONS
        for target in targets:
            assert target in ORDER_LEGAL_TRANSITIONS, f"{state} -> {target}"


def test_every_position_transition_target_is_a_known_state():
    for state, targets in POSITION_LEGAL_TRANSITIONS.items():
        for target in targets:
            assert target in POSITION_LEGAL_TRANSITIONS, f"{state} -> {target}"


def test_order_happy_path_applies():
    machine = OrderStateMachine
    status = "pending"
    for step in ("open", "partially_filled", "filled"):
        result = machine.apply(status, step)
        assert result.applied, f"{status} -> {step}: {result.reason}"
        status = result.new_status
    assert status == "filled"


def test_order_terminal_states_are_final_except_unknown_recovery():
    for terminal in ORDER_TERMINAL_STATES:
        for target in ORDER_LEGAL_TRANSITIONS:
            if target in ("unknown",):
                continue
            result = OrderStateMachine.apply(terminal, target)
            assert not result.applied, f"{terminal} -> {target} must not apply"


def test_order_out_of_order_evidence_is_stale_not_error():
    # 'filled' already recorded; a late 'open' update arrives from the venue.
    result = OrderStateMachine.apply("filled", "open")
    assert result.applied is False
    assert result.reason == "stale_out_of_order"
    assert result.new_status == "filled"


def test_order_illegal_transition_rejected():
    result = OrderStateMachine.apply("pending", "partially_filled")
    assert result.applied  # legal
    result = OrderStateMachine.apply("cancelled", "filled")
    assert not result.applied


def test_order_unknown_recovery_accepts_any_evidence():
    for target in ("pending", "open", "filled", "cancelled"):
        result = OrderStateMachine.apply("unknown", target)
        assert result.applied, target


def test_position_lifecycle_paths():
    machine = PositionStateMachine
    # open -> reducing -> closed
    assert machine.apply("open", "reducing").applied
    assert machine.apply("reducing", "closed").applied
    # open -> liquidating -> liquidated
    assert machine.apply("open", "liquidating").applied
    assert machine.apply("liquidating", "liquidated").applied
    # settlement flow
    assert machine.apply("open", "settlement_pending").applied
    assert machine.apply("settlement_pending", "settled").applied


def test_position_terminal_states_final():
    for terminal in POSITION_TERMINAL_STATES:
        result = PositionStateMachine.apply(terminal, "open")
        assert not result.applied


def test_position_stale_out_of_order():
    result = PositionStateMachine.apply("closed", "reducing")
    assert not result.applied
    assert result.reason == "stale_out_of_order"


def test_unknown_statuses_never_crash():
    result = OrderStateMachine.apply("filled", "warp_speed")
    assert not result.applied
    assert "unknown_incoming_status" in result.reason
    result = PositionStateMachine.apply("hyperspace", "open")
    assert not result.applied
    assert "unknown_current_status" in result.reason
