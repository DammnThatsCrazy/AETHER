"""Small runtime validator for obligations returned by the rights PDP."""

from __future__ import annotations

from typing import Any


def obligation_violations(context: dict[str, Any]) -> list[str]:
    """Return missing materialization obligations for a reference-only stamp."""
    obligations = context.get("obligations") or []
    if not isinstance(obligations, list):
        return ["obligations_malformed"]
    violations: list[str] = []
    lineage = context.get("lineage_root_refs") or context.get("lineage_root_ref")
    envelopes = context.get("envelope_refs") or context.get("rights_envelope_refs")
    for raw in obligations:
        kind = raw.get("kind") if isinstance(raw, dict) else str(raw)
        if kind == "stamp_lineage" and not (lineage or envelopes):
            violations.append("obligation_lineage_missing")
        elif kind == "purpose_logging" and not context.get("purpose"):
            violations.append("obligation_purpose_missing")
        elif kind == "provenance" and not envelopes:
            violations.append("obligation_provenance_missing")
        elif kind == "ttl" and not context.get("retention_class") and not context.get("retention_deadline"):
            violations.append("obligation_ttl_missing")
        elif kind == "tenant_partition" and not context.get("tenant_id"):
            violations.append("obligation_tenant_partition_missing")
    return sorted(set(violations))


def enforce_obligations(context: dict[str, Any], operation: str) -> None:
    violations = obligation_violations(context)
    if violations:
        raise ValueError(
            f"rights_{operation}_blocked: obligations not satisfied: {','.join(violations)}"
        )


__all__ = ["enforce_obligations", "obligation_violations"]
