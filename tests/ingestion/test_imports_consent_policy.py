"""Regression tests for the WS-B3 tenant-import T-class consent-policy seam
(``services/imports/commit.py::_enforce_imports_consent_policy``).

Covers the post-review finding #3 (Consent Policy Bypass / Fail-open Gate):
policy data classes must never be derived from the client-supplied mapping
``source_column`` labels in isolation, and an unresolved column must deny by
default instead of ``continue``-skipping the policy check.

Proves, against the ACTUAL staged row schema (never the mapping labels):
  1. disabling ``imports_consent_policy_enabled`` DENIES the commit (fail
     closed) — the mandatory T-class policy layer cannot be bypassed by
     switching the flag off;
  2. a mapping ``source_column`` that is NOT PROVEN present among the real
     staged columns denies with ``mapping_source_column_unresolved`` (a client
     cannot launder prohibited content under a label no policy ever sees);
  3. fingerprinting is detected from the REAL staged column schema and denied
     under tenant compliance policy even when every mapping label is innocent;
  4. a resolved, fingerprint-free mapping passes the gate (control).
"""
from __future__ import annotations

import dataclasses
import uuid

import pytest

from config.settings import settings
from services.imports.commit import _enforce_imports_consent_policy
from services.imports.contracts import FieldMapping
from shared.common.common import ConflictError


def _tenant() -> str:
    return f"t-import-{uuid.uuid4().hex[:10]}"


def _policy_off(monkeypatch) -> None:
    patched = dataclasses.replace(
        settings.ingress_consent, imports_consent_policy_enabled=False
    )
    monkeypatch.setattr(settings, "ingress_consent", patched)


def _compliance_on(monkeypatch) -> None:
    patched = dataclasses.replace(
        settings.consent_authority, tenant_compliance_policy_enabled=True
    )
    monkeypatch.setattr(settings, "consent_authority", patched)


def _fm(source_column: str, target_field: str = "external_id") -> FieldMapping:
    return FieldMapping(
        source_column=source_column,
        primitive="entity",
        target_field=target_field,
    )


def _staged(rows: list[dict]) -> list[dict]:
    return [{"file_id": "f-1", "rows": rows}]


# ── 1. Flag OFF ⇒ commit DENIED (fail closed), never a policy bypass ─────────
@pytest.mark.asyncio
async def test_flag_off_denies_closed(monkeypatch):
    _policy_off(monkeypatch)
    with pytest.raises(ConflictError) as ei:
        await _enforce_imports_consent_policy(
            _tenant(),
            [_fm("user_id")],
            _staged([{"user_id": "alice"}]),
        )
    assert "enforcement_disabled" in str(ei.value)


# ── 2. Phantom / empty source_column ⇒ DENIED (no label trust, no skip) ──────
@pytest.mark.asyncio
async def test_phantom_source_column_denies():
    # Mapping names a column that never appears in the staged rows.
    with pytest.raises(ConflictError) as ei:
        await _enforce_imports_consent_policy(
            _tenant(),
            [_fm("email"), _fm("user_id")],
            _staged([{"user_id": "alice"}]),  # only user_id is real
        )
    assert "mapping_source_column_unresolved" in str(ei.value)


@pytest.mark.asyncio
async def test_empty_source_column_denies():
    with pytest.raises(ConflictError) as ei:
        await _enforce_imports_consent_policy(
            _tenant(),
            [_fm("")],
            _staged([{"user_id": "alice"}]),
        )
    assert "mapping_source_column_unresolved" in str(ei.value)


# ── 3. Fingerprinting from the REAL staged columns (innocent labels) ─────────
@pytest.mark.asyncio
async def test_fingerprint_on_real_staged_columns_denied(monkeypatch):
    _compliance_on(monkeypatch)
    # Every mapping label is innocent; the fingerprint key lives in the actual
    # staged row schema — detection must come from the data, not the labels.
    with pytest.raises(ConflictError) as ei:
        await _enforce_imports_consent_policy(
            _tenant(),
            [_fm("user_id")],
            _staged([{"user_id": "alice", "deviceFingerprint": "abc123"}]),
        )
    assert "fingerprinting_not_authorized" in str(ei.value)


# ── 4. Resolved, fingerprint-free mapping passes (control) ───────────────────
@pytest.mark.asyncio
async def test_resolved_fingerprint_free_mapping_passes():
    # No exception ⇒ gate allowed (tenant data-policy default-allow without a
    # compliance profile; no fingerprint columns present).
    await _enforce_imports_consent_policy(
        _tenant(),
        [_fm("user_id"), _fm("email", target_field="value")],
        _staged([{"user_id": "alice", "email": "alice@example.com"}]),
    )
