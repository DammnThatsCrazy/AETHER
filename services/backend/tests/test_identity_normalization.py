"""Tests for identity signal normalization."""
from __future__ import annotations

import pytest

from services.identity.normalization import (
    extract_chain_namespace,
    normalize_campaign,
    normalize_email,
    normalize_phone,
    normalize_user_id,
    normalize_wallet_address,
)


# ── Email normalization ────────────────────────────────────────────────────────

def test_normalize_email_lowercases():
    assert normalize_email("Alice@Example.COM") == "alice@example.com"


def test_normalize_email_strips_whitespace():
    assert normalize_email("  alice@example.com  ") == "alice@example.com"


def test_normalize_email_invalid_returns_empty():
    assert normalize_email("not-an-email") == ""
    assert normalize_email("@nodomain") == ""
    assert normalize_email("") == ""


def test_normalize_email_valid():
    assert normalize_email("alice@sub.example.com") == "alice@sub.example.com"


# ── Phone normalization ────────────────────────────────────────────────────────

def test_normalize_phone_strips_formatting():
    assert normalize_phone("+1 (415) 555-1234") == "+14155551234"


def test_normalize_phone_adds_plus_if_missing():
    result = normalize_phone("14155551234")
    assert result.startswith("+")


def test_normalize_phone_too_short_returns_empty():
    assert normalize_phone("123") == ""


def test_normalize_phone_empty_returns_empty():
    assert normalize_phone("") == ""


# ── User ID normalization ──────────────────────────────────────────────────────

def test_normalize_user_id_tenant_scoped():
    result = normalize_user_id("user_123", "tenant_a")
    assert result == "tenant_a:user_123"


def test_normalize_user_id_empty_returns_empty():
    assert normalize_user_id("", "tenant_a") == ""


# ── Wallet normalization ───────────────────────────────────────────────────────

def test_normalize_wallet_evm_lowercased():
    result = normalize_wallet_address("0xABCDef", "eip155")
    assert result == "0xabcdef"


def test_normalize_wallet_solana_preserved():
    addr = "SomeSolanaAddress123"
    assert normalize_wallet_address(addr, "solana") == addr


def test_normalize_wallet_empty_returns_empty():
    assert normalize_wallet_address("", "eip155") == ""


# ── Campaign normalization ─────────────────────────────────────────────────────

def test_normalize_campaign_extracts_utm():
    campaign = {
        "source": "google",
        "medium": "cpc",
        "campaign": "spring_sale",
        "content": "banner_a",
        "term": "running shoes",
    }
    result = normalize_campaign(campaign)
    assert result.get("source") == "google"
    assert result.get("medium") == "cpc"
    assert result.get("campaign") == "spring_sale"


def test_normalize_campaign_empty_dict():
    result = normalize_campaign({})
    assert isinstance(result, dict)


def test_normalize_campaign_missing_keys_returns_empty_strings():
    result = normalize_campaign({"source": "google"})
    assert result.get("medium") == ""


# ── Chain namespace extraction ─────────────────────────────────────────────────

def test_extract_chain_namespace_evm_chain_id():
    wallet = {"chainId": "eip155:1"}
    assert extract_chain_namespace(wallet) == "eip155"


def test_extract_chain_namespace_explicit_solana():
    wallet = {"vm": "solana"}
    assert extract_chain_namespace(wallet) == "solana"


def test_extract_chain_namespace_default():
    assert extract_chain_namespace({}) == "eip155"
