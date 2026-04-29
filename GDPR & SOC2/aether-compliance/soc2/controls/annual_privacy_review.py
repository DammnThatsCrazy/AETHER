"""
P-2.2 — Annual Privacy Review Process
Defines the annual review schedule, checklist, and findings register for
ongoing GDPR compliance monitoring.

Covers: consent mechanisms, privacy notices, retention compliance,
DSR performance against SLAs, sub-processor privacy compliance,
and processing activity register currency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReviewArea(str, Enum):
    CONSENT = "consent_mechanisms"
    PRIVACY_NOTICE = "privacy_notices"
    RETENTION = "data_retention"
    DSR_PERFORMANCE = "dsr_performance"
    SUB_PROCESSORS = "sub_processor_compliance"
    ROPA = "ropa_currency"
    DATA_PROTECTION = "data_protection_controls"
    CROSS_BORDER = "cross_border_transfers"
    TRAINING = "staff_training"


@dataclass
class ReviewFinding:
    finding_id: str
    area: ReviewArea
    severity: str     # low | medium | high
    description: str
    action_required: str
    owner: str
    due_date: str
    status: str = "open"


@dataclass
class AnnualPrivacyReview:
    """A completed annual privacy review record."""
    review_id: str
    year: int
    lead_reviewer: str
    review_date: str
    next_review_date: str
    areas_reviewed: list
    findings: list = field(default_factory=list)
    overall_rating: str = ""  # satisfactory | needs_improvement | unsatisfactory
    sign_off: str = ""
    completed: bool = False


REVIEW_CHECKLIST = {
    ReviewArea.CONSENT: [
        "Verify consent banners reflect current processing purposes",
        "Confirm consent withdrawal mechanism is functional across all platforms",
        "Review DNT header handling in SDK — verify dnt_respected=true",
        "Audit consent audit trail completeness (DynamoDB records)",
        "Verify consent records include all required fields (Art. 7(1))",
        "Check consent version alignment with current privacy notice",
    ],
    ReviewArea.PRIVACY_NOTICE: [
        "Review privacy notice accuracy against current ROPA",
        "Verify all processing purposes are disclosed",
        "Confirm sub-processor list is current and disclosed",
        "Verify cross-border transfer mechanisms are disclosed (SCCs)",
        "Check retention periods are accurately stated",
        "Verify DSR contact information and process is correct",
    ],
    ReviewArea.RETENTION: [
        "Verify S3 lifecycle rules are active on all data buckets",
        "Confirm per-tenant retention settings are within policy bounds",
        "Audit RDS/TimescaleDB for data older than configured retention",
        "Verify consent records (7-year retention) are preserved in DynamoDB",
        "Confirm backup deletion within 90 days of primary erasure (Art. 17)",
        "Review data lake Parquet file ages against maximum retention",
    ],
    ReviewArea.DSR_PERFORMANCE: [
        "Review all DSRs from past year: calculate average response time",
        "Verify no DSRs exceeded Art. 15/17 30-day SLA",
        "Confirm erasure requests completed cascading deletion across all 7+ stores",
        "Verify restriction requests had immediate effect",
        "Confirm DSR audit log entries are complete and immutable",
        "Review any DSR escalations or complaints",
    ],
    ReviewArea.SUB_PROCESSORS: [
        "Verify sub-processor register is current (all sub-processors listed)",
        "Confirm AWS DPA and SCCs are current and signed",
        "Audit any new sub-processors added in past year — PIA conducted?",
        "Verify notification procedure for sub-processor changes was followed",
        "Confirm all sub-processors have adequate security posture (certifications)",
        "Review TIA currency for all cross-border transfers",
    ],
    ReviewArea.ROPA: [
        "Review all 9 processing activities — confirm purpose and legal basis are current",
        "Identify any new processing activities not yet registered",
        "Confirm DPIA status for profiling/ML prediction activities",
        "Verify data category descriptions are accurate",
        "Check recipient and sub-processor lists per activity",
        "Update retention periods where tenant policies have changed",
    ],
    ReviewArea.DATA_PROTECTION: [
        "Re-run continuous compliance monitor — verify all checks pass",
        "Confirm encryption is active on all data stores (quarterly rotation check)",
        "Verify pseudonymization is applied in data lake pipeline",
        "Audit IP anonymization implementation — no raw IPs stored",
        "Review data minimization configuration per tenant",
        "Verify access controls aligned with classification policy",
    ],
    ReviewArea.CROSS_BORDER: [
        "Verify SCCs are current (post-Schrems II supplementary measures in place)",
        "Confirm TIA for each transfer is < 2 years old",
        "Review any new cross-border transfer routes added",
        "Verify QuickNode and other RPC sub-processors have adequate protections",
        "Check AWS region configurations — data not leaving agreed regions",
    ],
    ReviewArea.TRAINING: [
        "Confirm all staff completed annual privacy/security training",
        "Verify training covers current GDPR obligations and breach procedures",
        "Review training records for new joiners in past year",
        "Update training materials for any regulatory or procedural changes",
    ],
}


class AnnualPrivacyReviewProcess:
    """Manages the annual privacy review lifecycle."""

    def __init__(self):
        self.reviews: list[AnnualPrivacyReview] = []

    def initiate_review(
        self,
        year: int,
        lead_reviewer: str,
        review_date: str,
    ) -> AnnualPrivacyReview:
        review_id = f"APR-{year}"
        from datetime import datetime
        next_year = year + 1
        review = AnnualPrivacyReview(
            review_id=review_id,
            year=year,
            lead_reviewer=lead_reviewer,
            review_date=review_date,
            next_review_date=f"{next_year}-01-31",
            areas_reviewed=[],
        )
        self.reviews.append(review)
        return review

    def add_finding(
        self,
        review: AnnualPrivacyReview,
        area: ReviewArea,
        severity: str,
        description: str,
        action_required: str,
        owner: str,
        due_date: str,
    ) -> ReviewFinding:
        finding_id = f"{review.review_id}-F{len(review.findings) + 1:02d}"
        finding = ReviewFinding(
            finding_id=finding_id,
            area=area,
            severity=severity,
            description=description,
            action_required=action_required,
            owner=owner,
            due_date=due_date,
        )
        review.findings.append(finding)
        return finding

    def complete_review(
        self,
        review: AnnualPrivacyReview,
        overall_rating: str,
        sign_off: str,
    ) -> None:
        review.areas_reviewed = list(REVIEW_CHECKLIST.keys())
        review.overall_rating = overall_rating
        review.sign_off = sign_off
        review.completed = True

    def run_demo_review(self, year: int) -> AnnualPrivacyReview:
        """Run a demonstration annual review (all checks passing)."""
        review = self.initiate_review(year, "DPO / Privacy Lead", f"{year}-01-31")
        # Simulate completion with satisfactory rating
        self.complete_review(review, "satisfactory", "DPO")
        return review

    def total_checklist_items(self) -> int:
        return sum(len(items) for items in REVIEW_CHECKLIST.values())

    def generate_evidence(self) -> dict:
        completed = [r for r in self.reviews if r.completed]
        return {
            "control": "P-2.2",
            "artifact": "Annual Privacy Review Process",
            "review_areas": len(REVIEW_CHECKLIST),
            "total_checklist_items": self.total_checklist_items(),
            "reviews_completed": len(completed),
            "latest_rating": completed[-1].overall_rating if completed else "pending",
            "schedule": "Annual (complete by 31 January each year)",
            "status": "IMPLEMENTED",
            "evidence_type": "process_document",
        }

    def print_summary(self, review: AnnualPrivacyReview | None = None) -> None:
        total_items = self.total_checklist_items()
        print(f"\n  Annual Privacy Review Process")
        print(f"  Areas: {len(REVIEW_CHECKLIST)} | Checklist items: {total_items}")
        print(f"  Schedule: Annual (January deadline)")
        if review:
            status = "COMPLETE" if review.completed else "IN PROGRESS"
            print(f"\n  {review.year} Review: {status}")
            print(f"  Lead: {review.lead_reviewer}  |  Rating: {review.overall_rating}")
            print(f"  Sign-off: {review.sign_off}  |  Findings: {len(review.findings)}")
        print("\n  Areas covered:")
        for area, items in REVIEW_CHECKLIST.items():
            print(f"    {area.value:<30} {len(items)} checks")
