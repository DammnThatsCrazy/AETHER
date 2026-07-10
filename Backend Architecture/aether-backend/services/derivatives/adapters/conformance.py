"""Adapter conformance suite — every derivatives adapter must pass before
its implementation status may advance. Enforces the observation-only
invariants mechanically rather than by review."""

from __future__ import annotations

import json
import pathlib
from decimal import Decimal
from typing import Any

from repositories.typed_repo import as_decimal
from services.derivatives.adapters.base import DerivativesAdapter

_REGISTRY_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "packages" / "shared" / "contracts" / "event-registry.json"
)

_AMOUNT_KEYS = {
    "quantity", "price", "limit_price", "amount", "size", "entry_price",
    "realized_pnl", "unrealized_pnl", "gross_exposure", "net_exposure",
    "maintenance_margin", "initial_margin", "margin_utilization", "fee_amount",
}


def _canonical_derivatives_events() -> frozenset[str]:
    events = json.loads(_REGISTRY_PATH.read_text()).get("events", [])
    return frozenset(e["type"] for e in events if e.get("family") == "derivatives")


def _contains_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_float(v) for v in value)
    return False


async def run_conformance(adapter: DerivativesAdapter) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # (a) descriptor completeness + honest status
    descriptor = adapter.descriptor()
    required = ("adapter_id", "display_name", "implementation_status", "capabilities")
    check(
        "descriptor_complete",
        all(descriptor.get(k) for k in required),
        f"descriptor keys: {sorted(descriptor)}",
    )
    check(
        "descriptor_observation_only",
        descriptor.get("execution_by_aether") is False,
        "descriptor must declare execution_by_aether=false",
    )

    # (b) credential authority refusal
    try:
        adapter.validate_config({"authority_type": "trade"})
        check("refuses_trade_authority", False, "trade authority was accepted")
    except ValueError as exc:
        check("refuses_trade_authority", True, str(exc))
    try:
        adapter.validate_config({"authority_type": "read_only"})
        check("accepts_read_only_authority", True)
    except Exception as exc:  # pragma: no cover - adapter bug surface
        check("accepts_read_only_authority", False, str(exc))

    # (c) checkpoint monotonicity across three pulls
    checkpoint: dict[str, Any] | None = None
    cursors: list[Any] = []
    all_events: list[dict] = []
    for _ in range(3):
        events, checkpoint = await adapter.pull_events(checkpoint)
        cursors.append(json.dumps(checkpoint, sort_keys=True, default=str))
        all_events.extend(events)
    check(
        "checkpoint_monotonic",
        len(cursors) == len(set(cursors)) or cursors[-1] == cursors[-2],
        f"cursors: {cursors}",
    )

    # (d) idempotent replay — same checkpoint twice yields identical events
    events_one, _ = await adapter.pull_events(None)
    events_two, _ = await adapter.pull_events(None)
    check(
        "idempotent_replay",
        json.dumps(events_one, sort_keys=True, default=str)
        == json.dumps(events_two, sort_keys=True, default=str),
        "same checkpoint must yield identical events",
    )

    # (e) canonical event names only
    canonical = _canonical_derivatives_events()
    unknown = sorted({
        e.get("event_name", "") for e in all_events
        if e.get("event_name") not in canonical
    })
    check("canonical_event_names", not unknown, f"unknown events: {unknown}")

    # (f) Decimal-only amounts, no floats anywhere
    float_found = any(_contains_float(e) for e in all_events)
    bad_amounts: list[str] = []
    for event in all_events:
        for key, value in (event.get("payload") or {}).items():
            if key in _AMOUNT_KEYS and value is not None:
                try:
                    as_decimal(value)
                except (TypeError, ValueError, ArithmeticError):
                    bad_amounts.append(f"{event.get('event_name')}.{key}={value!r}")
    check("decimal_only_amounts", not float_found and not bad_amounts,
          f"floats={float_found} bad={bad_amounts}")

    # (g) execution flag never true
    executed = [
        e.get("event_name") for e in all_events
        if e.get("execution_by_aether") is True
        or (e.get("payload") or {}).get("execution_by_aether") is True
    ]
    check("never_claims_execution", not executed, f"violations: {executed}")

    return {
        "adapter_id": adapter.adapter_id,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "events_sampled": len(all_events),
    }


# Re-export for callers doing spot arithmetic on sampled events.
__all__ = ["run_conformance", "Decimal"]
