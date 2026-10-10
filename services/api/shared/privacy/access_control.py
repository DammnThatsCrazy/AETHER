"""
Aether Privacy — Access Control Layer

Layered access model combining RBAC + ABAC + purpose-based access.
Provides field-level masking, graph traversal restrictions, and
export/training eligibility enforcement.
"""

from __future__ import annotations

import re
from typing import Any

from shared.privacy.classification import (
    DataClassification,
    AccessLevel,
    TrainingEligibility,
    classify_field,
    get_rules,
)
from shared.logger.logger import get_logger

logger = get_logger("aether.privacy.access")


# ═══════════════════════════════════════════════════════════════════════════
# ROLE HIERARCHY
# ═══════════════════════════════════════════════════════════════════════════

# Roles ordered from least to most privileged
ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "editor": 1,
    "support": 2,
    "compliance": 3,
    "data_science": 4,
    "admin": 5,
    "auditor": 6,  # Can read everything but not write
}

# Purpose-based access: what each purpose can see
PURPOSE_ACCESS: dict[str, set[DataClassification]] = {
    "operational": {
        DataClassification.PUBLIC,
        DataClassification.INTERNAL,
        DataClassification.CONFIDENTIAL,
    },
    "analytics": {
        DataClassification.PUBLIC,
        DataClassification.INTERNAL,
        DataClassification.CONFIDENTIAL,
    },
    "support": {
        DataClassification.PUBLIC,
        DataClassification.INTERNAL,
        DataClassification.CONFIDENTIAL,
        DataClassification.SENSITIVE_PII,
    },
    "compliance": {
        DataClassification.PUBLIC,
        DataClassification.INTERNAL,
        DataClassification.CONFIDENTIAL,
        DataClassification.SENSITIVE_PII,
        DataClassification.FINANCIAL,
        DataClassification.REGULATED,
    },
    "investigation": {
        DataClassification.PUBLIC,
        DataClassification.INTERNAL,
        DataClassification.CONFIDENTIAL,
        DataClassification.SENSITIVE_PII,
        DataClassification.FINANCIAL,
        DataClassification.REGULATED,
        DataClassification.HIGHLY_SENSITIVE,
    },
    "training": {
        DataClassification.PUBLIC,
        DataClassification.INTERNAL,
    },
    "export": {
        DataClassification.PUBLIC,
        DataClassification.INTERNAL,
        DataClassification.CONFIDENTIAL,
    },
}


def check_role_access(role: str, classification: DataClassification) -> bool:
    """Check if a role has sufficient privilege for a classification tier."""
    rules = get_rules(classification)
    min_role = rules.min_access_role
    role_level = ROLE_HIERARCHY.get(role.lower(), 0)
    min_level = ROLE_HIERARCHY.get(min_role, 0)
    return role_level >= min_level


def check_purpose_access(purpose: str, classification: DataClassification) -> bool:
    """Check if a declared purpose allows access to a classification tier."""
    allowed = PURPOSE_ACCESS.get(purpose, set())
    return classification in allowed


def get_field_access_level(
    field_name: str,
    role: str,
    purpose: str = "operational",
    consent_granted: bool = True,
) -> AccessLevel:
    """
    Determine the access level for a specific field given role, purpose, and consent.

    Returns: FULL, MASKED, METADATA_ONLY, DENIED, PURPOSE_BOUND, or INTERNAL_ONLY
    """
    classification = classify_field(field_name)
    rules = get_rules(classification)

    # Consent check
    if rules.requires_consent and not consent_granted:
        return AccessLevel.DENIED

    # Role check
    if not check_role_access(role, classification):
        if classification in (DataClassification.HIGHLY_SENSITIVE, DataClassification.REGULATED):
            return AccessLevel.DENIED
        return AccessLevel.MASKED

    # Purpose check
    if not check_purpose_access(purpose, classification):
        return AccessLevel.METADATA_ONLY

    # External visibility
    if purpose == "export" and not rules.externally_visible:
        return AccessLevel.DENIED

    return AccessLevel.FULL


# ═══════════════════════════════════════════════════════════════════════════
# FIELD-LEVEL MASKING
# ═══════════════════════════════════════════════════════════════════════════

# Regex patterns for sensitive values
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_PATTERN = re.compile(r"\+?\d[\d\s\-()]{7,}")
_WALLET_PATTERN = re.compile(r"0x[a-fA-F0-9]{40}")


