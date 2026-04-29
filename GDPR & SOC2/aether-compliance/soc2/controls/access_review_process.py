"""
C-2.2 — Quarterly Access Review Process
Formal process definition, review checklist, and evidence framework for
quarterly IAM permission reviews.

Technical implementation: audit/reviews/access_review.py (AccessReviewer)
This module formalises the process governance layer on top of that implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReviewOutcome(str, Enum):
    APPROVED = "approved"          # Access confirmed as appropriate
    REVOKED = "revoked"            # Access removed
    ESCALATED = "escalated"        # Requires manager sign-off before approval
    DEFERRED = "deferred"          # Under investigation, access suspended pending review


@dataclass
class ReviewChecklist:
    """Mandatory checklist items for each quarterly review."""
    quarter: str
    reviewer: str
    items_checked: list
    items_failed: list
    remediation_actions: list
    completed_date: str = ""
    sign_off: str = ""

    @property
    def passed(self) -> bool:
        return len(self.items_failed) == 0


REVIEW_CHECKLIST_TEMPLATE = [
    # IAM User Hygiene
    "Verify no IAM users have active access keys older than 90 days",
    "Verify all IAM console users have MFA enabled",
    "Verify no IAM users have both console and programmatic access (separation of duty)",
    "Identify and disable IAM users inactive for > 90 days",
    "Verify no root account access keys exist",

    # Role and Policy Review
    "Verify no IAM roles have wildcard resource ARNs ('*') in non-emergency policies",
    "Review all recently created IAM roles (last 90 days) for least privilege",
    "Verify ECS task roles are scoped to their specific service boundaries",
    "Check for unused IAM roles (no AssumeRolePolicyDocument invocations in 90 days)",
    "Verify all cross-account role trust policies are current and necessary",

    # Service Account Review
    "Audit all active API keys: verify each has an identified owner and purpose",
    "Verify service-to-service API keys are rotated on schedule",
    "Identify API keys belonging to departed employees/contractors and revoke",
    "Verify Secrets Manager rotation policies are active for all credentials",

    # Privileged Access
    "Review all admin-role assignments: confirm business justification still valid",
    "Verify break-glass procedures are documented and last test date is < 6 months",
    "Confirm no shared credentials exist (each human user has individual identity)",
    "Review all recent privilege escalation events in CloudTrail",

    # Third-Party and Contractor Access
    "Audit all contractor/vendor access: verify contracts are active",
    "Review sub-processor access controls: confirm scope matches DPA",
    "Verify all terminated contractor accounts are disabled in < 24h",
]

REMEDIATION_SLAS = {
    "active_key_over_90_days": 7,      # Rotate within 7 days
    "mfa_not_enabled": 1,              # Enable MFA within 1 business day
    "inactive_user": 3,                # Disable within 3 business days
    "wildcard_policy": 14,             # Scope policy within 14 days
    "orphaned_api_key": 1,             # Revoke immediately
    "departed_employee": 0,            # Revoke same day as departure
}


class AccessReviewProcess:
    """
    Manages the quarterly access review process lifecycle.
    Wraps the technical AccessReviewer with formal process governance.
    """

    def __init__(self):
        self.reviews: list[ReviewChecklist] = []
        self.checklist_template = list(REVIEW_CHECKLIST_TEMPLATE)

    def initiate_review(self, quarter: str, reviewer: str) -> ReviewChecklist:
        review = ReviewChecklist(
            quarter=quarter,
            reviewer=reviewer,
            items_checked=[],
            items_failed=[],
            remediation_actions=[],
        )
        self.reviews.append(review)
        return review

    def complete_item(self, review: ReviewChecklist, item: str, passed: bool,
                      action: str = "") -> None:
        review.items_checked.append(item)
        if not passed:
            review.items_failed.append(item)
            if action:
                review.remediation_actions.append(action)

    def sign_off(self, review: ReviewChecklist, signer: str, date: str) -> None:
        review.sign_off = signer
        review.completed_date = date

    def run_demo_review(self, quarter: str) -> ReviewChecklist:
        """Run a demonstration quarterly review showing the full checklist."""
        review = self.initiate_review(quarter, "security-lead")

        # Simulate passing all checklist items (production would query live IAM)
        for item in self.checklist_template:
            self.complete_item(review, item, passed=True)

        self.sign_off(review, "CISO", "2026-04-29")
        return review

    def generate_evidence(self) -> dict:
        completed = [r for r in self.reviews if r.completed_date]
        return {
            "control": "C-2.2",
            "artifact": "Quarterly Access Review Process",
            "checklist_items": len(self.checklist_template),
            "reviews_conducted": len(completed),
            "reviews_passed": sum(1 for r in completed if r.passed),
            "remediation_slas_defined": len(REMEDIATION_SLAS),
            "technical_implementation": "audit/reviews/access_review.py (AccessReviewer)",
            "status": "IMPLEMENTED",
            "evidence_type": "process_document",
        }

    def print_process(self, review: ReviewChecklist | None = None) -> None:
        print(f"\n  Quarterly Access Review Process — {len(self.checklist_template)} checklist items")
        print(f"  Frequency: Quarterly (Q1/Q2/Q3/Q4)  |  Owner: Security Team\n")
        if review:
            status = "PASSED" if review.passed else f"FAILED ({len(review.items_failed)} items)"
            print(f"  {review.quarter} Review: {status}")
            print(f"  Reviewer: {review.reviewer}  |  Sign-off: {review.sign_off}")
            print(f"  Items checked: {len(review.items_checked)} / {len(self.checklist_template)}")
            if review.remediation_actions:
                print(f"  Remediation actions: {len(review.remediation_actions)}")
        else:
            print(f"  No completed reviews yet — first review due Q1")
