"""Identity claim normalizer — normalizes email, phone, provider IDs, and anonymous IDs.

Normalization rules:
- email: lowercase, strip, normalize common domain variants
- phone: E.164 format (international)
- provider IDs: preserve meaning, normalize whitespace/case
- anonymous IDs: lowercase, strip
"""

from __future__ import annotations

import re
from typing import Optional


# Common email domain normalization map
_EMAIL_DOMAIN_NORMALIZE = {
    "gmail.com": "gmail.com",
    "googlemail.com": "gmail.com",
    "yahoo.com": "yahoo.com",
    "yahoo.co.uk": "yahoo.com",
    "hotmail.com": "hotmail.com",
    "live.com": "hotmail.com",
    "outlook.com": "outlook.com",
}


def normalize_email(email: str) -> str:
    """Normalize an email address for identity matching.

    - Lowercase
    - Strip whitespace
    - Normalize domain variants (googlemail.com -> gmail.com)
    - Remove plus addressing tags for matching (but preserve raw for display)
    """
    if not email:
        return ""

    email = email.strip().lower()

    # Split local and domain
    if "@" not in email:
        return email

    local, domain = email.rsplit("@", 1)

    # Normalize domain
    domain = _EMAIL_DOMAIN_NORMALIZE.get(domain, domain)

    # Remove plus addressing for matching (user+tag@gmail.com -> user@gmail.com)
    if "+" in local:
        local = local.split("+")[0]

    # Remove dots in gmail local part (user.name@gmail.com -> username@gmail.com)
    if domain == "gmail.com":
        local = local.replace(".", "")

    return f"{local}@{domain}"


def normalize_phone(phone: str) -> str:
    """Normalize a phone number to E.164 format.

    Strips all non-digit characters except leading +.
    If the number doesn't start with +, assumes US (+1) for 10-digit numbers.
    """
    if not phone:
        return ""

    phone = phone.strip()

    # Extract digits and leading +
    has_plus = phone.startswith("+")
    digits = re.sub(r"[^\d]", "", phone)

    if not digits:
        return ""

    # Assume US for 10-digit numbers without country code
    if len(digits) == 10 and not has_plus:
        digits = "1" + digits

    # Return with E.164 format
    if has_plus or digits.startswith("+"):
        return "+" + digits.lstrip("+")
    elif len(digits) >= 11:
        return "+" + digits
    else:
        return digits


def normalize_provider_id(identifier: str) -> str:
    """Normalize a provider/customer identifier.

    Preserves the semantic value but normalizes whitespace and case.
    Shopify customer IDs, Stripe customer IDs, CRM contact IDs, etc.
    """
    if not identifier:
        return ""

    identifier = identifier.strip()

    # Lowercase for case-insensitive providers
    # Preserve case for case-sensitive providers (most keep original case)
    return identifier


def normalize_anonymous_id(anonymous_id: str) -> str:
    """Normalize an anonymous ID."""
    if not anonymous_id:
        return ""

    return anonymous_id.strip().lower()


def normalize_device_id(device_id: str) -> str:
    """Normalize a device ID."""
    if not device_id:
        return ""

    return device_id.strip().lower()


def normalize_installation_id(installation_id: str) -> str:
    """Normalize a mobile installation ID."""
    if not installation_id:
        return ""

    return installation_id.strip().lower()
