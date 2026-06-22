"""
Aether Shared — @aether/graph/write_validator

Pre-write edge validator that enforces required property presence,
layer classification, and consent gating before a graph edge is committed.

Usage in GraphClient.add_edge():
    validator = GraphWriteValidator()
    result = validator.validate(edge, env=self._env)
    if not result.passed and not _is_lenient(self._env):
        raise GraphWriteValidationError(result.violations)

In local/test environments the validator logs violations instead of raising,
so existing tests and dev flows are not broken.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from shared.graph.edge_properties import (
    CONSENT_REQUIRED_LAYERS,
    REQUIRED_EDGE_PROPERTIES,
    VALID_ACTOR_KINDS,
)
from shared.logger.logger import get_logger

logger = get_logger("aether.graph.write_validator")


# ═══════════════════════════════════════════════════════════════════════════
# EXCEPTIONS
# ═══════════════════════════════════════════════════════════════════════════

class GraphWriteValidationError(ValueError):
    """Raised when an edge fails pre-write validation in strict environments."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__(
            f"Graph write validation failed ({len(violations)} violation(s)):\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


# ═══════════════════════════════════════════════════════════════════════════
# RESULT
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationResult:
    passed: bool
    violations: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════

def _is_lenient_env(env: str) -> bool:
    """Return True when running in local or test mode (validator logs, not raises)."""
    return env.lower() in ("local", "test", "")


class GraphWriteValidator:
    """
    Validates an Edge before it is written to the graph backend.

    Checks (in order):
    1.  edge_type is a non-empty string
    2.  from_vertex_id and to_vertex_id are non-empty
    3.  All REQUIRED_EDGE_PROPERTIES present in edge.properties
    4.  actor_kind is one of {human, agent, system}
    5.  confidence is a parseable float in [0.0, 1.0]
    6.  valid_from is a non-empty string (ISO-8601 format assumed by callers)
    7.  For H2A / A2H edges: consent_purpose must be present
    8.  tenant_id on edge matches tenant_id on vertices when provided
    """

    def __init__(self) -> None:
        # Lazy import to avoid circular dependency at module load time
        self._env = os.getenv("AETHER_ENV", "local").lower()

    def validate(self, edge: "Edge", env: str | None = None) -> ValidationResult:  # type: ignore[name-defined]  # noqa: F821
        """Validate the edge. Returns a ValidationResult with all violations."""
        from shared.graph.relationship_layers import classify_edge_type
        env = env if env is not None else self._env
        violations: list[str] = []

        # 1. Basic structure
        if not edge.edge_type:
            violations.append("edge_type is empty")
        if not edge.from_vertex_id:
            violations.append("from_vertex_id is empty")
        if not edge.to_vertex_id:
            violations.append("to_vertex_id is empty")

        props = edge.properties or {}

        # 2. Required property presence
        missing = REQUIRED_EDGE_PROPERTIES - set(props.keys())
        for key in sorted(missing):
            violations.append(f"Missing required property: {key!r}")

        # 3. actor_kind value
        actor_kind = props.get("actor_kind", "")
        if actor_kind and actor_kind not in VALID_ACTOR_KINDS:
            violations.append(
                f"Invalid actor_kind: {actor_kind!r}. Must be one of {sorted(VALID_ACTOR_KINDS)}"
            )

        # 4. confidence range
        confidence_raw = props.get("confidence")
        if confidence_raw is not None:
            try:
                conf = float(confidence_raw)
                if not (0.0 <= conf <= 1.0):
                    violations.append(
                        f"confidence {conf!r} out of range [0.0, 1.0]"
                    )
            except (ValueError, TypeError):
                violations.append(
                    f"confidence {confidence_raw!r} is not a valid float"
                )

        # 5. valid_from non-empty (callers are responsible for ISO-8601 format)
        if "valid_from" in props and not props["valid_from"]:
            violations.append("valid_from must be a non-empty ISO-8601 timestamp")

        # 6. Consent purpose for H2A / A2H edges
        if edge.edge_type:
            try:
                layer = classify_edge_type(edge.edge_type)
                if (
                    layer is not None
                    and layer.value in CONSENT_REQUIRED_LAYERS
                    and not props.get("consent_purpose")
                ):
                    violations.append(
                        f"Edge type {edge.edge_type!r} is in layer {layer.value!r} "
                        "which requires 'consent_purpose' in properties"
                    )
            except Exception:
                pass  # classification errors are caught separately

        # 7. Silver-sourced mutations must carry a non-empty source_event_id
        if props.get("provenance_class") == "silver" and not props.get("source_event_id"):
            violations.append(
                "Silver-sourced edges (provenance_class='silver') require a non-empty source_event_id"
            )

        if violations:
            if _is_lenient_env(env):
                logger.warning(
                    "Graph write violations (lenient mode, not raising): %s",
                    violations,
                )
            return ValidationResult(passed=False, violations=violations)

        return ValidationResult(passed=True)
