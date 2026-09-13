"""Canonical IncentiveContext enums — backend carrier for the M1 JSON $defs.

Mirrors the enum members declared in
``packages/shared/contracts/incentive-context.schema.json`` (M1, blueprint
§§30-33). Parity between these constants and the JSON is enforced by
``tests/unit/incentive_context/test_incentive_context_canonical_parity.py`` so
this carrier can never silently drift from the contract it implements.

The ``sourceScope`` / ``evidenceBasis`` vocabularies are SHARED with the Social
Silver facts contract — the incentive-context schema does not define its own
copies, it references the same ``$defs`` spelling. They are re-exported from
``shared.social360.canonical`` so this module and the Social Silver carrier
cannot drift apart.

Honesty rules these values encode (blueprint §§30-33, §3.4, §31):

- ``none_observed`` is a POSITIVE assessment result ("we actually looked and
  found none over a bounded incentive-source space"), never the mere absence of
  a detected incentive. There is no automatic ``none_observed -> organic``
  conversion anywhere.
- an unknown incentive state stays ``unknown``; it is never coerced to
  ``organic`` or to ``paid`` / ``none_observed``.
- ``sourceScope`` has no ``unknown`` member: a context whose evidence cannot be
  attributed to a scope is NOT emitted with a guessed scope (the schema makes
  the field required, so the resolver refuses to build the context instead).
"""

from __future__ import annotations

# schema_version of the M1 incentive-context.schema.json we implement.
INCENTIVE_CONTEXT_SCHEMA_VERSION = "1.0.0"

# $defs/incentiveStatus — the incentive-exposure state machine (§31).
INCENTIVE_STATUSES: tuple[str, ...] = (
    "verified",
    "declared",
    "observed",
    "suspected",
    "none_observed",
    "unknown",
    "not_applicable",
)

# $defs/temporalSegment.segment — §32 segmentation of related activity around
# the incentive window. Order matters for output (PRE < WINDOW < POST).
PRE_INCENTIVE = "PRE_INCENTIVE"
INCENTIVE_WINDOW = "INCENTIVE_WINDOW"
POST_INCENTIVE = "POST_INCENTIVE"
TEMPORAL_SEGMENTS: tuple[str, ...] = (
    PRE_INCENTIVE,
    INCENTIVE_WINDOW,
    POST_INCENTIVE,
)

# confidenceKind — basis of the stated confidence (§13 evidence taxonomy).
CONFIDENCE_KINDS: tuple[str, ...] = (
    "provider_declared",
    "derived",
    "semantic_classification",
    "aggregated",
    "unknown",
)

# sourceScope / evidenceBasis — shared Social Silver vocabulary, re-exported so
# a single import site carries both carriers' provenance vocabulary.
from shared.social360.canonical import (  # noqa: E402  (see docstring)
    EVIDENCE_BASIS,
    EVIDENCE_BASIS_BY_ACQUISITION_MODE,
    SOURCE_SCOPES,
    SOURCE_SCOPE_BY_ACQUISITION_MODE,
)

# policy_ref carried by every context this resolver builds. It points at the
# governing program blueprint sections that make the resolution rules a policy
# the context can be audited against (§§30-33 incentive semantics, §3.4
# exposure-is-context-not-disqualification doctrine). Versioned so a rule change
# is observable on every context row.
POLICY_REF = (
    "blueprint:social360:docs/blueprints/social360.md#ss30-33-3.4:"
    "incentive-context-resolution:v1"
)

# Temporal segment boundary policy. The blueprint treats the choice of segment
# boundary as an explicit, documented decision; these are the assumptions this
# milestone records and the resolver emits in every segment's ``notes``.
SEGMENT_BOUNDARY_POLICY = (
    "segments are half-open UTC intervals [start, end); the incentive window is "
    "[exposure_started_at, exposure_ended_at); an activity at exposure_end is "
    "POST_INCENTIVE, an activity at exposure_start is INCENTIVE_WINDOW; when a "
    "PRE/POST outer bound is not supplied it is evidence-bounded to the earliest "
    "observed activity before the window / latest observed activity at or after "
    "its end (no magic look-back/look-forward constant); a naive boundary "
    "datetime is read as UTC unless a zone_id is supplied (DST policy from "
    "shared/temporal/windows.py applies to local boundaries)."
)

__all__ = [
    "CONFIDENCE_KINDS",
    "EVIDENCE_BASIS",
    "EVIDENCE_BASIS_BY_ACQUISITION_MODE",
    "INCENTIVE_CONTEXT_SCHEMA_VERSION",
    "INCENTIVE_STATUSES",
    "INCENTIVE_WINDOW",
    "POLICY_REF",
    "POST_INCENTIVE",
    "PRE_INCENTIVE",
    "SEGMENT_BOUNDARY_POLICY",
    "SOURCE_SCOPES",
    "SOURCE_SCOPE_BY_ACQUISITION_MODE",
    "TEMPORAL_SEGMENTS",
]
