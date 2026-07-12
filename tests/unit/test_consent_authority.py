"""Server-authoritative consent enforcement (PR 3 / FT-3-AUTHORITATIVE-CONSENT).

Proves the founding-tenant consent guarantee: the SERVER consent-receipt store,
not the SDK per-event ``context.consent`` snapshot, decides whether ingestion may
process an event. Absence of a server receipt is NOT permission (fail-closed).

Robust to suite ordering: other tests evict and re-import backend modules, which
can leave several distinct generations of ``config.settings`` /
``repositories.repos`` / ``services.*`` alive at once (split-brain in-memory
stores / exception types). Each test here forces a SINGLE consistent generation:
evict backend modules, import them fresh, reset the in-memory stores, then flip
the live ``settings.consent_authority`` flags (the ingestion path reads them at
call time) — mirroring tests/unit/test_trust_containment.py.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest  # noqa: F401  (imported for parity / future markers)

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

# Ensure backend modules are importable when this file runs in isolation.
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_BACKEND_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


def _run(coro):
    return asyncio.run(coro)


@contextmanager
def consent_env(**flag_overrides):
    """Force a fresh, consistent backend and override consent-authority flags.

    Yields the freshly-imported ``services.consent.authority`` module so tests
    seed receipts / profiles through the same generation the decision functions
    read from.
    """
    _evict_backend()
    settings_mod = importlib.import_module("config.settings")
    repos = importlib.import_module("repositories.repos")
    repos.reset_in_memory_stores()
    authority = importlib.import_module("services.consent.authority")
    settings = settings_mod.settings
    original = settings.consent_authority
    if flag_overrides:
        object.__setattr__(
            settings, "consent_authority",
            dataclasses.replace(original, **flag_overrides),
        )
    try:
        yield authority
    finally:
        object.__setattr__(settings, "consent_authority", original)


class FakeCache:
    """Minimal cache stub — idempotency check treats a miss as 'not duplicate'."""

    async def get(self, _key):
        return None


def _make_event(batch, *, event_type="track", user_id="u1", anonymous_id="a1", consent=None):
    ctx = batch.EventContext(consent=consent) if consent is not None else batch.EventContext()
    return batch.BaseEvent(
        id=f"evt-{user_id}-{event_type}",
        type=event_type,
        timestamp="2026-07-12T00:00:00Z",
        sessionId="s1",
        anonymousId=anonymous_id,
        userId=user_id,
        properties={},
        context=ctx,
    )


def _process(batch, event, tenant_id="t1"):
    return _run(batch._process_single_event(
        sdk_event=event,
        tenant_id=tenant_id,
        batch_id="b1",
        received_at="2026-07-12T00:00:00Z",
        cache=FakeCache(),
    ))


# ═══════════════════════════════════════════════════════════════════════════
# evaluate_consent — the server record is authoritative
# ═══════════════════════════════════════════════════════════════════════════


class TestEvaluateConsent:

    def test_no_receipt_is_missing_not_permission(self):
        with consent_env() as authority:
            allowed, reason = _run(authority.evaluate_consent("t1", "u1", "a1", "analytics"))
            assert allowed is False
            assert reason == authority.CONSENT_RECEIPT_MISSING

    def test_granted_receipt_allows(self):
        with consent_env() as authority:
            _run(authority.ConsentReceiptRepository().record(
                "r1", "t1", "analytics", "granted", subject_id="u1"))
            allowed, reason = _run(authority.evaluate_consent("t1", "u1", "a1", "analytics"))
            assert (allowed, reason) == (True, None)

    def test_denied_receipt_rejects(self):
        with consent_env() as authority:
            _run(authority.ConsentReceiptRepository().record(
                "r1", "t1", "analytics", "denied", subject_id="u1"))
            allowed, reason = _run(authority.evaluate_consent("t1", "u1", "a1", "analytics"))
            assert (allowed, reason) == (False, authority.CONSENT_DENIED)

    def test_revoked_receipt_rejects(self):
        with consent_env() as authority:
            _run(authority.ConsentReceiptRepository().record(
                "r1", "t1", "analytics", "revoked", subject_id="u1",
                revoked_at="2026-01-01T00:00:00Z"))
            allowed, reason = _run(authority.evaluate_consent("t1", "u1", "a1", "analytics"))
            assert (allowed, reason) == (False, authority.CONSENT_REVOKED)

    def test_expired_receipt_rejects(self):
        with consent_env() as authority:
            _run(authority.ConsentReceiptRepository().record(
                "r1", "t1", "analytics", "granted", subject_id="u1",
                expires_at="2020-01-01T00:00:00Z"))
            allowed, reason = _run(authority.evaluate_consent("t1", "u1", "a1", "analytics"))
            assert (allowed, reason) == (False, authority.CONSENT_EXPIRED)

    def test_unknown_purpose_rejects(self):
        with consent_env() as authority:
            allowed, reason = _run(authority.evaluate_consent("t1", "u1", "a1", "not_a_purpose"))
            assert (allowed, reason) == (False, authority.CONSENT_UNKNOWN)

    def test_empty_purpose_rejects(self):
        with consent_env() as authority:
            allowed, reason = _run(authority.evaluate_consent("t1", "u1", "a1", ""))
            assert (allowed, reason) == (False, authority.PURPOSE_NOT_AUTHORIZED)

    def test_no_subject_identifier_is_missing(self):
        with consent_env() as authority:
            allowed, reason = _run(authority.evaluate_consent("t1", None, None, "analytics"))
            assert (allowed, reason) == (False, authority.CONSENT_RECEIPT_MISSING)

    def test_anonymous_fallback_when_no_subject(self):
        with consent_env() as authority:
            _run(authority.ConsentReceiptRepository().record(
                "r1", "t1", "analytics", "granted", anonymous_id="a1"))
            allowed, reason = _run(authority.evaluate_consent("t1", None, "a1", "analytics"))
            assert (allowed, reason) == (True, None)

    def test_policy_version_mismatch_rejects(self):
        with consent_env() as authority:
            _run(authority.ConsentReceiptRepository().record(
                "r1", "t1", "analytics", "granted", subject_id="u1", policy_version="1"))
            allowed, reason = _run(authority.evaluate_consent(
                "t1", "u1", "a1", "analytics", required_policy_version="2"))
            assert (allowed, reason) == (False, authority.CONSENT_POLICY_MISMATCH)

    def test_explicit_opt_in_purpose_needs_lawful_basis(self):
        # `location` is explicitOptInRequired in the registry: a soft grant is
        # insufficient without an explicit opt-in basis.
        with consent_env() as authority:
            _run(authority.ConsentReceiptRepository().record(
                "r1", "t1", "location", "granted", subject_id="u1", mode="opt_out"))
            allowed, reason = _run(authority.evaluate_consent("t1", "u1", "a1", "location"))
            assert (allowed, reason) == (False, authority.LAWFUL_PROCESSING_NOT_CONFIGURED)

            _run(authority.ConsentReceiptRepository().record(
                "r2", "t1", "location", "granted", subject_id="u2",
                mode="opt_in", lawful_basis="explicit_consent"))
            allowed2, reason2 = _run(authority.evaluate_consent("t1", "u2", "a2", "location"))
            assert (allowed2, reason2) == (True, None)

    def test_gpc_suppresses_marketing(self):
        with consent_env() as authority:
            _run(authority.ConsentReceiptRepository().record(
                "r1", "t1", "marketing", "granted", subject_id="u1", gpc_observed=True))
            allowed, reason = _run(authority.evaluate_consent("t1", "u1", "a1", "marketing"))
            assert (allowed, reason) == (False, authority.GPC_SUPPRESSED)


# ═══════════════════════════════════════════════════════════════════════════
# evaluate_data_policy — tenant compliance, flag-gated
# ═══════════════════════════════════════════════════════════════════════════


class TestEvaluateDataPolicy:

    def test_prohibited_class_rejected_when_flag_on(self):
        with consent_env(tenant_compliance_policy_enabled=True) as authority:
            _run(authority.TenantComplianceProfileRepository().upsert(
                "t1", prohibited_data_classes=["biometric"]))
            allowed, reason = _run(authority.evaluate_data_policy("t1", "biometric"))
            assert (allowed, reason) == (False, authority.DATA_CLASSIFICATION_DENIED)

    def test_fingerprinting_default_deny_when_flag_on(self):
        with consent_env(tenant_compliance_policy_enabled=True) as authority:
            allowed, reason = _run(authority.evaluate_data_policy("t1", "fingerprint"))
            assert (allowed, reason) == (False, authority.FINGERPRINTING_NOT_AUTHORIZED)

    def test_fingerprinting_allowed_when_profile_authorizes(self):
        with consent_env(tenant_compliance_policy_enabled=True) as authority:
            _run(authority.TenantComplianceProfileRepository().upsert(
                "t1", fingerprinting_allowed=True))
            allowed, reason = _run(authority.evaluate_data_policy("t1", "fingerprint"))
            assert (allowed, reason) == (True, None)

    def test_tenant_policy_denied_state(self):
        with consent_env(tenant_compliance_policy_enabled=True) as authority:
            _run(authority.TenantComplianceProfileRepository().upsert(
                "t1", policy_state="denied"))
            allowed, reason = _run(authority.evaluate_data_policy("t1", "email"))
            assert (allowed, reason) == (False, authority.TENANT_POLICY_DENIED)

    def test_allowed_class_passes(self):
        with consent_env(tenant_compliance_policy_enabled=True) as authority:
            _run(authority.TenantComplianceProfileRepository().upsert(
                "t1", prohibited_data_classes=["biometric"]))
            allowed, reason = _run(authority.evaluate_data_policy("t1", "email"))
            assert (allowed, reason) == (True, None)

    def test_flag_off_disables_enforcement(self):
        with consent_env(tenant_compliance_policy_enabled=False) as authority:
            _run(authority.TenantComplianceProfileRepository().upsert(
                "t1", prohibited_data_classes=["biometric"]))
            # Flag off → legacy behavior: nothing enforced, even a prohibited
            # class and fingerprinting are allowed.
            assert _run(authority.evaluate_data_policy("t1", "biometric")) == (True, None)
            assert _run(authority.evaluate_data_policy("t1", "fingerprint")) == (True, None)


# ═══════════════════════════════════════════════════════════════════════════
# Ingestion hot-path — flag ON enforces server authority; OFF preserves legacy
# ═══════════════════════════════════════════════════════════════════════════


class TestIngestionEnforcement:

    def test_granted_sdk_snapshot_but_no_server_receipt_is_rejected(self):
        # The SDK claims consent; the server has no receipt. Server wins.
        with consent_env(authoritative_consent_enforcement_enabled=True):
            batch = importlib.import_module("services.ingestion.batch")
            event = _make_event(batch, consent={"analytics": True})
            result = _process(batch, event)
            assert result.status == "rejected"
            assert result.reason.startswith("consent_receipt_missing")

    def test_server_granted_receipt_is_accepted(self):
        with consent_env(authoritative_consent_enforcement_enabled=True) as authority:
            batch = importlib.import_module("services.ingestion.batch")
            _run(authority.ConsentReceiptRepository().record(
                "r1", "t1", "analytics", "granted", subject_id="u1"))
            event = _make_event(batch, consent={"analytics": True})
            result = _process(batch, event)
            assert result.status == "accepted"

    def test_server_revoked_receipt_is_rejected_despite_sdk_grant(self):
        with consent_env(authoritative_consent_enforcement_enabled=True) as authority:
            batch = importlib.import_module("services.ingestion.batch")
            _run(authority.ConsentReceiptRepository().record(
                "r1", "t1", "analytics", "revoked", subject_id="u1",
                revoked_at="2026-01-01T00:00:00Z"))
            event = _make_event(batch, consent={"analytics": True})
            result = _process(batch, event)
            assert result.status == "rejected"
            assert result.reason.startswith("consent_revoked")

    def test_flag_off_preserves_legacy_sdk_snapshot_behavior(self):
        # Flag OFF: no server receipt required; the SDK snapshot governs.
        with consent_env(authoritative_consent_enforcement_enabled=False):
            batch = importlib.import_module("services.ingestion.batch")
            # SDK grants analytics, no server receipt → accepted (legacy).
            event = _make_event(batch, consent={"analytics": True})
            assert _process(batch, event).status == "accepted"

    def test_flag_off_still_honors_sdk_snapshot_denial(self):
        # Flag OFF: the legacy per-event snapshot gate (4a) still blocks an
        # explicit SDK denial.
        with consent_env(authoritative_consent_enforcement_enabled=False):
            batch = importlib.import_module("services.ingestion.batch")
            event = _make_event(batch, consent={"analytics": False})
            result = _process(batch, event)
            assert result.status == "rejected"
            assert result.reason.startswith("consent_denied")
