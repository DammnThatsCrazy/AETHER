"""Unit tests — email alias hashing, redaction, shared mailboxes (Phase 9, ADR-C10)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


class TestAliasing:
    def test_normalization_is_case_insensitive(self):
        from services.comms.mailbox import build_email_alias
        a = build_email_alias("Jane.Doe@Example.COM", "t1")
        b = build_email_alias("jane.doe@example.com", "t1")
        assert a.alias_hash == b.alias_hash

    def test_tenant_scoped_hashes_differ(self):
        from services.comms.mailbox import build_email_alias
        a = build_email_alias("jane@example.com", "tenant-a")
        b = build_email_alias("jane@example.com", "tenant-b")
        assert a.alias_hash != b.alias_hash

    def test_invalid_address_returns_none(self):
        from services.comms.mailbox import build_email_alias
        assert build_email_alias("not-an-email", "t1") is None
        assert build_email_alias("", "t1") is None
        assert build_email_alias("a@b", "t1") is None


class TestPrivacy:
    """ADR-C10 — raw value never retained; display reveals ≤1 char per part."""

    def test_alias_object_contains_no_raw_address(self):
        from services.comms.mailbox import build_email_alias
        alias = build_email_alias("sensitive.person@bigcorp.com", "t1")
        flat = str(alias)
        assert "sensitive.person" not in flat
        assert "bigcorp.com" not in flat.replace(alias.domain, "")  # domain field is deliberate

    def test_redaction_format(self):
        from services.comms.mailbox import redact_email
        assert redact_email("jane.doe@example.com") == "j***@e***.com"
        assert redact_email("x@y.io") == "x***@y***.io"


class TestSharedMailboxes:
    """Phase 9 — role accounts never auto-identify a human."""

    @pytest.mark.parametrize("local", [
        "sales", "support", "admin", "billing", "operations", "security", "contact",
    ])
    def test_required_role_accounts_classified_shared(self, local):
        from services.comms.mailbox import build_email_alias
        alias = build_email_alias(f"{local}@example.com", "t1")
        assert alias.is_shared_mailbox, local

    def test_no_reply_classified(self):
        from services.comms.mailbox import build_email_alias
        alias = build_email_alias("no-reply@example.com", "t1")
        assert alias.local_part_class == "no_reply"

    def test_personal_address_not_shared(self):
        from services.comms.mailbox import build_email_alias
        alias = build_email_alias("jane.doe@example.com", "t1")
        assert not alias.is_shared_mailbox
        assert alias.local_part_class == "personal"

    def test_plus_addressing_stripped_before_classification(self):
        from services.comms.mailbox import build_email_alias
        alias = build_email_alias("support+ticket123@example.com", "t1")
        assert alias.is_shared_mailbox


class TestIdentityConfidence:
    """Phase 9 confidence policy."""

    def test_shared_mailbox_weak_for_individual(self):
        from services.comms.mailbox import build_email_alias, identity_confidence_for_alias
        shared = build_email_alias("support@example.com", "t1")
        assert identity_confidence_for_alias(shared) <= 0.2

    def test_no_reply_zero_confidence(self):
        from services.comms.mailbox import build_email_alias, identity_confidence_for_alias
        nr = build_email_alias("noreply@example.com", "t1")
        assert identity_confidence_for_alias(nr) == 0.0

    def test_method_ladder(self):
        from services.comms.mailbox import build_email_alias, identity_confidence_for_alias
        personal = build_email_alias("jane@example.com", "t1")
        ladder = [
            identity_confidence_for_alias(personal, method="open_pixel"),
            identity_confidence_for_alias(personal, method="forwarded_link"),
            identity_confidence_for_alias(personal, method="provider_profile"),
            identity_confidence_for_alias(personal, method="verified_mailbox"),
            identity_confidence_for_alias(personal, method="authenticated_session"),
        ]
        assert ladder == sorted(ladder), "confidence must increase with evidence strength"
        assert ladder[-1] == 1.0
