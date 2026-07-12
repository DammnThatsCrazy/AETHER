"""Server-authoritative consent + tenant compliance policy (PR 3).

The SERVER consent-receipt store — not the SDK per-event ``context.consent``
snapshot — is the source of truth for whether processing is lawful. Absence of
a server receipt is NOT permission: it is a denial (fail-closed). SDK snapshots
become evidence, not authority.

This module adds, on top of the existing consent primitives
(``shared/privacy/consent_enforcement.py`` for the registry-derived purpose set,
and ``services/consent/routes.py`` for the ``ConsentRepository`` write path):

* Stable rejection-code constants — a fixed vocabulary so ingestion, audit, and
  clients speak one language about *why* an event was refused.
* ``ConsentReceiptRepository`` — the authoritative server receipt store
  (BaseRepository over ``consent_receipts``).
* ``evaluate_consent(...)`` — the async decision consulted on the ingestion
  hot-path; returns ``(allowed, reason_code)``.
* ``TenantComplianceProfileRepository`` + ``evaluate_data_policy(...)`` — rejects
  prohibited data classes / unauthorized fingerprinting per tenant policy.

Pure stdlib + BaseRepository so the decision functions are unit-testable in
isolation (AETHER_ENV=local, no DATABASE_URL → in-memory repositories).
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

from config.settings import settings as _settings
from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger

# Reuse the canonical, registry-derived purpose set (never re-derive it here).
from shared.privacy.consent_enforcement import CONSENT_PURPOSES

logger = get_logger("aether.consent.authority")


# ── Stable rejection-code constants ─────────────────────────────────────────
# A fixed vocabulary. Ingestion echoes these as the per-event reason; changing a
# value is a contract change. Grouped by the concern that produced them.

# Receipt existence / integrity
CONSENT_RECEIPT_MISSING = "consent_receipt_missing"
CONSENT_UNKNOWN = "consent_unknown"
CONSENT_DENIED = "consent_denied"
CONSENT_REVOKED = "consent_revoked"
CONSENT_EXPIRED = "consent_expired"
CONSENT_POLICY_MISMATCH = "consent_policy_mismatch"
CONSENT_SUBJECT_MISMATCH = "consent_subject_mismatch"
CONSENT_TENANT_MISMATCH = "consent_tenant_mismatch"

# Purpose / lawful basis
PURPOSE_NOT_AUTHORIZED = "purpose_not_authorized"
LAWFUL_PROCESSING_NOT_CONFIGURED = "lawful_processing_not_configured"

# Tenant compliance / data classification
TENANT_POLICY_DENIED = "tenant_policy_denied"
DATA_CLASSIFICATION_DENIED = "data_classification_denied"
FINGERPRINTING_NOT_AUTHORIZED = "fingerprinting_not_authorized"

# Request-time privacy signals (see DEFERRED note at bottom of module)
GPC_SUPPRESSED = "gpc_suppressed"
DNT_SUPPRESSED = "dnt_suppressed"

# The complete, stable set — exported for tests / audit tooling.
REJECTION_CODES: frozenset[str] = frozenset({
    CONSENT_RECEIPT_MISSING,
    CONSENT_UNKNOWN,
    CONSENT_DENIED,
    CONSENT_REVOKED,
    CONSENT_EXPIRED,
    CONSENT_POLICY_MISMATCH,
    CONSENT_SUBJECT_MISMATCH,
    CONSENT_TENANT_MISMATCH,
    PURPOSE_NOT_AUTHORIZED,
    LAWFUL_PROCESSING_NOT_CONFIGURED,
    TENANT_POLICY_DENIED,
    DATA_CLASSIFICATION_DENIED,
    FINGERPRINTING_NOT_AUTHORIZED,
    GPC_SUPPRESSED,
    DNT_SUPPRESSED,
})

# States that count as an affirmative, still-valid grant.
_GRANTED_STATES = frozenset({"granted", "active"})

# Global Privacy Control opts out of sale/sharing → maps to advertising intent;
# Do Not Track opts out of behavioral tracking → maps to analytics. These are
# receipt-recorded here; request-time header suppression is deferred (see note).
_GPC_SUPPRESSED_PURPOSES = frozenset({"marketing"})
_DNT_SUPPRESSED_PURPOSES = frozenset({"analytics"})


# ── explicit-opt-in purpose set (registry-derived, fail-closed) ─────────────

_REGISTRY_PATH = (
    pathlib.Path(__file__).resolve().parents[4]
    / "packages" / "shared" / "contracts" / "consent-registry.json"
)


def _load_explicit_opt_in_purposes() -> frozenset[str]:
    """Purposes the registry marks ``explicitOptInRequired``.

    For these, a granted receipt is insufficient unless it records an explicit
    opt-in lawful basis. Fail-closed to an empty set if the registry is
    unreadable (the registry always ships with the repo)."""
    try:
        data = json.loads(_REGISTRY_PATH.read_text())
        return frozenset(
            p["key"] for p in data.get("purposes", [])
            if p.get("explicitOptInRequired", False)
        )
    except Exception:  # pragma: no cover - registry file always ships with repo
        logger.warning("consent registry unreadable; explicit-opt-in set empty")
        return frozenset()


_EXPLICIT_OPT_IN_PURPOSES: frozenset[str] = _load_explicit_opt_in_purposes()


# ── Repositories (BaseRepository JSONB stores) ──────────────────────────────

class ConsentReceiptRepository(BaseRepository):
    """Authoritative server-side consent receipts (table ``consent_receipts``).

    The SERVER record decides. One row per receipt; the latest row for a
    (tenant, subject, purpose) is the current state.
    """

    def __init__(self) -> None:
        super().__init__("consent_receipts")

    async def latest_for(
        self,
        tenant_id: str,
        purpose: str,
        *,
        subject_id: Optional[str] = None,
        anonymous_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Return the most recent receipt for a (tenant, subject, purpose).

        Prefers ``subject_id`` when present, else falls back to
        ``anonymous_id``. Returns None when no subject identifier is supplied or
        no receipt exists. find_many sorts by created_at desc, so [0] is latest.
        """
        filters: dict = {"tenant_id": tenant_id, "purpose": purpose}
        if subject_id:
            filters["subject_id"] = subject_id
        elif anonymous_id:
            filters["anonymous_id"] = anonymous_id
        else:
            return None
        rows = await self.find_many(filters=filters, limit=1)
        return rows[0] if rows else None

    async def record(
        self,
        receipt_id: str,
        tenant_id: str,
        purpose: str,
        state: str,
        *,
        subject_id: Optional[str] = None,
        anonymous_id: Optional[str] = None,
        policy_version: Optional[str] = None,
        source: str = "sdk",
        jurisdiction: Optional[str] = None,
        mode: Optional[str] = None,
        lawful_basis: Optional[str] = None,
        granted_at: Optional[str] = None,
        revoked_at: Optional[str] = None,
        expires_at: Optional[str] = None,
        gpc_observed: Optional[bool] = None,
        dnt_observed: Optional[bool] = None,
        integrity_hash: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Persist a server consent receipt (the authoritative record)."""
        now = utc_now().isoformat()
        return await self.insert(receipt_id, {
            "receipt_id": receipt_id,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "anonymous_id": anonymous_id,
            "purpose": purpose,
            "state": state,
            "policy_version": policy_version,
            "source": source,
            "jurisdiction": jurisdiction,
            "mode": mode,
            "lawful_basis": lawful_basis,
            "granted_at": granted_at or (now if state in _GRANTED_STATES else None),
            "revoked_at": revoked_at,
            "expires_at": expires_at,
            "gpc_observed": gpc_observed,
            "dnt_observed": dnt_observed,
            "integrity_hash": integrity_hash,
            "metadata": metadata or {},
        })


class TenantComplianceProfileRepository(BaseRepository):
    """Per-tenant compliance posture (table ``tenant_compliance_profiles``)."""

    def __init__(self) -> None:
        super().__init__("tenant_compliance_profiles")

    async def for_tenant(self, tenant_id: str) -> Optional[dict]:
        rows = await self.find_many(filters={"tenant_id": tenant_id}, limit=1)
        return rows[0] if rows else None

    async def upsert(
        self,
        tenant_id: str,
        *,
        profile_version: str = "1",
        commercial_stage: str = "",
        risk_tier: str = "",
        prohibited_data_classes: Optional[list[str]] = None,
        fingerprinting_allowed: bool = False,
        policy_state: str = "active",
        metadata: Optional[dict] = None,
    ) -> dict:
        record = {
            "profile_id": tenant_id,
            "tenant_id": tenant_id,
            "profile_version": profile_version,
            "commercial_stage": commercial_stage,
            "risk_tier": risk_tier,
            "prohibited_data_classes": [
                str(c).strip().lower() for c in (prohibited_data_classes or [])
            ],
            "fingerprinting_allowed": bool(fingerprinting_allowed),
            "policy_state": policy_state,
            "metadata": metadata or {},
        }
        existing = await self.find_by_id(tenant_id)
        if existing:
            return await self.update(tenant_id, record)
        return await self.insert(tenant_id, record)


# Module-level singletons (mirrors the repo's singleton pattern).
_receipt_repo = ConsentReceiptRepository()
_profile_repo = TenantComplianceProfileRepository()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _is_past(iso: Optional[str]) -> bool:
    """True if the ISO timestamp is in the past (naive → assumed UTC)."""
    if not iso:
        return False
    try:
        exp = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= exp


# ── Decision: server-authoritative consent ──────────────────────────────────

async def evaluate_consent(
    tenant_id: str,
    subject_id: Optional[str],
    anonymous_id: Optional[str],
    purpose: str,
    *,
    required_policy_version: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Decide whether processing is lawful for a (subject, purpose).

    The SERVER ConsentReceipt store is authoritative — the SDK snapshot is NOT
    consulted here. Fail-closed: any ambiguity denies.

    Returns ``(allowed, reason_code)``. ``reason_code`` is one of
    ``REJECTION_CODES`` when denied, and ``None`` when allowed.
    """
    purpose = (purpose or "").strip()
    if not purpose:
        return False, PURPOSE_NOT_AUTHORIZED
    # Unknown purpose → we cannot establish a lawful basis for it.
    if purpose not in CONSENT_PURPOSES:
        return False, CONSENT_UNKNOWN

    subject = (subject_id or "").strip() or None
    anon = (anonymous_id or "").strip() or None
    if not subject and not anon:
        # No identifier at all → no receipt can exist → absence is denial.
        return False, CONSENT_RECEIPT_MISSING

    receipt = await _receipt_repo.latest_for(
        tenant_id, purpose, subject_id=subject, anonymous_id=anon,
    )
    if not receipt:
        # Absence of a server receipt is NOT permission (fail-closed).
        return False, CONSENT_RECEIPT_MISSING

    # Defensive scope checks (the store lookup already scoped by tenant/subject).
    if receipt.get("tenant_id") not in (None, "", tenant_id):
        return False, CONSENT_TENANT_MISMATCH
    if subject and receipt.get("subject_id") not in (None, "", subject):
        return False, CONSENT_SUBJECT_MISMATCH

    # Explicit negative states, most specific first.
    state = (receipt.get("state") or "").strip().lower()
    if receipt.get("revoked_at") or state == "revoked":
        return False, CONSENT_REVOKED
    if state == "denied" or receipt.get("granted") is False:
        return False, CONSENT_DENIED
    if state == "expired" or _is_past(receipt.get("expires_at")):
        return False, CONSENT_EXPIRED
    if state not in _GRANTED_STATES:
        # Present but not an affirmative grant → indeterminate.
        return False, CONSENT_UNKNOWN

    # Request-time privacy signals recorded on the receipt (see DEFERRED note).
    if receipt.get("gpc_observed") is True and purpose in _GPC_SUPPRESSED_PURPOSES:
        return False, GPC_SUPPRESSED
    if receipt.get("dnt_observed") is True and purpose in _DNT_SUPPRESSED_PURPOSES:
        return False, DNT_SUPPRESSED

    # Explicit-opt-in purposes need an explicit lawful basis, not a soft grant.
    if purpose in _EXPLICIT_OPT_IN_PURPOSES:
        mode = (receipt.get("mode") or "").strip().lower()
        if not receipt.get("lawful_basis") and mode not in ("opt_in", "explicit"):
            return False, LAWFUL_PROCESSING_NOT_CONFIGURED

    # Policy-version pinning (opt-in): only enforced when a version is required.
    if (
        required_policy_version is not None
        and str(receipt.get("policy_version") or "") != str(required_policy_version)
    ):
        return False, CONSENT_POLICY_MISMATCH

    return True, None


# ── Decision: tenant data-classification policy ─────────────────────────────

# Data classes that are treated as device fingerprinting (default-deny).
_FINGERPRINT_CLASSES = frozenset({
    "fingerprint", "fingerprinting", "device_fingerprint", "cross_device_fingerprint",
})


async def evaluate_data_policy(
    tenant_id: str,
    data_class: str,
) -> tuple[bool, Optional[str]]:
    """Decide whether a data class may be processed under tenant policy.

    Returns ``(allowed, reason_code)``. Default-allow when no profile exists
    (prohibitions require an explicit tenant compliance profile), EXCEPT
    fingerprinting, which is default-deny unless the profile authorizes it.

    Gated by ``TENANT_COMPLIANCE_POLICY_ENABLED``: when off (legacy / default in
    local), tenant data-class policy is not enforced and everything is allowed.
    """
    if not _settings.consent_authority.tenant_compliance_policy_enabled:
        return True, None

    data_class = (data_class or "").strip().lower()
    profile = await _profile_repo.for_tenant(tenant_id)

    # Fingerprinting is default-deny: it requires explicit tenant authorization.
    if data_class in _FINGERPRINT_CLASSES:
        if not (profile and profile.get("fingerprinting_allowed") is True):
            return False, FINGERPRINTING_NOT_AUTHORIZED
        return True, None

    if not profile:
        # No profile configured → no data-class prohibitions to enforce.
        return True, None

    if (profile.get("policy_state") or "").strip().lower() == "denied":
        return False, TENANT_POLICY_DENIED

    prohibited = {
        str(c).strip().lower() for c in (profile.get("prohibited_data_classes") or [])
    }
    if data_class and data_class in prohibited:
        return False, DATA_CLASSIFICATION_DENIED

    return True, None


# ─────────────────────────────────────────────────────────────────────────────
# DEFERRED (tracked in config/implementation_ledger.yaml FT-3-AUTHORITATIVE-
# CONSENT): request-time DNT/GPC header suppression and request-time
# fingerprinting-signal detection. This module enforces GPC/DNT and
# fingerprinting authorization from the RECORDED receipt/profile state; wiring
# the live request headers (Sec-GPC / DNT) and per-event fingerprint payload
# detection into evaluate_consent/evaluate_data_policy is a follow-up.
# ─────────────────────────────────────────────────────────────────────────────
