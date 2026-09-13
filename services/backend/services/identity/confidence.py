"""Confidence scoring for identity signals and candidate matches.

Implements the five-tier confidence model:
    BLOCKED → WEAK → PROBABLE → STRONG → DETERMINISTIC

Every scoring decision produces a numeric score (0.0–1.0), a tier, and
an explicit list of reason codes that make the decision auditable.

Score semantics — read this before treating the number as a probability:
the composite value produced here is an *identity MATCH score*, an
evidence-weighted strength-of-match derived from signal-type weights. It is
**not** a calibrated probability: it is not fit against observed
merge-correctness outcomes, so it must never be read as ``P(same identity)``.
It is an ordinal match strength whose only job is to drive the tier decision.
:func:`score_signals` returns a :class:`MatchScore`, which unpacks as the same
``(score, tier, reason_codes)`` 3-tuple as before but additionally carries
explicit ``score_kind`` / ``calibrated=False`` markers that make this contract
machine-readable.
"""

from __future__ import annotations

from typing import Any

from .models import (
    ConfidenceTier,
    IdentitySignalType,
    REASON_CONSENT_BLOCKS_LINK,
    REASON_CONSENT_ALLOWS_LINK,
    REASON_CROSS_TENANT_BLOCKED,
    REASON_FINGERPRINT_ONLY_BLOCKED,
    REASON_SAME_USER_ID,
    REASON_SAME_EXTERNAL_ID,
    REASON_SAME_VERIFIED_WALLET,
    REASON_SAME_VERIFIED_EMAIL,
    REASON_SAME_EMAIL_HASH,
    REASON_SAME_PHONE_HASH,
    REASON_SAME_ANONYMOUS_ID,
    REASON_SAME_SESSION_ID,
    REASON_SAME_DEVICE_INSTALL,
    REASON_SAME_CAMPAIGN_PATH,
    REASON_SAME_JOURNEY_PATH,
    REASON_SAME_AGENT_DELEGATION,
    REASON_SAME_ORG_ACCOUNT,
    REASON_REVOKED_ALIAS,
    REASON_INSUFFICIENT_EVIDENCE,
)


# ── Score kind markers ────────────────────────────────────────────────────────
#
# Make the semantics of the composite number explicit and machine-readable: it
# is an evidence-weighted identity *match* score, not a calibrated probability.

SCORE_KIND: str = "identity_match_score"
CALIBRATED: bool = False


class MatchScore(tuple):
    """Result of :func:`score_signals` — an evidence-weighted identity match score.

    Unpacks exactly like the historical ``(score, tier, reason_codes)`` 3-tuple,
    so every existing caller keeps working unchanged, while additionally
    carrying explicit semantic markers on the result itself:

    * ``score_kind`` — ``"identity_match_score"``: a strength-of-match, not a
      probability.
    * ``calibrated`` — ``False``: the score is NOT calibrated against observed
      outcomes and must not be interpreted as ``P(same identity)``.
    """

    __slots__ = ()
    score_kind: str = SCORE_KIND
    calibrated: bool = False

    def __new__(
        cls,
        score: float,
        tier: ConfidenceTier,
        reason_codes: list[str],
    ) -> "MatchScore":
        return super().__new__(cls, (score, tier, reason_codes))

    @property
    def score(self) -> float:
        return self[0]

    @property
    def tier(self) -> ConfidenceTier:
        return self[1]

    @property
    def reason_codes(self) -> list[str]:
        return list(self[2])


# ── Signal-type weights (used to compute composite score) ─────────────────────

_SIGNAL_WEIGHTS: dict[IdentitySignalType, float] = {
    IdentitySignalType.USER_ID:                    1.00,
    IdentitySignalType.EXTERNAL_ID:                1.00,
    IdentitySignalType.WALLET_SIGNATURE_VERIFIED:  0.95,
    IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED:   1.00,
    IdentitySignalType.COMMERCE_CUSTOMER_ID:       0.90,
    IdentitySignalType.PAYMENT_CUSTOMER_ID:        0.90,
    IdentitySignalType.ACCOUNT_ID:                 0.88,
    IdentitySignalType.EMAIL_HASH:                 0.85,
    IdentitySignalType.PHONE_HASH:                 0.83,
    IdentitySignalType.ORG_ID:                     0.80,
    IdentitySignalType.MOBILE_INSTALL_ID:          0.70,
    IdentitySignalType.INSTALLATION_ID:            0.68,
    IdentitySignalType.ANONYMOUS_ID:               0.65,
    IdentitySignalType.BROWSER_ID:                 0.60,
    IdentitySignalType.WALLET_ADDRESS:             0.60,
    IdentitySignalType.SESSION_ID:                 0.50,
    IdentitySignalType.JOURNEY_ID:                 0.45,
    IdentitySignalType.AGENT_ID:                   0.40,
    IdentitySignalType.CAMPAIGN_ID:                0.20,
    IdentitySignalType.DEVICE_FINGERPRINT:         0.15,
}

