"""Deterministic normalization for all identity signal types.

All normalization is deterministic and idempotent.
Raw PII is never stored; normalized forms are hashed before persistence.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Optional

from .hashing import normalize_wallet


def normalize_email(email: str) -> str:
    """Normalize email: strip whitespace, lowercase, validate format."""
    if not email:
        return ""
    v = email.strip().lower()
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", v):
        return ""
    return v


def normalize_phone(phone: str) -> str:
    """Normalize phone number toward E.164 where possible."""
    if not phone:
        return ""
    stripped = re.sub(r"[^\d+]", "", phone.strip())
    if not stripped:
        return ""
    if not stripped.startswith("+"):
        stripped = "+" + stripped
    if len(stripped) < 8 or len(stripped) > 16:
        return ""
    return stripped


def normalize_wallet_address(address: str, chain_namespace: str = "eip155") -> str:
    """Normalize a wallet address for the given chain."""
    return normalize_wallet(address, chain_namespace)


def normalize_user_id(user_id: str, tenant_id: str) -> str:
    """Produce a tenant-scoped normalized user ID key."""
    if not user_id or not tenant_id:
        return ""
    return f"{tenant_id}:{user_id.strip()}"


def normalize_anonymous_id(anon_id: str, tenant_id: str) -> str:
    """Produce a tenant-scoped anonymous ID key."""
    if not anon_id or not tenant_id:
        return ""
    return f"{tenant_id}:{anon_id.strip()}"


def normalize_session_id(session_id: str, tenant_id: str) -> str:
    """Produce a tenant-scoped session ID key."""
    if not session_id or not tenant_id:
        return ""
    return f"{tenant_id}:{session_id.strip()}"


def normalize_external_id(external_id: str, tenant_id: str) -> str:
    """Produce a tenant-scoped external customer/account ID key."""
    if not external_id or not tenant_id:
        return ""
    return f"{tenant_id}:{external_id.strip()}"


def normalize_agent_id(agent_id: str, tenant_id: str) -> str:
    """Produce a tenant-scoped agent ID key."""
    if not agent_id or not tenant_id:
        return ""
    return f"{tenant_id}:{agent_id.strip()}"


def normalize_org_id(org_id: str, tenant_id: str) -> str:
    """Produce a tenant-scoped org/account ID key."""
    if not org_id or not tenant_id:
        return ""
    return f"{tenant_id}:{org_id.strip()}"


def normalize_campaign(campaign: dict[str, Any]) -> dict[str, str]:
    """Normalize UTM/campaign attribution context."""
    return {
        "source": (campaign.get("source") or "").strip().lower(),
        "medium": (campaign.get("medium") or "").strip().lower(),
        "campaign": (campaign.get("campaign") or "").strip().lower(),
        "content": (campaign.get("content") or "").strip().lower(),
        "term": (campaign.get("term") or "").strip().lower(),
        "click_id": (campaign.get("clickId") or campaign.get("click_id") or "").strip(),
        "referrer_domain": _extract_domain(
            campaign.get("referrerDomain") or campaign.get("referrer_domain") or ""
        ),
    }


def _extract_domain(url_or_domain: str) -> str:
    if not url_or_domain:
        return ""
    try:
        parsed = urllib.parse.urlparse(url_or_domain)
        host = parsed.netloc or parsed.path
        return host.lower().split(":")[0]
    except Exception:
        return url_or_domain.lower()


def normalize_fingerprint(fp_value: str) -> str:
    """Normalize a device fingerprint token."""
    if not fp_value:
        return ""
    return fp_value.strip()


def extract_chain_namespace(wallet_data: dict[str, Any]) -> str:
    """Infer chain namespace from wallet data."""
    chain_id = str(wallet_data.get("chainId") or wallet_data.get("chain_id") or "")
    vm = str(wallet_data.get("vm") or wallet_data.get("vmType") or "").lower()
    if chain_id.startswith("eip155") or vm in ("evm", "eip155"):
        return "eip155"
    if vm in ("svm", "solana"):
        return "solana"
    if vm in ("cosmos", "cosmwasm"):
        return "cosmos"
    if vm in ("move", "aptos"):
        return "aptos"
    if "eip155" in chain_id:
        return "eip155"
    return "eip155"
