"""
C-2.1 — Formal Data Classification Policy
Bridges the technical classification taxonomy in
Backend Architecture/aether-backend/shared/privacy/classification.py
into a formal policy document with handling requirements per tier.

The 7-tier technical taxonomy (PUBLIC → HIGHLY_SENSITIVE) is already implemented
in code. This module documents the formal policy, handling matrix, and labelling
requirements that satisfy the SOC 2 Confidentiality criterion.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClassificationTier:
    """Formal handling requirements for a classification level."""
    level: str
    label: str
    examples: list
    storage_requirements: str
    transmission_requirements: str
    access_requirements: str
    retention: str
    deletion_method: str
    training_eligible: bool
    external_sharing: str


CLASSIFICATION_POLICY: list[ClassificationTier] = [
    ClassificationTier(
        level="PUBLIC",
        label="Public",
        examples=["Marketing content", "Public API documentation", "Open-source code"],
        storage_requirements="No encryption required (encryption applied by default via KMS)",
        transmission_requirements="HTTPS recommended, no strict enforcement",
        access_requirements="No restrictions",
        retention="Permanent",
        deletion_method="Hard delete",
        training_eligible=True,
        external_sharing="Freely shareable",
    ),
    ClassificationTier(
        level="INTERNAL",
        label="Internal",
        examples=["Architecture diagrams", "Non-sensitive logs", "Internal configs"],
        storage_requirements="Encrypted at rest (AES-256 KMS)",
        transmission_requirements="TLS 1.3 required",
        access_requirements="Aether employees and contractors only",
        retention="1 year",
        deletion_method="Hard delete",
        training_eligible=True,
        external_sharing="Not for external sharing without approval",
    ),
    ClassificationTier(
        level="CONFIDENTIAL",
        label="Confidential",
        examples=["Customer behavioral events", "Session data", "Risk/trust scores", "Device fingerprints"],
        storage_requirements="Encrypted at rest (AES-256 KMS). Access logged.",
        transmission_requirements="TLS 1.3 required. No transmission outside tenant boundary without SCCs.",
        access_requirements="Minimum role: Editor. Access logged and audited.",
        retention="Per tenant config (default 90 days, max 7 years)",
        deletion_method="Hard delete or pseudonymize on DSAR",
        training_eligible=True,
        external_sharing="Permitted under DPA/SCCs only",
    ),
    ClassificationTier(
        level="SENSITIVE_PII",
        label="Sensitive PII",
        examples=["Email addresses", "Phone numbers", "IP addresses", "Full names", "Dates of birth"],
        storage_requirements="Encrypted at rest. Field-level encryption for highest-risk fields. Pseudonymized in data lake.",
        transmission_requirements="TLS 1.3 required. Pseudonymized before leaving ingest boundary.",
        access_requirements="Minimum role: Editor. Consent required. Purpose binding enforced. Log redaction required.",
        retention="Per tenant config. Deleted within 30 days of DSAR.",
        deletion_method="Pseudonymize (SHA-256 + per-tenant salt)",
        training_eligible=False,
        external_sharing="Never exported raw. Aggregated/anonymized exports only with approval.",
    ),
    ClassificationTier(
        level="FINANCIAL",
        label="Financial",
        examples=["Payment amounts", "Account numbers", "Transaction hashes", "Balance data"],
        storage_requirements="Encrypted at rest. Field-level encryption. 7-year compliance retention.",
        transmission_requirements="TLS 1.3. Encrypted payloads. Tokenization where possible.",
        access_requirements="Minimum role: Editor. Contract basis (Art. 6(1)(b)). Export requires approval.",
        retention="7 years (financial record compliance)",
        deletion_method="Pseudonymize (retain structure, remove PII)",
        training_eligible=False,
        external_sharing="Requires written approval and DPA amendment.",
    ),
    ClassificationTier(
        level="REGULATED",
        label="Regulated",
        examples=["KYC status", "AML flags", "Sanctions matches", "Beneficial owner records"],
        storage_requirements="Encrypted at rest. Field-level encryption. No graph traversal. Compliance team only.",
        transmission_requirements="TLS 1.3. Encrypted payloads. Cross-border only under specific legal basis.",
        access_requirements="Minimum role: Compliance. Legal obligation basis. Export prohibited. Audit every access.",
        retention="7 years or as required by applicable regulation",
        deletion_method="Tombstone (mark deleted, retain for legal hold)",
        training_eligible=False,
        external_sharing="Prohibited without explicit legal basis and DPA documentation.",
    ),
    ClassificationTier(
        level="HIGHLY_SENSITIVE",
        label="Highly Sensitive",
        examples=["SSN/TIN", "Passport numbers", "Encryption keys", "Private keys", "Raw API key material"],
        storage_requirements="Encrypted at rest via AWS KMS with customer-managed keys. HSM-backed where applicable.",
        transmission_requirements="Envelope encryption. Never transmitted in plaintext. Key material stored only in Secrets Manager.",
        access_requirements="Minimum role: Admin. Break-glass process required. Every access triggers PagerDuty alert.",
        retention="Until deletion requested or key rotated",
        deletion_method="Key destroy (encryption key deletion renders data unreadable)",
        training_eligible=False,
        external_sharing="Absolutely prohibited.",
    ),
]

LABELLING_REQUIREMENTS = """
Data Labelling Requirements
===========================
1. All new data stores must declare a classification tier in their Terraform module tags.
2. API response models must declare field-level classifications via ClassificationRules.
3. S3 buckets must have an 'aether:data-classification' tag set to one of the 7 levels.
4. Database schemas must include a 'classification' column or table-level comment.
5. ML features must declare training_eligible and classification_tier in the feature registry.
6. Sub-processors must declare what classification tiers they process in the sub-processor register.
"""


class DataClassificationPolicy:
    """Formal data classification policy with handling matrix."""

    def __init__(self):
        self.tiers = CLASSIFICATION_POLICY

    def get_tier(self, level: str) -> ClassificationTier | None:
        return next((t for t in self.tiers if t.level == level), None)

    def generate_evidence(self) -> dict:
        return {
            "control": "C-2.1",
            "artifact": "Data Classification Policy",
            "tiers_defined": len(self.tiers),
            "tier_names": [t.level for t in self.tiers],
            "training_eligible_tiers": [t.level for t in self.tiers if t.training_eligible],
            "technical_implementation": "shared/privacy/classification.py (7-tier taxonomy, FIELD_CLASSIFICATIONS registry)",
            "status": "IMPLEMENTED",
            "evidence_type": "policy_document",
        }

    def print_matrix(self) -> None:
        print(f"\n  Data Classification Policy — {len(self.tiers)} tiers\n")
        print(f"  {'Level':<18} {'Access Req.':<25} {'Training':>9} {'External Sharing'}")
        print(f"  {'—'*18} {'—'*25} {'—'*9} {'—'*30}")
        for t in self.tiers:
            print(f"  {t.label:<18} {t.access_requirements[:24]:<25} {'Yes' if t.training_eligible else 'No':>9} {t.external_sharing[:30]}")
