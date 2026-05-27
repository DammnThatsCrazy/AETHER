"""
Aether Privacy — PII Masking

Role-based PII masking for analyst-facing profile data.
Three analyst role tiers control what is visible:
  analyst_readonly   — full data, PII masked, no exports
  analyst_standard   — full data, PII masked, can export, can approve retarget recommendations
  analyst_compliance — can unmask PII, full wallet addresses, full export + profile

PII masking rules:
  Email:  j***@gmail.com          (first char + domain)
  Phone:  +1 ***-**78             (country code + last 2 digits)
  Name:   James T.                (first name + last initial)
  DOB:    age range only 35–44    (never exact)
  SSN/Tax ID: never returned in any role
  Wallet: masked to 0x1234...abcd for non-compliance roles (first 6 + last 4)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

AnalystRole = str  # 'analyst_readonly' | 'analyst_standard' | 'analyst_compliance'

_COMPLIANCE_ROLE = "analyst_compliance"

# Age range brackets (inclusive lower, exclusive upper)
_AGE_RANGES = [
    (18, 25, "18–24"),
    (25, 35, "25–34"),
    (35, 45, "35–44"),
    (45, 55, "45–54"),
    (55, 65, "55–64"),
    (65, 1000, "65+"),
]


def mask_email(email: str, role: AnalystRole) -> str:
    if role == _COMPLIANCE_ROLE:
        return email
    match = re.match(r"^(.)(.*)(@.+)$", email)
    if not match:
        return "***@***.***"
    return f"{match.group(1)}***{match.group(3)}"


def mask_phone(phone: str, role: AnalystRole) -> str:
    if role == _COMPLIANCE_ROLE:
        return phone
    # Keep country code and last 2 digits
    digits = re.sub(r"[^\d]", "", phone)
    if len(digits) >= 10:
        country = f"+{digits[0]}" if len(digits) > 10 else "+1"
        return f"{country} ***-**{digits[-2:]}"
    return "+* ***-**" + (digits[-2:] if len(digits) >= 2 else "**")


def mask_name(full_name: str, role: AnalystRole) -> str:
    if role == _COMPLIANCE_ROLE:
        return full_name
    parts = full_name.strip().split()
    if not parts:
        return "***"
    first = parts[0]
    last_initial = f" {parts[-1][0]}." if len(parts) > 1 else ""
    return f"{first}{last_initial}"


def mask_dob(dob: str | date | datetime, role: AnalystRole) -> str:
    """Returns age range string, never exact DOB."""
    if role == _COMPLIANCE_ROLE:
        return str(dob)
    try:
        if isinstance(dob, str):
            birth_date = date.fromisoformat(dob[:10])
        elif isinstance(dob, datetime):
            birth_date = dob.date()
        else:
            birth_date = dob
        today = date.today()
        age = today.year - birth_date.year - (
            (today.month, today.day) < (birth_date.month, birth_date.day)
        )
        for low, high, label in _AGE_RANGES:
            if low <= age < high:
                return label
        return "18+"
    except (ValueError, AttributeError):
        return "unknown"


def mask_wallet_address(address: str, role: AnalystRole) -> str:
    """For non-compliance roles: show first 6 + last 4 chars."""
    if role == _COMPLIANCE_ROLE:
        return address
    if len(address) > 10:
        return f"{address[:6]}...{address[-4:]}"
    return "***"


def mask_profile_pii(profile: dict[str, Any], role: AnalystRole) -> dict[str, Any]:
    """
    Apply PII masking to a profile dict in-place.
    Only modifies known PII fields — all other data passes through.
    """
    masked = dict(profile)

    if "email" in masked and masked["email"]:
        masked["email"] = mask_email(masked["email"], role)

    if "phone" in masked and masked["phone"]:
        masked["phone"] = mask_phone(masked["phone"], role)

    if "full_name" in masked and masked["full_name"]:
        masked["full_name"] = mask_name(masked["full_name"], role)

    if "date_of_birth" in masked and masked["date_of_birth"]:
        masked["date_of_birth"] = mask_dob(masked["date_of_birth"], role)

    # SSN / Tax ID — never returned in any role
    for field in ("ssn", "tax_id", "national_id", "social_security_number"):
        if field in masked:
            del masked[field]

    # Wallet addresses
    if "wallet_address" in masked and masked["wallet_address"]:
        masked["wallet_address"] = mask_wallet_address(masked["wallet_address"], role)

    if "wallets" in masked and isinstance(masked["wallets"], list):
        masked["wallets"] = [
            {**w, "wallet_address": mask_wallet_address(w.get("wallet_address", ""), role)}
            for w in masked["wallets"]
        ]

    return masked