# ── Reason code mapping per signal type ───────────────────────────────────────

_REASON_BY_SIGNAL: dict[IdentitySignalType, str] = {
    IdentitySignalType.USER_ID:                    REASON_SAME_USER_ID,
    IdentitySignalType.EXTERNAL_ID:                REASON_SAME_EXTERNAL_ID,
    IdentitySignalType.WALLET_SIGNATURE_VERIFIED:  REASON_SAME_VERIFIED_WALLET,
    IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED:   REASON_SAME_VERIFIED_EMAIL,
    IdentitySignalType.EMAIL_HASH:                 REASON_SAME_EMAIL_HASH,
    IdentitySignalType.PHONE_HASH:                 REASON_SAME_PHONE_HASH,
    IdentitySignalType.ANONYMOUS_ID:               REASON_SAME_ANONYMOUS_ID,
    IdentitySignalType.SESSION_ID:                 REASON_SAME_SESSION_ID,
    IdentitySignalType.MOBILE_INSTALL_ID:          REASON_SAME_DEVICE_INSTALL,
    IdentitySignalType.INSTALLATION_ID:            REASON_SAME_DEVICE_INSTALL,
    IdentitySignalType.BROWSER_ID:                 REASON_SAME_DEVICE_INSTALL,
    IdentitySignalType.DEVICE_FINGERPRINT:         REASON_FINGERPRINT_ONLY_BLOCKED,
    IdentitySignalType.CAMPAIGN_ID:                REASON_SAME_CAMPAIGN_PATH,
    IdentitySignalType.JOURNEY_ID:                 REASON_SAME_JOURNEY_PATH,
    IdentitySignalType.AGENT_ID:                   REASON_SAME_AGENT_DELEGATION,
    IdentitySignalType.ORG_ID:                     REASON_SAME_ORG_ACCOUNT,
    IdentitySignalType.COMMERCE_CUSTOMER_ID:       REASON_SAME_EXTERNAL_ID,
    IdentitySignalType.PAYMENT_CUSTOMER_ID:        REASON_SAME_EXTERNAL_ID,
    IdentitySignalType.ACCOUNT_ID:                 REASON_SAME_ORG_ACCOUNT,
    IdentitySignalType.WALLET_ADDRESS:             REASON_SAME_VERIFIED_WALLET,
}

# ── Signals requiring explicit consent ───────────────────────────────────────

CONSENT_REQUIRED_SIGNALS: frozenset[IdentitySignalType] = frozenset({
    IdentitySignalType.EMAIL_HASH,
    # Verified email ownership still requires identity-linking consent before it
    # may stitch entities together (blueprint §40).
    IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
    IdentitySignalType.PHONE_HASH,
    IdentitySignalType.DEVICE_FINGERPRINT,
    IdentitySignalType.BROWSER_ID,
    IdentitySignalType.MOBILE_INSTALL_ID,
    IdentitySignalType.INSTALLATION_ID,
})


