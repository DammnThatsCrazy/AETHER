"""Capability activation-state vocabulary — frozen row shape + legal moves.

The persisted capability lifecycle lives in ``capability_activation_states``
(append-only state versions; exactly one non-superseded row per coordinate).
This module freezes the row shape (mirroring the
``CREDENTIAL_VERSION_FIELDS`` discipline in
``services/providers/credentials/schema.py``) and the machine-enforced legal
transition set for the canonical ``CredentialReadiness`` lifecycle.

Coordinate: ``(tenant_id, provider, environment, capability)``. The state a
row certifies is additionally bound to the credential version it was
certified against (``credential_version_ref``) — rotating a credential
demotes the coordinate back to CREDENTIAL_SUPPLIED for the new version.
"""

from __future__ import annotations

from shared.certification.readiness import CredentialReadiness as R

# Frozen JSONB row shape (a test asserts writes carry exactly these fields).
ACTIVATION_STATE_FIELDS: tuple[str, ...] = (
    "tenant_id",
    "provider",
    "domain",
    "environment",
    "capability",
    "state_version",
    "readiness_state",
    "prior_state",
    "credential_version_ref",
    "evidence_refs",
    "reason",
    "actor_type",
    "actor_id",
    "kill_switch",
    "superseded",
    "occurred_at",
)

ACTOR_TYPES: tuple[str, ...] = ("user", "operator", "system_worker")

# Credential environments the runtime lifecycle accepts (matches the
# credential authority's sandbox/live axis plus internal local/staging runs —
# the same set the evidence-manifest schema allows).
ACTIVATION_ENVIRONMENTS: tuple[str, ...] = ("local", "sandbox", "staging", "live")

# ── Legal transitions (machine-enforced; a test pins this literal) ───────────
#
# Upward motion is strictly single-step along the tenant-runtime progression
# CREDENTIAL_WAITING → CREDENTIAL_SUPPLIED → CONNECTION_VALIDATED →
# SANDBOX_VALIDATED → PARTNER_LIVE (no rung-skipping, ever). Off-ramps are
# reachable from every progression state; recovery paths are explicit:
# SUSPENDED/DEGRADED resume to the state they interrupted, REVOKED and
# DISABLED re-enter at CREDENTIAL_WAITING. SCAFFOLDED can only advance to
# CREDENTIAL_WAITING (a code-completeness fact, not a tenant action) and
# nothing ever returns to SCAFFOLDED.

_PROGRESSION = (
    R.CREDENTIAL_WAITING,
    R.CREDENTIAL_SUPPLIED,
    R.CONNECTION_VALIDATED,
    R.SANDBOX_VALIDATED,
    R.PARTNER_LIVE,
)

TRANSITIONS: frozenset[tuple[R, R]] = frozenset(
    {
        # single-step progression
        (R.SCAFFOLDED, R.CREDENTIAL_WAITING),
        (R.CREDENTIAL_WAITING, R.CREDENTIAL_SUPPLIED),
        (R.CREDENTIAL_SUPPLIED, R.CONNECTION_VALIDATED),
        (R.CONNECTION_VALIDATED, R.SANDBOX_VALIDATED),
        (R.SANDBOX_VALIDATED, R.PARTNER_LIVE),
        # credential rotation re-binds the coordinate to the new version
        (R.CONNECTION_VALIDATED, R.CREDENTIAL_SUPPLIED),
        (R.SANDBOX_VALIDATED, R.CREDENTIAL_SUPPLIED),
        (R.PARTNER_LIVE, R.CREDENTIAL_SUPPLIED),
        # explicit demotion one level down from live
        (R.PARTNER_LIVE, R.SANDBOX_VALIDATED),
        # credential deletion/expiry drops a supplied-but-unvalidated coordinate
        (R.CREDENTIAL_SUPPLIED, R.CREDENTIAL_WAITING),
    }
    # off-ramps reachable from every progression state
    | {(s, off) for s in _PROGRESSION for off in (R.DEGRADED, R.SUSPENDED, R.REVOKED, R.DISABLED)}
    # DEGRADED recovers to the progression state it interrupted
    | {(R.DEGRADED, s) for s in _PROGRESSION}
    | {(R.DEGRADED, R.SUSPENDED), (R.DEGRADED, R.REVOKED), (R.DEGRADED, R.DISABLED)}
    # SUSPENDED resumes to the progression state it interrupted
    | {(R.SUSPENDED, s) for s in _PROGRESSION}
    | {(R.SUSPENDED, R.REVOKED), (R.SUSPENDED, R.DISABLED)}
    # REVOKED / DISABLED re-enter at CREDENTIAL_WAITING
    | {(R.REVOKED, R.CREDENTIAL_WAITING), (R.REVOKED, R.DISABLED)}
    | {(R.DISABLED, R.CREDENTIAL_WAITING)}
)

# States whose promotion REQUIRES at least one resolvable evidence reference.
EVIDENCE_REQUIRED_STATES: frozenset[R] = frozenset(
    {R.CONNECTION_VALIDATED, R.SANDBOX_VALIDATED, R.PARTNER_LIVE}
)

# Promotions past this rung additionally require an entitlement check.
ENTITLEMENT_REQUIRED_FROM: R = R.CONNECTION_VALIDATED


def is_legal_transition(current: R, target: R) -> bool:
    return (current, target) in TRANSITIONS


__all__ = [
    "ACTIVATION_STATE_FIELDS",
    "ACTIVATION_ENVIRONMENTS",
    "ACTOR_TYPES",
    "ENTITLEMENT_REQUIRED_FROM",
    "EVIDENCE_REQUIRED_STATES",
    "TRANSITIONS",
    "is_legal_transition",
]
