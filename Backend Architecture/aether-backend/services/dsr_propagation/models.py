"""Contracts for DSR propagation records (prompt §3.11).

A *propagation record* tracks how one Data Subject Request (DSR) fans out across
every backend component that can hold subject data or subject-derived artifacts.
Each component gets its own ``DSRPropagationStep`` with a fail-closed status
machine and evidence pointers (policy decision, audit event, retrain/recompute
flags). The record is the backend's tamper-visible answer to "what did this DSR
touch, and is any of it blocked?".

Nothing here executes a DSR — it only records propagation state. The state
machine is deliberately fail-closed: unknown/incomplete steps never roll up to
``completed`` (see :func:`overall_status`).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now

# ── DSR request types (mirrors services/consent DSR_TYPES) ────────────────────

DSRType = Literal[
    "access", "rectification", "erasure", "portability", "restriction", "objection",
]
DSR_TYPES: tuple[str, ...] = (
    "access", "rectification", "erasure", "portability", "restriction", "objection",
)

# ── Components a DSR propagates to (prompt §3.11) ─────────────────────────────
#
# Order is stable and load-bearing: open_request() seeds one pending step per
# component in this exact order so status() output is deterministic.
DSRComponent = Literal[
    "identity_aliases",
    "identity_subjects",
    "graph_edges",
    "profile360_snapshots",
    "feature_rows",
    "training_datasets",
    "model_artifacts",
    "prediction_drift_buffers",
    "exports",
    "audit_exports",
    "cached_tenant_views",
    "replay_bundles",
    "reward_decisions",
    "attribution_records",
    "connector_derived_records",
    "financial_value_snapshots",
    "semantic_observations",
    "sentiment_observations",
    "semantic_gold_state",
    "semantic_review_queue",
    "continuation_records",
    "mobile_installations",
    "client_sync_records",
    "kyber_trusted_devices",
    "kyber_webauthn_credentials",
    "kyber_device_proof_keys",
    "population_memberships",
    "population_snapshots",
    "populations",
]
DSR_COMPONENTS: tuple[DSRComponent, ...] = (
    "identity_aliases",
    "identity_subjects",
    "graph_edges",
    "profile360_snapshots",
    "feature_rows",
    "training_datasets",
    "model_artifacts",
    "prediction_drift_buffers",
    "exports",
    "audit_exports",
    "cached_tenant_views",
    "replay_bundles",
    "reward_decisions",
    "attribution_records",
    "connector_derived_records",
    "financial_value_snapshots",
    "semantic_observations",
    "sentiment_observations",
    "semantic_gold_state",
    "semantic_review_queue",
    "continuation_records",
    "mobile_installations",
    "client_sync_records",
    "kyber_trusted_devices",
    "kyber_webauthn_credentials",
    "kyber_device_proof_keys",
    "population_memberships",
    "population_snapshots",
    "populations",
)

# ── Per-step status machine (prompt §3.11) ────────────────────────────────────

DSRPropagationStatus = Literal[
    "pending",
    "running",
    "completed",
    "blocked",
    "failed",
    "skipped_legal_hold",
    "requires_manual_review",
]
DSR_PROPAGATION_STATUSES: tuple[DSRPropagationStatus, ...] = (
    "pending",
    "running",
    "completed",
    "blocked",
    "failed",
    "skipped_legal_hold",
    "requires_manual_review",
)

# A step is "terminal" once it has reached a state that will not advance on its
# own. ``running`` and ``pending`` are the only non-terminal states.
DSR_TERMINAL_STATUSES: frozenset[str] = frozenset({
    "completed", "blocked", "failed", "skipped_legal_hold", "requires_manual_review",
})

# States that count as "successfully resolved" for overall roll-up. A legal-hold
# skip is a *lawful* resolution of that component, so it counts toward completion.
_RESOLVED_STATUSES: frozenset[str] = frozenset({"completed", "skipped_legal_hold"})

# Overall roll-up never surfaces ``skipped_legal_hold`` (that folds into
# ``completed``); it can, however, surface any blocking/attention state.
DSROverallStatus = Literal[
    "pending", "running", "completed", "blocked", "failed", "requires_manual_review",
]


class ReattributionEvidence(BaseModel):
    """DSR propagation evidence that a subject's request corrected attribution.

    Reliability Phase-2, Program 3 ("Deletion / replay / re-attribution") **M2**:
    when re-attribution runs as part of a subject's request — privacy erasure
    (``reason="privacy_erasure"``) or fraud-network takedown
    (``reason="fraud_takedown"``) — it voids the now-wrong attribution runs for
    the subject's conversions (``services/measurement/reattribution.py``'s
    ``reattribute_affected`` -> ``ReattributionResult``). This records that
    correction as first-class propagation evidence on the ``attribution_records``
    component, so a DSR/compliance audit can see that attribution was actually
    re-run — not merely that touchpoints/conversions were tombstoned — as part of
    the request.

    Carries the ``ReattributionResult`` summary verbatim (the trigger ``reason``,
    the run/conversion counts, and the ``truncated``/``partial_failure`` honesty
    flags) plus a ``recorded_at`` stamp. It is *additive* evidence: it augments
    the component step's own erasure receipt (tombstone counts / audit pointer),
    never replaces it — so it composes with the erasure job's ``mark_step``
    marking regardless of order. The raw per-conversion ``errors`` list a
    ``ReattributionResult`` carries is summarized to ``errors_count`` here (the
    evidence records *that* the invalidation was partial, not error strings that
    can name conversion ids).
    """

    reason: str = Field(min_length=1)
    conversions_scanned: int = Field(default=0, ge=0)
    conversions_reattributed: int = Field(default=0, ge=0)
    runs_deactivated: int = Field(default=0, ge=0)
    runs_created: int = Field(default=0, ge=0)
    touchpoints_scanned: int = Field(default=0, ge=0)
    scope_limit: int = Field(default=0, ge=0)
    truncated: bool = False
    partial_failure: bool = False
    errors_count: int = Field(default=0, ge=0)
    # Stamped via the module's UTC helper (shared/common utc_now) — no bare
    # datetime construction here (temporal gate). ``now_iso`` is defined below,
    # so this defers to utc_now() directly to avoid a forward reference.
    recorded_at: str = Field(default_factory=lambda: utc_now().isoformat())


class DSRPropagationStep(BaseModel):
    """One component's propagation state within a DSR (prompt §3.11)."""

    component: DSRComponent
    status: DSRPropagationStatus = "pending"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    blocked_reason: Optional[str] = None
    policy_decision_id: Optional[str] = None
    audit_event_id: Optional[str] = None
    records_impacted: int = Field(default=0, ge=0)
    artifacts_impacted: int = Field(default=0, ge=0)
    requires_retrain: bool = False
    requires_recompute: bool = False
    # Program 3 M2 — additive re-attribution evidence (see ReattributionEvidence).
    # ``None`` until a re-attribution (privacy erasure OR fraud takedown) is
    # recorded against this component; augments, never replaces, the step's own
    # erasure receipt.
    reattribution: Optional[ReattributionEvidence] = None