def score_signals(
    matching_signal_types: list[IdentitySignalType],
    consent_snapshot: dict | None,
    source_tenant_id: str,
    target_tenant_id: str,
    revoked_types: list[IdentitySignalType] | None = None,
) -> MatchScore:
    """
    Compute the composite identity **match** score and tier for a candidate.

    The returned number is an evidence-weighted match strength, NOT a calibrated
    probability (see the module docstring and :class:`MatchScore`).

    Returns:
        MatchScore — unpacks as ``(score: float, tier: ConfidenceTier,
        reason_codes: list[str])`` and carries ``score_kind`` /
        ``calibrated=False`` markers.
    """
    reason_codes: list[str] = []
    revoked_types = revoked_types or []

    # ── Absolute blocking rules ──────────────────────────────────────────

    if source_tenant_id != target_tenant_id:
        return MatchScore(0.0, ConfidenceTier.BLOCKED, [REASON_CROSS_TENANT_BLOCKED])

    # Revoked alias in matching set
    for rt in revoked_types:
        if rt in matching_signal_types:
            reason_codes.append(REASON_REVOKED_ALIAS)
            # Only block if the revoked signal is the only strong evidence
            non_revoked = [
                st for st in matching_signal_types
                if st not in revoked_types
            ]
            if not non_revoked:
                return MatchScore(0.0, ConfidenceTier.BLOCKED, reason_codes)

    # Fingerprint-only check: if the ONLY signals are fingerprint, block
    non_fp = [
        st for st in matching_signal_types
        if st != IdentitySignalType.DEVICE_FINGERPRINT
    ]
    if not non_fp and IdentitySignalType.DEVICE_FINGERPRINT in matching_signal_types:
        return MatchScore(0.0, ConfidenceTier.BLOCKED, [REASON_FINGERPRINT_ONLY_BLOCKED])

    # ── Consent check for sensitive signals ──────────────────────────────

    sensitive_in_match = [
        st for st in matching_signal_types
        if st in CONSENT_REQUIRED_SIGNALS
    ]
    has_consent = _has_consent(consent_snapshot)

    if sensitive_in_match and not has_consent:
        # Sensitive link attempted without consent — block
        reason_codes.append(REASON_CONSENT_BLOCKS_LINK)
        # Remove sensitive signals from scoring
        matching_signal_types = [
            st for st in matching_signal_types
            if st not in CONSENT_REQUIRED_SIGNALS
        ]
        if not matching_signal_types:
            return MatchScore(0.0, ConfidenceTier.BLOCKED, reason_codes)
    elif sensitive_in_match and has_consent:
        reason_codes.append(REASON_CONSENT_ALLOWS_LINK)

    if not matching_signal_types:
        return MatchScore(0.0, ConfidenceTier.BLOCKED, [REASON_INSUFFICIENT_EVIDENCE])

    # ── Composite score ───────────────────────────────────────────────────

    # Use the maximum signal weight as the primary match strength, then
    # boost slightly for each additional corroborating signal. This is an
    # evidence-weighted MATCH score, not a calibrated probability.
    weights = [
        _SIGNAL_WEIGHTS.get(st, 0.3)
        for st in matching_signal_types
    ]
    weights.sort(reverse=True)
    primary = weights[0]
    boost = sum(w * 0.02 for w in weights[1:])
    match_score = min(1.0, primary + boost)

    # Add reason codes for each matched signal
    for st in matching_signal_types:
        code = _REASON_BY_SIGNAL.get(st)
        if code and code not in reason_codes:
            reason_codes.append(code)

    tier = _tier_for_score(match_score, matching_signal_types)
    return MatchScore(match_score, tier, reason_codes)


def _tier_for_score(
    score: float,
    matching_types: list[IdentitySignalType],
) -> ConfidenceTier:
    """Map numeric score + signal types to a confidence tier."""

    # DETERMINISTIC: user_id, external_id, verified wallet
    deterministic_types = {
        IdentitySignalType.USER_ID,
        IdentitySignalType.EXTERNAL_ID,
        IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
        IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
        IdentitySignalType.COMMERCE_CUSTOMER_ID,
        IdentitySignalType.PAYMENT_CUSTOMER_ID,
    }
    if any(st in deterministic_types for st in matching_types):
        return ConfidenceTier.DETERMINISTIC

    # STRONG: email hash, phone hash, account ID, org ID
    strong_types = {
        IdentitySignalType.EMAIL_HASH,
        IdentitySignalType.PHONE_HASH,
        IdentitySignalType.ACCOUNT_ID,
    }
    if any(st in strong_types for st in matching_types) and score >= 0.80:
        return ConfidenceTier.STRONG

    # PROBABLE: device continuity, anon ID + session/install
    probable_types = {
        IdentitySignalType.ANONYMOUS_ID,
        IdentitySignalType.INSTALLATION_ID,
        IdentitySignalType.MOBILE_INSTALL_ID,
        IdentitySignalType.BROWSER_ID,
        IdentitySignalType.WALLET_ADDRESS,
    }
    if any(st in probable_types for st in matching_types) and score >= 0.55:
        return ConfidenceTier.PROBABLE

    if score >= 0.30:
        return ConfidenceTier.WEAK

    return ConfidenceTier.BLOCKED


def _has_consent(consent_snapshot: dict | None) -> bool:
    """Return True if the consent snapshot allows identity-stitching."""
    if consent_snapshot is None:
        return False
    # If explicit opt-out
    if consent_snapshot.get("denied") is True:
        return False
    # Check for analytics or identity-specific consent
    purposes = consent_snapshot.get("purposes") or consent_snapshot.get("grants") or {}
    if isinstance(purposes, dict):
        return bool(
            purposes.get("analytics")
            or purposes.get("identity")
            or purposes.get("marketing")
        )
    # Fallback: presence of any non-empty snapshot implies minimal consent
    return bool(consent_snapshot)


def signal_weight(signal_type: IdentitySignalType) -> float:
    """Return the base match weight for a single signal type."""
    return _SIGNAL_WEIGHTS.get(signal_type, 0.3)


# Clearly-named public alias reflecting what the score actually is (an identity
# match score). ``score_signals`` is retained as the historical name that
# existing callers (e.g. merge_policy.evaluate) import.
identity_match_score = score_signals
