"""Wave 2c consent-gate tests — require_social_read_consent.

D-05 semantics under test:
* OFF flag => NO-OP (an un-activated surface is not a consent-failure surface);
* ON flag + registry row requires historical-consent evaluation + no consent
  => typed :class:`ConsentRequired`;
* consent is never fabricated: the default provider is ``None`` (fail-closed);
* a raising provider fails closed (no consent);
* an awaitable provider is awaited.
"""

from __future__ import annotations

import asyncio

import pytest

from services.relationship_intelligence import consent as _consent
from shared.relationship_spine import flags as _spine_flags


def _require(*, tenant="tenant-1", subject="subject-1", **kwargs):
    return asyncio.run(
        _consent.require_social_read_consent(
            tenant, subject_entity_id=subject, **kwargs
        )
    )


def _set_flag(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(_spine_flags, "social360_enabled", lambda: value)


def _grant_provider(**kwargs):
    return True


# ---------------------------------------------------------------------------
# OFF-flag: NO-OP, provider never consulted
# ---------------------------------------------------------------------------


def test_flag_off_is_a_noop(monkeypatch):
    _set_flag(monkeypatch, False)

    def _exploding_provider(**kwargs):
        raise AssertionError("provider must not be consulted while the flag is OFF")

    _consent.set_default_consent_provider(_exploding_provider)
    # NO-OP: returns None and never reaches the registry/provider path.
    assert _require(subject="subject-x") is None


# ---------------------------------------------------------------------------
# ON-flag: registry row requires evaluation, consent decides
# ---------------------------------------------------------------------------


def test_flag_on_with_no_provider_raises_consent_required(monkeypatch):
    _set_flag(monkeypatch, True)
    with pytest.raises(_consent.ConsentRequired) as excinfo:
        _require(subject="subject-x")
    # static + content-free: never leaks the subject
    assert str(excinfo.value) == _consent.CONSENT_REQUIRED_MESSAGE
    assert "subject-x" not in str(excinfo.value)


def test_flag_on_with_granting_provider_passes(monkeypatch):
    _set_flag(monkeypatch, True)
    _consent.set_default_consent_provider(_grant_provider)
    assert _require(subject="subject-x") is None


def test_flag_on_with_explicit_granting_provider_passes(monkeypatch):
    _set_flag(monkeypatch, True)
    assert _require(subject="subject-x", consent_provider=_grant_provider) is None


def test_flag_on_with_denying_provider_raises(monkeypatch):
    _set_flag(monkeypatch, True)
    _consent.set_default_consent_provider(lambda **kwargs: False)
    with pytest.raises(_consent.ConsentRequired):
        _require(subject="subject-x")


def test_flag_on_provider_receives_subject_and_tenant(monkeypatch):
    _set_flag(monkeypatch, True)
    seen = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return True

    _require(tenant="tenant-q", subject="subject-q", consent_provider=_capture)
    assert seen.get("tenant_id") == "tenant-q"
    assert seen.get("subject_entity_id") == "subject-q"


def test_raising_provider_fails_closed(monkeypatch):
    _set_flag(monkeypatch, True)

    def _boom(**kwargs):
        raise RuntimeError("entitlement subsystem down")

    with pytest.raises(_consent.ConsentRequired):
        _require(subject="subject-x", consent_provider=_boom)


def test_awaitable_provider_is_awaited(monkeypatch):
    _set_flag(monkeypatch, True)

    async def _async_provider(**kwargs):
        return True

    assert _require(subject="subject-x", consent_provider=_async_provider) is None


# ---------------------------------------------------------------------------
# Registry declaration drives the gate
# ---------------------------------------------------------------------------


def test_surface_registry_row_declares_historical_consent():
    row = _consent.INTELLIGENCE_PROJECTION_DEFINITIONS.get(_consent.SOCIAL360_PROJECTION_ID)
    assert row is not None
    security = row.get("security") or {}
    assert security.get("requiresHistoricalConsentEvaluation") is True


def test_missing_registry_row_fails_closed_to_consent_required(monkeypatch):
    _set_flag(monkeypatch, True)
    monkeypatch.setattr(_consent, "INTELLIGENCE_PROJECTION_DEFINITIONS", {})
    with pytest.raises(_consent.ConsentRequired):
        _require(subject="subject-x")


def test_default_provider_clears_back_to_fail_closed(monkeypatch):
    _set_flag(monkeypatch, True)
    _consent.set_default_consent_provider(_grant_provider)
    assert _require(subject="subject-x") is None
    _consent.clear_default_consent_provider()
    with pytest.raises(_consent.ConsentRequired):
        _require(subject="subject-x")


def test_consent_required_is_exception_typed_and_messageless_content():
    err = _consent.ConsentRequired()
    assert isinstance(err, Exception)
    assert err.message == _consent.CONSENT_REQUIRED_MESSAGE
