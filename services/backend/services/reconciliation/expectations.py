"""Config-backed per-tenant Profile360 dimension expectations.

The checked-in registry provides safe defaults. Operators can override minimum
volume and freshness by tenant through config/reconciliation_expectations.json
(or AETHER_RECONCILIATION_EXPECTATIONS_FILE). Overrides are validated before
use and never mutate the process-global defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_DAY = 24 * 60 * 60
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "reconciliation_expectations.json"


class ExpectationConfigError(ValueError):
    """Raised when an operator-provided expectation override is invalid."""


@dataclass(frozen=True)
class DimensionExpectation:
    """What a healthy dimension looks like."""

    dimension: str
    min_events: int = 1
    freshness_sla_seconds: int = _DAY
    source_method: str = ""
    depends_on: tuple[str, ...] = field(default_factory=tuple)


EXPECTATION_REGISTRY: dict[str, DimensionExpectation] = {
    "wallets": DimensionExpectation(
        "wallets", min_events=1, freshness_sla_seconds=7 * _DAY, source_method="wallets",
    ),
    "sessions": DimensionExpectation(
        "sessions", min_events=1, freshness_sla_seconds=_DAY, source_method="sessions",
    ),
    "campaigns": DimensionExpectation(
        "campaigns", min_events=1, freshness_sla_seconds=30 * _DAY, source_method="campaigns",
    ),
    "journeys": DimensionExpectation(
        "journeys", min_events=1, freshness_sla_seconds=7 * _DAY,
        source_method="journeys", depends_on=("sessions",),
    ),
    "financials": DimensionExpectation(
        "financials", min_events=1, freshness_sla_seconds=7 * _DAY, source_method="financials",
    ),
    "relationships": DimensionExpectation(
        "relationships", min_events=1, freshness_sla_seconds=30 * _DAY,
        source_method="relationships",
    ),
}
REGISTERED_DIMENSIONS: tuple[str, ...] = tuple(EXPECTATION_REGISTRY)


def _config_path() -> Path:
    return Path(
        os.getenv("AETHER_RECONCILIATION_EXPECTATIONS_FILE", str(_DEFAULT_CONFIG_PATH))
    )


@lru_cache(maxsize=16)
def _read_config(path: Optional[Path] = None) -> dict[str, Any]:
    selected = path or _config_path()
    # Overrides are deployment configuration; a process restart activates a new
    # file atomically and avoids repeated I/O in tenant coverage sweeps.
    if not selected.exists():
        return {"version": 1, "defaults": {}, "tenants": {}}
    try:
        document = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExpectationConfigError(
            f"Cannot read reconciliation expectation config: {selected}"
        ) from exc
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ExpectationConfigError("Expectation config must be an object with version=1")
    defaults = document.get("defaults", {})
    tenants = document.get("tenants", {})
    if not isinstance(defaults, dict) or not isinstance(tenants, dict):
        raise ExpectationConfigError("defaults and tenants must be objects")
    return document


def _validated_override(dimension: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ExpectationConfigError(f"Override for {dimension!r} must be an object")
    unknown = set(raw) - {"min_events", "freshness_sla_seconds", "source_method", "depends_on"}
    if unknown:
        raise ExpectationConfigError(
            f"Unknown expectation fields for {dimension!r}: {sorted(unknown)}"
        )
    values: dict[str, Any] = {}
    if "min_events" in raw:
        value = raw["min_events"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ExpectationConfigError(f"{dimension}.min_events must be a non-negative integer")
        values["min_events"] = value
    if "freshness_sla_seconds" in raw:
        value = raw["freshness_sla_seconds"]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ExpectationConfigError(
                f"{dimension}.freshness_sla_seconds must be a positive integer"
            )
        values["freshness_sla_seconds"] = value
    if "source_method" in raw:
        value = raw["source_method"]
        if not isinstance(value, str) or not value:
            raise ExpectationConfigError(f"{dimension}.source_method must be a non-empty string")
        values["source_method"] = value
    if "depends_on" in raw:
        value = raw["depends_on"]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ExpectationConfigError(f"{dimension}.depends_on must be a list of strings")
        values["depends_on"] = tuple(value)
    return values


def _apply_layer(
    registry: dict[str, DimensionExpectation], layer: Any, *, label: str
) -> dict[str, DimensionExpectation]:
    if not isinstance(layer, dict):
        raise ExpectationConfigError(f"{label} must be an object")
    resolved = dict(registry)
    for dimension, raw in layer.items():
        if dimension not in EXPECTATION_REGISTRY:
            raise ExpectationConfigError(
                f"{label} references unregistered dimension {dimension!r}"
            )
        resolved[dimension] = replace(
            resolved[dimension], **_validated_override(dimension, raw)
        )
    return resolved


def resolved_registry(
    tenant_id: Optional[str] = None, *, path: Optional[Path] = None
) -> dict[str, DimensionExpectation]:
    """Resolve base, global, then tenant overrides without cross-tenant leakage."""
    document = _read_config(path)
    resolved = _apply_layer(
        EXPECTATION_REGISTRY, document.get("defaults", {}), label="defaults"
    )
    if tenant_id is not None:
        tenants = document.get("tenants", {})
        tenant_layer = tenants.get(tenant_id, {})
        resolved = _apply_layer(
            resolved, tenant_layer, label=f"tenants.{tenant_id}"
        )
    return resolved


def get_expectation(
    dimension: str, tenant_id: Optional[str] = None, *, path: Optional[Path] = None
) -> DimensionExpectation:
    """Return the effective expectation for one tenant and dimension."""
    return resolved_registry(tenant_id, path=path).get(dimension) or DimensionExpectation(dimension)


def registry_snapshot(
    tenant_id: Optional[str] = None, *, path: Optional[Path] = None
) -> list[dict]:
    """Serializable effective registry for diagnostics and documentation."""
    return [
        {
            "dimension": exp.dimension,
            "min_events": exp.min_events,
            "freshness_sla_seconds": exp.freshness_sla_seconds,
            "source_method": exp.source_method,
            "depends_on": list(exp.depends_on),
        }
        for exp in resolved_registry(tenant_id, path=path).values()
    ]


__all__ = [
    "DimensionExpectation",
    "ExpectationConfigError",
    "EXPECTATION_REGISTRY",
    "REGISTERED_DIMENSIONS",
    "get_expectation",
    "registry_snapshot",
    "resolved_registry",
]
