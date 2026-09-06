"""Regression tests for the shared WS-B3 ingress facade.

Covers the two post-review findings on
``services/ingestion/validation.py::evaluate_ingress_decision``:

1. Authoritative-ON + a purpose + an unresolvable subject is DENIED
   (``consent_receipt_missing``) — never silently fail-opened to allowed. The
   facade mirrors ``validate_event``: under the authoritative flag the server
   receipt is consulted UNCONDITIONALLY for every purposed request.
2. The mandatory T-class layer (tenant data-policy removal of fingerprinting)
   runs even when the per-path S gate is OFF (no purpose supplied) — the
   "flag OFF" seam state still carries the scrub/data-policy layer.

Settings are flipped on the live singleton via ``dataclasses.replace`` +
``monkeypatch.setattr``; every test uses a unique tenant id and the package
conftest clears the in-memory stores before/after each test.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from config.settings import settings
from services.consent import authority
from services.ingestion.validation import (
    RequestPrivacySignals,
    evaluate_ingress_decision,
    scrub_sensitive_fields,
)


def _tenant() -> str:
    return f"t-facade-{uuid.uuid4().hex[:10]}"


def _authoritative_on(monkeypatch) -> None:
    patched = dataclasses.replace(
        settings.consent_authority, authoritative_consent_enforcement_enabled=True
    )
    monkeypatch.setattr(settings, "consent_authority", patched)


def _tenant_policy_on(monkeypatch) -> None:
    patched = dataclasses.replace(
        settings.consent_authority, tenant_compliance_policy_enabled=True
    )
    monkeypatch.setattr(settings, "consent_authority", patched)


async def _seed_granted(tenant_id: str, *, subject_id: str, purpose: str = "analytics") -> None:
    await authority.ConsentReceiptRepository().record(
        f"rc-{uuid.uuid4().hex[:10]}", tenant_id, purpose, "granted",
        subject_id=subject_id,
    )


@pytest.mark.asyncio
async def test_authoritative_on_purposed_unresolvable_subject_is_denied(monkeypatch):
    """Finding-1 regression: no subject/anonymous under authoritative-ON +
    a purpose must DENY (consent_receipt_missing), never fail open to allowed."""
    _authoritative_on(monkeypatch)
    tenant_id = _tenant()
    # Seed a receipt for a DIFFERENT subject so the deny is about THIS subject
    # being unresolvable-without-a-receipt, not an empty store.
    await _seed_granted(tenant_id, subject_id="other-user")

    allowed, reason, decisions = await evaluate_ingress_decision(
        tenant_id=tenant_id,
        subject_id=None,
        anonymous_id=None,
        purpose="analytics",
        fingerprint_obj=None,
    )
    assert allowed is False
    assert reason == "consent_receipt_missing"
    consent_decision = next(d for d in decisions if d["control"] == "consent_authority")
    assert consent_decision["outcome"] == "denied"
    assert consent_decision["subject_resolvable"] is False


@pytest.mark.asyncio
async def test_authoritative_on_with_granted_receipt_allows(monkeypatch):
    """Control: the S gate is a real per-subject check — a granted server
    receipt for THIS subject is allowed (proves the deny above is not a gate
    that always denies)."""
    _authoritative_on(monkeypatch)
    tenant_id = _tenant()
    await _seed_granted(tenant_id, subject_id="u-1")

    allowed, reason, decisions = await evaluate_ingress_decision(
        tenant_id=tenant_id,
        subject_id="u-1",
        anonymous_id="anon-1",
        purpose="analytics",
    )
    assert (allowed, reason) == (True, None)
    consent_decision = next(d for d in decisions if d["control"] == "consent_authority")
    assert consent_decision["outcome"] == "allowed"
    assert consent_decision["subject_resolvable"] is True


@pytest.mark.asyncio
async def test_purposeless_still_runs_mandatory_data_policy(monkeypatch):
    """flag-OFF seam state (purpose/subject omitted) still runs the MANDATORY
    T-class data-policy layer: fingerprint-bearing payloads are denied by the
    tenant policy even though no per-subject (S) server receipt is consulted."""
    _tenant_policy_on(monkeypatch)  # tenant compliance profile enforcement
    tenant_id = _tenant()

    allowed, reason, decisions = await evaluate_ingress_decision(
        tenant_id=tenant_id,
        subject_id=None,
        anonymous_id=None,
        purpose=None,  # S gate fully skipped — C/T minimization
        fingerprint_obj={"deviceFingerprint": "classified"},
    )
    assert allowed is False
    assert reason == "fingerprinting_not_authorized"
    policy = next(d for d in decisions if d["control"] == "fingerprint_policy")
    assert policy["outcome"] == "denied"
    assert policy["classified_paths"] == 1
    # No consent_authority decision was recorded: the S gate was not consulted.
    assert all(d["control"] != "consent_authority" for d in decisions)


@pytest.mark.asyncio
async def test_scrub_redacts_and_never_rejects():
    """Scrub is the unconditional minimization primitive — it redacts secret
    values while KEEPING the key, and it never raises/rejects on its own."""
    payload, found = scrub_sensitive_fields(
        {"profile": {"api_key": "sk-secret", "email": "a@b.c"}}
    )
    assert found is True
    assert payload["profile"]["api_key"] == "[REDACTED]"
    assert payload["profile"]["email"] == "a@b.c"


@pytest.mark.asyncio
async def test_request_privacy_signals_default_is_inert(monkeypatch):
    """A default decision carries no request-privacy suppression; a granted
    receipt is allowed (no GPC/DNT noise from the facade)."""
    _authoritative_on(monkeypatch)
    tenant_id = _tenant()
    await _seed_granted(tenant_id, subject_id="u-2")

    allowed, reason, _ = await evaluate_ingress_decision(
        tenant_id=tenant_id,
        subject_id="u-2",
        anonymous_id=None,
        purpose="analytics",
        request_privacy=RequestPrivacySignals(),
    )
    assert (allowed, reason) == (True, None)
