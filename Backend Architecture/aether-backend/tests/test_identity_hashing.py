"""Tests for identity hashing — no raw PII is ever persisted."""
from __future__ import annotations

import pytest

from services.identity.hashing import (
    hash_email,
    hash_external_id,
    hash_fingerprint,
    hash_phone,
    hash_value,
    hash_wallet,
    normalize_wallet,
    redact_display,
)


def test_hash_value_deterministic():
    assert hash_value("hello", "scope") == hash_value("hello", "scope")


def test_hash_value_different_scope():
    h1 = hash_value("hello", "scope_a")
    h2 = hash_value("hello", "scope_b")
    assert h1 != h2


def test_hash_value_empty_returns_empty():
    assert hash_value("", "scope") == ""


def test_hash_email_deterministic():
    h1 = hash_email("Alice@Example.COM", "tenant1")
    h2 = hash_email("alice@example.com", "tenant1")
    assert h1 == h2  # normalized before hashing


def test_hash_email_tenant_scoped():
    h1 = hash_email("alice@example.com", "tenant1")
    h2 = hash_email("alice@example.com", "tenant2")
    assert h1 != h2


def test_hash_email_invalid_returns_empty():
    assert hash_email("not-an-email", "tenant1") == ""
    assert hash_email("", "tenant1") == ""


def test_hash_phone_deterministic():
    h1 = hash_phone("+14155551234", "tenant1")
    h2 = hash_phone("+14155551234", "tenant1")
    assert h1 == h2


def test_hash_phone_tenant_scoped():
    h1 = hash_phone("+14155551234", "tenant1")
    h2 = hash_phone("+14155551234", "tenant2")
    assert h1 != h2


def test_hash_phone_strips_formatting():
    h1 = hash_phone("+1 (415) 555-1234", "tenant1")
    h2 = hash_phone("+14155551234", "tenant1")
    assert h1 == h2


def test_hash_phone_invalid_returns_empty():
    assert hash_phone("123", "tenant1") == ""
    assert hash_phone("", "tenant1") == ""


def test_hash_fingerprint_no_tenant_scope():
    h1 = hash_fingerprint("fp123")
    h2 = hash_fingerprint("fp123")
    assert h1 == h2


def test_hash_fingerprint_empty_returns_empty():
    assert hash_fingerprint("") == ""


def test_hash_external_id_tenant_scoped():
    h1 = hash_external_id("customer_001", "tenant1")
    h2 = hash_external_id("customer_001", "tenant2")
    assert h1 != h2


def test_hash_wallet_evm_normalized():
    h1 = hash_wallet("0xAbCdEf1234567890", "eip155")
    h2 = hash_wallet("0xabcdef1234567890", "eip155")
    assert h1 == h2  # lowercased


def test_hash_wallet_chain_scoped():
    h1 = hash_wallet("0xabc", "eip155")
    h2 = hash_wallet("0xabc", "solana")
    assert h1 != h2


def test_normalize_wallet_evm_lowercased():
    assert normalize_wallet("0xABCD", "eip155") == "0xabcd"


def test_normalize_wallet_solana_preserved():
    addr = "SoLaNaAdDrEsS1234567"
    assert normalize_wallet(addr, "solana") == addr


def test_normalize_wallet_empty_returns_empty():
    assert normalize_wallet("", "eip155") == ""


def test_redact_display_email():
    assert redact_display("alice@example.com", "email_hash") == "[REDACTED:email_hash]"


def test_redact_display_phone():
    assert redact_display("+14155551234", "phone_hash") == "[REDACTED:phone_hash]"


def test_redact_display_fingerprint():
    assert redact_display("fp-xyz-123", "device_fingerprint") == "[REDACTED:fingerprint]"


def test_redact_display_wallet_truncates():
    result = redact_display("0x1234567890abcdef", "wallet_address")
    assert "..." in result
    assert result.startswith("0x1234")


def test_redact_display_short_value_unchanged():
    result = redact_display("short", "wallet_address")
    assert result == "short"


def test_raw_email_never_stored():
    """Verify that hash_email returns a hash and NOT the raw email."""
    raw = "alice@example.com"
    h = hash_email(raw, "tenant1")
    assert raw not in h
    assert len(h) == 64  # HMAC-SHA256 hex is 64 chars


def test_raw_phone_never_stored():
    raw = "+14155551234"
    h = hash_phone(raw, "tenant1")
    assert raw not in h
    assert len(h) == 64
