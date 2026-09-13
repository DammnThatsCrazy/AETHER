"""Canonical epistemic-status vocabulary (Python).

A single, consolidated status vocabulary for how *trustworthy* a claim,
finding, or state is — whether it is a direct observation, an
evidence-grounded fact, or only a derived / inferred / correlated / predicted
suspicion.

No-silent-escalation invariant
------------------------------
A ``derived`` / ``inferred`` / ``correlated`` / ``predicted`` suspicion must
never render as a factual declaration (``verified`` / ``causally_supported`` /
``confirmed``) without an evidence-grounded upgrade. This vocabulary is the
single authority a ClaimEnvelope / FraudHypothesis state and any UI render
against: a UI may only display a more-confident status when the underlying
record transitioned with evidence (held-out experiment, verified identity
link, independent corroboration, …), never by styling or copy preference.

Consolidation
-------------
Epistemic claims previously scattered across fragmented vocabularies map onto
this vocabulary through the typed tables below. Table keys are fragment
values (kept as literal strings so this shared package never imports
services/generated modules at runtime); table values are canonical
:class:`EpistemicStatus` members. Fragment values with no honest epistemic
reading map to ``unknown`` / ``not_applicable`` with an explanatory comment —
never to a factual declaration:

* ``OBSERVATION_CLASS_TO_EPISTEMIC`` ← ``OBSERVATION_CLASS_VALUES``
  (``shared/graph/graph_contract.py``)
* ``CAUSALITY_CLASS_TO_EPISTEMIC``   ← ``CAUSALITY_CLASSES``
  (``shared/graph/edge_properties.py``)
* ``LIFECYCLE_STATE_TO_EPISTEMIC``   ← ``LIFECYCLE_STATE_VALUES``
  (``shared/graph/graph_contract.py``)
* ``RESULT_STATUS_TO_EPISTEMIC``     ← ``ResultStatus``
  (``shared/computation/result.py``)
* ``CONFLICT_STATUS_TO_EPISTEMIC``   ← ``ConflictStatus``
  (``services/identity/models.py``)
* ``PROJECTION_SECTION_STATE_TO_EPISTEMIC`` ← ``PROJECTION_SECTION_STATES``
  (``shared/intelligence_projections/generated_registry.py``)

The parity test ``tests/contracts/test_epistemic_status_parity.py`` imports the
source vocabularies directly and asserts each table covers its fragment
exactly (so the literal keys cannot silently drift from their sources).

TS twin: ``packages/shared/epistemic-status.ts`` (parity-tested by
``tests/contracts/test_epistemic_status_parity.py``).
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class EpistemicStatus(str, Enum):
    """The single authority for how a claim / state may be presented.

    Banding (used by UI render rules):

    * Direct / factual: ``observed``, ``verified``, ``resolved``,
      ``causally_supported``.
    * Suspicion / derivative (must NOT self-escalate): ``derived``,
      ``inferred``, ``predicted``, ``correlated``, ``attributed``.
    * Contested / withdrawn: ``disputed``, ``superseded``, ``stale``.
    * Honest absence: ``unknown``, ``unavailable``, ``not_applicable``.
    """

    OBSERVED = "observed"
    VERIFIED = "verified"
    RESOLVED = "resolved"
    DERIVED = "derived"
    INFERRED = "inferred"
    PREDICTED = "predicted"
    CORRELATED = "correlated"
    ATTRIBUTED = "attributed"
    CAUSALLY_SUPPORTED = "causally_supported"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    STALE = "stale"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"

    @classmethod
    def valid_values(cls) -> frozenset[str]:
        return frozenset(m.value for m in cls)


# Ordered exactly like the enum members — the TS twin mirrors this order.
EPISTEMIC_STATUS_VALUES: Final[tuple[str, ...]] = tuple(
    m.value for m in EpistemicStatus
)

# ── Fragmented-vocabulary → EpistemicStatus mapping tables ──────────────────
#
# All keys are the frozen values of the source vocabulary named in the
# comment. Totality is enforced by tests/contracts/test_epistemic_status_parity.py.

# OBSERVATION_CLASS_VALUES (shared/graph/graph_contract.py) — how a data point
# was produced. Production method does NOT grant epistemic weight by itself:
# probabilistic/derived/predicted/simulated inputs stay on the suspicion side.
OBSERVATION_CLASS_TO_EPISTEMIC: dict[str, EpistemicStatus] = {
    "observed": EpistemicStatus.OBSERVED,  # raw observation / direct capture
    "deterministic": EpistemicStatus.VERIFIED,  # exact computation over trusted inputs
    "probabilistic": EpistemicStatus.INFERRED,  # statistical model output — an inference, never a fact
    "derived": EpistemicStatus.DERIVED,
    "predicted": EpistemicStatus.PREDICTED,  # forward-looking estimate
    "simulated": EpistemicStatus.DERIVED,  # synthetic artifact; derived, never fact
    "manually_asserted": EpistemicStatus.OBSERVED,  # operator assertion surfaced as a direct claim
    "externally_enriched": EpistemicStatus.OBSERVED,  # third-party feed; observation pending verification
}

# CAUSALITY_CLASSES (shared/graph/edge_properties.py) — causal weight of an
# edge. correlation / inferred_influence / attributed_influence must NEVER read
# as causally_supported; only experiment_incremental / direct_cause carry
# evidence-grounded causal support.
CAUSALITY_CLASS_TO_EPISTEMIC: dict[str, EpistemicStatus] = {
    "observed_sequence": EpistemicStatus.OBSERVED,  # time-ordered, no causal claim
    "correlation": EpistemicStatus.CORRELATED,  # statistical co-occurrence
    "attributed_influence": EpistemicStatus.ATTRIBUTED,  # attribution-model output
    "inferred_influence": EpistemicStatus.INFERRED,  # ML-inferred causal path
    "experiment_incremental": EpistemicStatus.CAUSALLY_SUPPORTED,  # A/B / geo experiment
    "direct_cause": EpistemicStatus.CAUSALLY_SUPPORTED,  # established mechanism
}

# LIFECYCLE_STATE_VALUES (shared/graph/graph_contract.py) — graph-node / cluster
# liveness. Most lifecycle states describe data-plane liveness, not knowledge
# status, so they map to not_applicable (a claim must not derive epistemic
# weight from a node's liveness). Only the clearly epistemic states map.
LIFECYCLE_STATE_TO_EPISTEMIC: dict[str, EpistemicStatus] = {
    "provisional": EpistemicStatus.DERIVED,  # tentative / pre-final
    "unresolved": EpistemicStatus.DISPUTED,  # open, not settled
    "active": EpistemicStatus.NOT_APPLICABLE,  # liveness, not knowledge
    "growing": EpistemicStatus.NOT_APPLICABLE,  # liveness, not knowledge
    "stable": EpistemicStatus.NOT_APPLICABLE,  # liveness, not knowledge
    "shrinking": EpistemicStatus.NOT_APPLICABLE,  # liveness, not knowledge
    "dormant": EpistemicStatus.NOT_APPLICABLE,  # liveness, not knowledge
    "decaying": EpistemicStatus.NOT_APPLICABLE,  # liveness, not knowledge
    "reactivated": EpistemicStatus.NOT_APPLICABLE,  # liveness, not knowledge
    "merged": EpistemicStatus.SUPERSEDED,  # pre-merge record replaced by survivor
    "split": EpistemicStatus.SUPERSEDED,  # pre-split record replaced by fragments
    "suppressed": EpistemicStatus.UNAVAILABLE,  # exists but withheld by consent/policy
    "disputed": EpistemicStatus.DISPUTED,
    "expired": EpistemicStatus.STALE,  # validity window lapsed
    "revoked": EpistemicStatus.SUPERSEDED,  # withdrawn
    "invalidated": EpistemicStatus.SUPERSEDED,  # voided
    "deleted": EpistemicStatus.UNAVAILABLE,  # removed; not accessible
    "tombstoned": EpistemicStatus.SUPERSEDED,  # record replaced by a tombstone
}

# ResultStatus (shared/computation/result.py) — honest state of a computed
# result. "available" is value-bearing pipeline output; the honest-absence and
# best-effort statuses map to the absence / suspicion bands accordingly.
RESULT_STATUS_TO_EPISTEMIC: dict[str, EpistemicStatus] = {
    "available": EpistemicStatus.OBSERVED,  # value present from a trusted pipeline
    "partial": EpistemicStatus.DERIVED,  # best-effort value, flagged as such
    "estimated": EpistemicStatus.INFERRED,  # statistical estimate — not a fact
    "insufficient_data": EpistemicStatus.UNKNOWN,  # below minimum to report
    "missing_inputs": EpistemicStatus.UNKNOWN,  # could not run; no knowledge
    "not_applicable": EpistemicStatus.NOT_APPLICABLE,
    "not_provisioned": EpistemicStatus.UNAVAILABLE,  # capability not provisioned
    "unavailable": EpistemicStatus.UNAVAILABLE,
    "stale": EpistemicStatus.STALE,
    "conflicted": EpistemicStatus.DISPUTED,  # contradictory results
    "unreconciled": EpistemicStatus.DISPUTED,  # unresolved discrepancy
    "truncated": EpistemicStatus.DERIVED,  # partial best-effort value retained
    "privacy_restricted": EpistemicStatus.UNAVAILABLE,  # exists but withheld
    "suppressed": EpistemicStatus.UNAVAILABLE,  # exists but withheld
    "failed": EpistemicStatus.UNKNOWN,  # computation failed; no knowledge
}

# ConflictStatus (services/identity/models.py) — identity-conflict lifecycle.
CONFLICT_STATUS_TO_EPISTEMIC: dict[str, EpistemicStatus] = {
    "open": EpistemicStatus.DISPUTED,  # an open conflict is a contested state
    "resolved": EpistemicStatus.RESOLVED,
    "dismissed": EpistemicStatus.SUPERSEDED,  # closed without action; open state no longer stands
}

# PROJECTION_SECTION_STATES (generated_registry.py) — state of a projection
# result section. Section availability is about the surface's content, not the
# subject's truth; only the honesty-relevant states carry epistemic weight.
PROJECTION_SECTION_STATE_TO_EPISTEMIC: dict[str, EpistemicStatus] = {
    "available": EpistemicStatus.OBSERVED,  # filled section; a present, direct report
    "degraded": EpistemicStatus.DERIVED,  # produced on reduced / partial inputs
    "empty": EpistemicStatus.OBSERVED,  # honest zero-rows outcome; absence is the reported fact
    "missing": EpistemicStatus.UNKNOWN,  # dependency did not supply the section
    "not_applicable": EpistemicStatus.NOT_APPLICABLE,
    "stale": EpistemicStatus.STALE,
    "suppressed": EpistemicStatus.UNAVAILABLE,  # withheld by consent/policy
    "unknown": EpistemicStatus.UNKNOWN,
}

__all__ = [
    "EpistemicStatus",
    "EPISTEMIC_STATUS_VALUES",
    "OBSERVATION_CLASS_TO_EPISTEMIC",
    "CAUSALITY_CLASS_TO_EPISTEMIC",
    "LIFECYCLE_STATE_TO_EPISTEMIC",
    "RESULT_STATUS_TO_EPISTEMIC",
    "CONFLICT_STATUS_TO_EPISTEMIC",
    "PROJECTION_SECTION_STATE_TO_EPISTEMIC",
]
