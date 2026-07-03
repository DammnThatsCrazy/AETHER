"""Unit + security tests — signed post-click correlation token (Phase 11)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


class TestIssueVerify:
    def test_roundtrip(self):
        from services.comms.click_token import issue_click_token, verify_click_token
        token = issue_click_token(
            "tenant-a", campaign_id="camp-1", external_message_id="msg-1",
            recipient_alias_id="alias-1", link_id="link-1", sequence_step=3,
        )
        assert token.startswith("v")
        result = verify_click_token(token, "tenant-a")
        assert result.valid
        assert result.claims.campaign_id == "camp-1"
        assert result.claims.external_message_id == "msg-1"
        assert result.claims.recipient_alias_id == "alias-1"
        assert result.claims.link_id == "link-1"
        assert result.claims.sequence_step == 3

    def test_no_raw_pii_in_token(self):
        from services.comms.click_token import issue_click_token
        token = issue_click_token("tenant-a", recipient_alias_id="hashed-alias")
        assert "@" not in token

    def test_correlation_evidence_shape(self):
        from services.comms.click_token import (
            correlation_evidence_from_token, issue_click_token,
        )
        token = issue_click_token("tenant-a", campaign_id="camp-1", link_id="l1")
        ev = correlation_evidence_from_token(token, "tenant-a")
        assert ev["canonicalCampaignId"] == "camp-1"
        assert ev["evidence_source"] == "signed_click_token"
        assert ev["identity_method"] == "signed_click"


class TestSecurity:
    def test_cross_tenant_rejected(self):
        from services.comms.click_token import issue_click_token, verify_click_token
        token = issue_click_token("tenant-a", campaign_id="camp-1")
        result = verify_click_token(token, "tenant-b")
        assert not result.valid
        assert result.error == "tenant_mismatch"

    def test_tampered_payload_rejected(self):
        from services.comms.click_token import issue_click_token, verify_click_token
        token = issue_click_token("tenant-a", campaign_id="camp-1")
        version, payload, sig = token.split(".")
        tampered = f"{version}.{payload[:-2]}AA.{sig}"
        assert not verify_click_token(tampered, "tenant-a").valid

    def test_expired_rejected(self):
        from services.comms.click_token import issue_click_token, verify_click_token
        token = issue_click_token("tenant-a", ttl_seconds=1)
        # Fake time passing by direct claim check
        import services.comms.click_token as ct
        original = time.time
        try:
            time_module = ct.time
            ct_time = time_module.time
            ct.time.time = lambda: ct_time() + 10  # type: ignore[assignment]
            result = verify_click_token(token, "tenant-a")
        finally:
            ct.time.time = original  # type: ignore[assignment]
        assert not result.valid
        assert result.error == "expired"

    def test_garbage_token_rejected(self):
        from services.comms.click_token import verify_click_token
        for garbage in ("", "abc", "v1.only-two", "no-version.x.y"):
            result = verify_click_token(garbage, "tenant-a")
            assert not result.valid

    def test_key_rotation_old_version_still_verifies(self, monkeypatch):
        from services.comms import click_token as ct
        monkeypatch.setenv("COMMS_CLICK_TOKEN_KEYS", "1:old-secret,2:new-secret")
        monkeypatch.setenv("COMMS_CLICK_TOKEN_ACTIVE_VERSION", "1")
        token_v1 = ct.issue_click_token("tenant-a", campaign_id="c")
        assert token_v1.startswith("v1.")
        # Rotate: v2 signs, v1 still verifies
        monkeypatch.setenv("COMMS_CLICK_TOKEN_ACTIVE_VERSION", "2")
        token_v2 = ct.issue_click_token("tenant-a", campaign_id="c")
        assert token_v2.startswith("v2.")
        assert ct.verify_click_token(token_v1, "tenant-a").valid
        assert ct.verify_click_token(token_v2, "tenant-a").valid

    def test_unknown_key_version_rejected(self, monkeypatch):
        from services.comms import click_token as ct
        monkeypatch.setenv("COMMS_CLICK_TOKEN_KEYS", "1:secret-one")
        token = ct.issue_click_token("tenant-a")
        monkeypatch.setenv("COMMS_CLICK_TOKEN_KEYS", "9:different")
        result = ct.verify_click_token(token, "tenant-a")
        assert not result.valid


class TestEvidencePriority:
    def test_signed_token_outranks_all_other_evidence(self):
        from services.comms.click_token import CAMPAIGN_EVIDENCE_PRIORITY
        priorities = CAMPAIGN_EVIDENCE_PRIORITY
        assert priorities["signed_click_token"] < priorities["provider_click_id"]
        assert priorities["provider_click_id"] < priorities["utm_id"]
        assert priorities["utm_id"] < priorities["external_campaign_id"]
        assert priorities["external_campaign_id"] < priorities["utm_campaign_composite"]
        assert priorities["utm_campaign_composite"] < priorities["referrer_landing"]
        assert priorities["referrer_landing"] < priorities["manual_review"]
