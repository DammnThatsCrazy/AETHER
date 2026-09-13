"""Email alias handling — normalization, tenant-scoped hashing, redacted
display, and shared-mailbox classification (Phase 9, ADR-C10).

Raw addresses never leave this module: callers receive
``(alias_hash, redacted_display)`` pairs. Hashing reuses the identity
service's tenant-scoped HMAC so the same address produces the same alias
across comms and identity evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.identity.hashing import hash_email
from services.identity.normalization import normalize_email

# Local parts that identify a role/shared mailbox rather than a person.
SHARED_MAILBOX_LOCAL_PARTS: frozenset[str] = frozenset({
    "sales", "support", "admin", "billing", "operations", "ops", "security",
    "contact", "info", "hello", "help", "team", "office", "hr", "careers",
    "jobs", "legal", "finance", "accounts", "accounting", "marketing",
    "press", "media", "partnerships", "partners", "webmaster", "postmaster",
    "abuse", "noc", "it", "devops", "engineering", "service", "services",
    "customerservice", "customer-service", "enquiries", "inquiries",
    "feedback", "orders", "returns", "no-reply", "noreply", "donotreply",
    "do-not-reply", "mailer-daemon", "notifications", "alerts", "news",
    "newsletter", "updates", "system", "root", "bounce", "bounces",
})


@dataclass(frozen=True)
class EmailAlias:
    """Privacy-safe representation of an email address."""
    alias_hash: str          # tenant-scoped HMAC — safe to store and join on
    display: str             # redacted, e.g. "j***@e***le.com"
    domain: str              # bare domain (retained for org resolution)
    is_shared_mailbox: bool  # role account — resolves to org, never a human
    local_part_class: str    # "personal" | "shared" | "no_reply"


def redact_email(normalized_email: str) -> str:
    """Redact an email for display: first char of local part + domain TLD hint.

    ``jane.doe@example.com`` → ``j***@e***.com``. Never reveals more than one
    character of the local part or the domain name.
    """
    local, _, domain = normalized_email.rpartition("@")
    if not local or not domain:
        return "***"
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    local_hint = local[0] if local else "*"
    domain_hint = domain[0] if domain else "*"
    return f"{local_hint}***@{domain_hint}***.{tld}" if tld else f"{local_hint}***@{domain_hint}***"


def classify_local_part(local: str) -> str:
    normalized = local.lower().strip()
    # strip plus-addressing before classification
    normalized = normalized.split("+", 1)[0]
    if normalized in ("no-reply", "noreply", "donotreply", "do-not-reply",
                      "mailer-daemon", "bounce", "bounces"):
        return "no_reply"
    if normalized in SHARED_MAILBOX_LOCAL_PARTS:
        return "shared"
    return "personal"


def build_email_alias(raw_email: str, tenant_id: str) -> Optional[EmailAlias]:
    """Normalize, hash, and classify an email address.

    Returns None when the input is not a plausible address. The raw value is
    not retained on the returned object.
    """
    normalized = normalize_email(raw_email or "")
    if not normalized or "@" not in normalized:
        return None
    local, _, domain = normalized.rpartition("@")
    if not local or not domain or "." not in domain:
        return None
    local_class = classify_local_part(local)
    return EmailAlias(
        alias_hash=hash_email(normalized, tenant_id),
        display=redact_email(normalized),
        domain=domain,
        is_shared_mailbox=local_class != "personal",
        local_part_class=local_class,
    )


def identity_confidence_for_alias(
    alias: EmailAlias,
    *,
    method: str = "provider_profile",
) -> float:
    """Identity confidence policy for email-derived evidence (Phase 9).

    Shared mailboxes never carry individual-human confidence: they resolve
    to the organization/team level.
    """
    if alias.local_part_class == "no_reply":
        return 0.0
    if alias.is_shared_mailbox:
        return 0.2  # organization-level evidence only
    return {
        "provider_profile": 0.7,        # probable
        "verified_mailbox": 0.9,        # strong — mailbox tied to account
        "authenticated_session": 1.0,   # deterministic — post-click auth
        "signed_click": 0.9,            # strong — signed token correlation
        "forwarded_link": 0.4,          # reduced — link may have travelled
        "open_pixel": 0.3,              # weak
    }.get(method, 0.5)
