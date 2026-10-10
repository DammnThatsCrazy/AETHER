"""IncentiveContext resolution (Social360 M5).

Runtime resolution of first-class, temporal, provenance-bearing incentive
context (blueprint §§30-33). Consumes Campaign360 / Economic360 references and
``shared/temporal/windows.py``; emits contexts conforming to the M1
``incentive-context.schema.json``. Honesty doctrine is release-blocking: an
incentive's absence is never automatically ``organic`` and an unknown incentive
state stays ``unknown``.

Deliberately a standalone resolver service — NOT a Silver projector. Incentive
context is a computed, provenance-bearing context (``computed_at``), not a
Silver fact row, and the Silver plane's one-projector-per-table ownership
registry has no IncentiveContext table to own.
"""

from __future__ import annotations

from .canonical import (
    INCENTIVE_STATUSES,
    INCENTIVE_WINDOW,
    POLICY_REF,
    POST_INCENTIVE,
    PRE_INCENTIVE,
    TEMPORAL_SEGMENTS,
)
from .models import IncentiveContext, TemporalSegment

__all__ = [
    "INCENTIVE_STATUSES",
    "INCENTIVE_WINDOW",
    "IncentiveContext",
    "POLICY_REF",
    "POST_INCENTIVE",
    "PRE_INCENTIVE",
    "TEMPORAL_SEGMENTS",
    "TemporalSegment",
]