# Evidence keys a caller may attach when marking a step. Anything outside this
# set is rejected (fail-closed) so typos never silently vanish.
#
# ``reattribution`` (Program 3 M2) lets a caller attach the re-attribution
# summary in the SAME ``mark_step`` call that marks the component (e.g. the
# erasure job marking ``attribution_records`` completed with both its tombstone
# receipt and the re-attribution evidence). It is NOT a completion receipt on
# its own (see ``_COMPLETION_EVIDENCE_FIELDS`` in service.py) — it augments one.
STEP_EVIDENCE_FIELDS: frozenset[str] = frozenset({
    "started_at", "completed_at", "blocked_reason", "policy_decision_id",
    "audit_event_id", "records_impacted", "artifacts_impacted",
    "requires_retrain", "requires_recompute", "reattribution",
})


def overall_status(steps: list[dict]) -> DSROverallStatus:
    """Roll individual step statuses up to a single request-level status.

    Fail-closed precedence — the record only reads ``completed`` when *every*
    component is resolved:

    1. no steps at all -> ``pending`` (nothing seeded yet)
    2. any ``blocked``            -> ``blocked``
    3. any ``failed``             -> ``failed``
    4. any ``requires_manual_review`` -> ``requires_manual_review``
    5. any ``running``            -> ``running``
    6. every step ``completed``/``skipped_legal_hold`` -> ``completed``
    7. otherwise (some still ``pending``) -> ``pending``
    """
    if not steps:
        return "pending"
    statuses = {str(s.get("status", "pending")) for s in steps}
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    if "requires_manual_review" in statuses:
        return "requires_manual_review"
    if "running" in statuses:
        return "running"
    if statuses <= _RESOLVED_STATUSES:
        return "completed"
    return "pending"


def now_iso() -> str:
    return utc_now().isoformat()
