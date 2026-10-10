"""Decision policies — versioned separately from definitions.

A metric DEFINITION says what a number is; a POLICY says what to DO with it
(block/review/allow, merge/review/reject, intervene/ignore). Fraud probability is
a metric; "block above 0.9" is a policy. Identity match probability is a metric;
"merge above 0.95" is a policy. Keeping them separate lets thresholds change
without restating the underlying numbers, and vice versa.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"
    MERGE = "merge"
    REJECT = "reject"
    INTERVENE = "intervene"
    IGNORE = "ignore"


class DecisionThreshold(BaseModel):
    """One threshold band mapping a metric range to an outcome."""

    lower: Optional[float] = None
    upper: Optional[float] = None
    outcome: PolicyOutcome


class DecisionPolicy(BaseModel):
    """A versioned mapping from one or more metrics to an action."""

    policy_id: str
    policy_version: str = "1"
    display_name: str
    metric_definition_ids: list[str] = Field(default_factory=list)
    thresholds: list[DecisionThreshold] = Field(default_factory=list)
    default_outcome: PolicyOutcome = PolicyOutcome.REVIEW
    owner: str = "risk"
    fail_closed: bool = True

    def decide(self, value: Optional[float]) -> PolicyOutcome:
        """Map a metric value to an outcome; None fails closed when configured."""
        if value is None:
            return self.default_outcome if not self.fail_closed else PolicyOutcome.REVIEW
        for band in self.thresholds:
            lo_ok = band.lower is None or value >= band.lower
            hi_ok = band.upper is None or value < band.upper
            if lo_ok and hi_ok:
                return band.outcome
        return self.default_outcome


__all__ = ["PolicyOutcome", "DecisionThreshold", "DecisionPolicy"]
