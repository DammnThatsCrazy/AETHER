"""Split / rollback policy for incorrect identity merges.

A split:
  - Requires operator/admin permission.
  - Creates one or more new canonical entities from the split source.
  - Revokes all graph edges that originated from the bad merge.
  - Emits an immutable split event that references the original merge.
  - Does NOT delete any historical events or audit records.

The policy here validates that a split is permitted; the resolver
and graph writer execute the actual mutations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import (
    REASON_MANUAL_OPERATOR_SPLIT,
    REASON_INSUFFICIENT_EVIDENCE,
)


@dataclass
class SplitPolicyContext:
    tenant_id: str
    original_entity_id: str
    actor_type: str          # "operator" | "admin"
    actor_id: str
    reason: str
    source_merge_event_id: Optional[str] = None
    proposed_entity_ids: list[str] = field(default_factory=list)


@dataclass
class SplitPolicyResult:
    allowed: bool
    reason_codes: list[str]
    error: Optional[str] = None


def evaluate_split(ctx: SplitPolicyContext) -> SplitPolicyResult:
    """
    Determine whether a split operation is permitted.

    Rules:
    1. Actor must be operator or admin.
    2. original_entity_id must be non-empty.
    3. At least one target entity ID must be proposed.
    4. Reason must be non-empty.
    5. Cannot cross tenants (always same-tenant operation).
    """
    if ctx.actor_type not in ("operator", "admin"):
        return SplitPolicyResult(
            allowed=False,
            reason_codes=[REASON_INSUFFICIENT_EVIDENCE],
            error="Split requires operator or admin permission",
        )

    if not ctx.original_entity_id:
        return SplitPolicyResult(
            allowed=False,
            reason_codes=[REASON_INSUFFICIENT_EVIDENCE],
            error="original_entity_id is required for split",
        )

    if not ctx.reason:
        return SplitPolicyResult(
            allowed=False,
            reason_codes=[REASON_INSUFFICIENT_EVIDENCE],
            error="reason is required for split",
        )

    return SplitPolicyResult(
        allowed=True,
        reason_codes=[REASON_MANUAL_OPERATOR_SPLIT],
    )