def mask_value(value: Any, classification: DataClassification) -> Any:
    """Mask a value based on its classification tier."""
    if value is None:
        return None

    s = str(value)

    if classification == DataClassification.HIGHLY_SENSITIVE:
        return "***REDACTED***"

    if classification == DataClassification.REGULATED:
        if len(s) > 4:
            return s[:2] + "*" * (len(s) - 4) + s[-2:]
        return "****"

    if classification == DataClassification.FINANCIAL:
        if len(s) > 4:
            return "*" * (len(s) - 4) + s[-4:]
        return "****"

    if classification == DataClassification.SENSITIVE_PII:
        # Email masking
        if _EMAIL_PATTERN.match(s):
            parts = s.split("@")
            if len(parts) == 2:
                local = parts[0]
                masked_local = local[0] + "***" + (local[-1] if len(local) > 1 else "")
                return f"{masked_local}@{parts[1]}"

        # Phone masking
        if _PHONE_PATTERN.match(s):
            digits = re.sub(r"\D", "", s)
            if len(digits) > 4:
                return "*" * (len(digits) - 4) + digits[-4:]

        # General PII masking
        if len(s) > 4:
            return s[:2] + "*" * (len(s) - 4) + s[-2:]
        return "****"

    return value


def apply_field_masking(
    record: dict,
    role: str,
    purpose: str = "operational",
    consent_granted: bool = True,
) -> dict:
    """
    Apply field-level masking to a record based on role, purpose, and consent.
    Returns a new dict with sensitive fields masked or removed.
    """
    masked = {}
    for field_name, value in record.items():
        access = get_field_access_level(field_name, role, purpose, consent_granted)

        if access == AccessLevel.FULL:
            masked[field_name] = value
        elif access == AccessLevel.MASKED:
            classification = classify_field(field_name)
            masked[field_name] = mask_value(value, classification)
        elif access == AccessLevel.METADATA_ONLY:
            masked[field_name] = f"[{classify_field(field_name).value}]"
        elif access == AccessLevel.DENIED:
            continue  # Field omitted entirely
        else:
            masked[field_name] = value

    return masked


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH TRAVERSAL POLICY
# ═══════════════════════════════════════════════════════════════════════════


def can_traverse_edge(
    edge_type: str,
    role: str,
    purpose: str = "operational",
    is_inferred: bool = False,
    confidence: float = 1.0,
) -> bool:
    """
    Determine if a graph edge can be traversed given role, purpose, and
    edge characteristics.

    Inferred edges with low confidence are more restricted than
    directly observed edges.
    """
    # Inferred edges require higher privilege
    if is_inferred:
        if purpose in ("export", "training"):
            return False  # Never export or train on inferred edges
        if confidence < 0.5:
            # Low confidence inferred edges require compliance role
            return ROLE_HIERARCHY.get(role.lower(), 0) >= ROLE_HIERARCHY["compliance"]
        if confidence < 0.8:
            # Medium confidence requires at least editor
            return ROLE_HIERARCHY.get(role.lower(), 0) >= ROLE_HIERARCHY["editor"]

    # Regulated edge types
    regulated_edges = {
        "BENEFICIAL_OF", "AUTHORIZED_ON", "OVERLAPS_WITH",
        "LINKED_VIA", "KYC_FOR", "COMPLIANCE_ACTED_ON",
        "RESTRICTED_ON",
    }
    if edge_type in regulated_edges:
        return ROLE_HIERARCHY.get(role.lower(), 0) >= ROLE_HIERARCHY["compliance"]

    return True


def can_use_for_training(
    classification: DataClassification,
    consent_granted: bool = True,
    is_anonymized: bool = False,
) -> bool:
    """Check if data is eligible for ML training."""
    rules = get_rules(classification)
    eligibility = rules.training_eligibility

    if eligibility == TrainingEligibility.EXCLUDED:
        return False
    if eligibility == TrainingEligibility.CONSENT_REQUIRED and not consent_granted:
        return False
    if eligibility == TrainingEligibility.ANONYMIZED_ONLY and not is_anonymized:
        return False
    if eligibility == TrainingEligibility.AGGREGATE_ONLY:
        return False  # Individual records never eligible
    return True


# ═══════════════════════════════════════════════════════════════════════════
# LOG REDACTION
# ═══════════════════════════════════════════════════════════════════════════


def redact_for_logging(data: Any) -> Any:
    """
    Redact sensitive fields from data before logging.
    Recursively processes dicts and lists.
    """
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            classification = classify_field(key)
            rules = get_rules(classification)
            if rules.log_redaction_required:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_for_logging(value)
        return redacted
    elif isinstance(data, list):
        return [redact_for_logging(item) for item in data]
    elif isinstance(data, str):
        # Redact email patterns in string values
        result = _EMAIL_PATTERN.sub("[EMAIL_REDACTED]", data)
        # Redact phone patterns
        result = _PHONE_PATTERN.sub("[PHONE_REDACTED]", result)
        return result
    return data
