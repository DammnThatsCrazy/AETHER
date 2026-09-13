"""
Aether Agent Layer — Quality Scorer Enrichment Worker
Evaluates data quality of entity records and assigns composite scores.

Capabilities:
  - Completeness: what % of expected fields are populated?
  - Freshness: how recently was each field updated?
  - Consistency: do cross-referenced fields agree?
  - Source reliability: weight by source trust score
  - Composite DQ score (0-1) written back to entity metadata
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from config.settings import WorkerType
from models.core import AgentTask, TaskResult

from workers.base import BaseWorker

logger = logging.getLogger("aether.worker.quality_scorer")

# Source trust scores (higher = more reliable)
_SOURCE_TRUST: dict[str, float] = {
    "etherscan": 0.95,
    "dune_analytics": 0.90,
    "sec_edgar": 0.92,
    "crunchbase": 0.85,
    "clearbit": 0.80,
    "apollo": 0.78,
    "linkedin": 0.75,
    "github": 0.80,
    "twitter_x": 0.60,
    "reddit": 0.50,
    "web_crawl": 0.55,
    "web_scrape": 0.50,
    "web_domain": 0.55,
    "llm_inference": 0.45,
    "user_submitted": 0.70,
    "manual": 0.60,
    "heuristic": 0.50,
    "interpolation": 0.40,
    "inferred": 0.45,
}

# Field freshness decay (days -> penalty multiplier)
_FRESHNESS_DECAY_DAYS = 90  # fields older than this get penalized

# Composite score weights
_WEIGHT_COMPLETENESS = 0.30
_WEIGHT_FRESHNESS = 0.25
_WEIGHT_RELIABILITY = 0.25
_WEIGHT_CONSISTENCY = 0.20

# Entity type -> fields that indicate type mismatch
_TYPE_EXCLUSIVE_FIELDS: dict[str, set[str]] = {
    "company": {"legal_name", "employee_count", "founded_year", "headquarters", "industry"},
    "person": {"first_name", "last_name", "full_name", "title", "bio"},
    "wallet": {"ens_name", "total_tx_count", "net_worth_usd", "wallet_address"},
}


class QualityScorerWorker(BaseWorker):
    """
    Enrichment worker that scores entity data quality.

    Payload contract:
        entity_id      : str           — graph entity to score
        entity_data    : dict          — current entity fields + values
        field_metadata : dict          — {field: {"source": str, "updated_at": str}}
        required_fields: list[str]     — fields expected for this entity type
    """

    worker_type = WorkerType.QUALITY_SCORER
    data_source = "general_web"  # no external calls, but keep for consistency

    def _execute(self, task: AgentTask) -> TaskResult:
        entity_id = task.payload.get("entity_id", "")
        entity_data: dict[str, Any] = task.payload.get("entity_data", {})
        field_meta: dict[str, dict] = task.payload.get("field_metadata", {})
        required = task.payload.get("required_fields", list(entity_data.keys()))

        logger.info(
            f"Scoring quality for entity {entity_id}: "
            f"{len(entity_data)} fields, {len(required)} required"
        )

        try:
            # -- Completeness --
            completeness, populated = self._score_completeness(
                entity_data, required
            )

            # -- Freshness --
            freshness, freshness_scores, stale_fields = self._score_freshness(
                populated, field_meta
            )

            # -- Source reliability --
            source_reliability, source_scores = self._score_source_reliability(
                populated, field_meta
            )

            # -- Consistency --
            consistency, consistency_issues = self._score_consistency(
                entity_data
            )

            # -- Composite score (weighted average) --
            composite = round(
                completeness * _WEIGHT_COMPLETENESS
                + freshness * _WEIGHT_FRESHNESS
                + source_reliability * _WEIGHT_RELIABILITY
                + consistency * _WEIGHT_CONSISTENCY,
                4,
            )

        except Exception as exc:
            logger.exception(f"Quality scoring failed for {entity_id}: {exc}")
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                data={"error": str(exc), "entity_id": entity_id},
                confidence=0.0,
                source_attribution="quality_scorer:error",
            )

        data = {
            "entity_id": entity_id,
            "scores": {
                "completeness": round(completeness, 4),
                "freshness": round(freshness, 4),
                "source_reliability": round(source_reliability, 4),
                "consistency": round(consistency, 4),
                "composite": composite,
            },
            "populated_fields": len(populated),
            "required_fields": len(required),
            "stale_fields": stale_fields,
            "consistency_issues": consistency_issues,
            "field_scores": {
                f: {
                    "fresh": round(freshness_scores[i], 3) if i < len(freshness_scores) else 0,
                    "source_trust": round(source_scores[i], 3) if i < len(source_scores) else 0,
                }
                for i, f in enumerate(populated)
            },
        }
        confidence = composite  # quality score IS the confidence

        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=True,
            data=data,
            confidence=round(confidence, 3),
            source_attribution="quality_scorer:internal",
        )

    # ------------------------------------------------------------------
    # Dimension: Completeness
    # ------------------------------------------------------------------

    def _score_completeness(
        self,
        entity_data: dict[str, Any],
        required: list[str],
    ) -> tuple[float, list[str]]:
        """
        Ratio of required_fields that are present and non-empty.
        Returns (score, list_of_populated_field_names).
        """
        populated: list[str] = []
        for f in required:
            if f in entity_data:
                val = entity_data[f]
                if val is not None and val != "" and val != []:
                    populated.append(f)

        score = len(populated) / max(len(required), 1)
        return score, populated

    # ------------------------------------------------------------------
    # Dimension: Freshness
    # ------------------------------------------------------------------

    def _score_freshness(
        self,
        populated: list[str],
        field_meta: dict[str, dict],
    ) -> tuple[float, list[float], list[str]]:
        """
        For each populated field with a timestamp in field_metadata,
        compute age in days. Score inversely proportional to age.
        Returns (overall_freshness, per_field_scores, stale_field_names).
        """
        now = datetime.now(timezone.utc)
        freshness_scores: list[float] = []
        stale_fields: list[str] = []

        for field_name in populated:
            meta = field_meta.get(field_name, {})
            updated_str = meta.get("updated_at")

            if updated_str:
                try:
                    updated = datetime.fromisoformat(updated_str)
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    age_days = (now - updated).days

                    # Inverse linear decay: fresh (0 days) = 1.0,
                    # at decay threshold = 0.0, clamped
                    score = max(1.0 - (age_days / _FRESHNESS_DECAY_DAYS), 0.0)
                    freshness_scores.append(score)

                    if age_days > _FRESHNESS_DECAY_DAYS:
                        stale_fields.append(field_name)
                except (ValueError, TypeError):
                    # Unparseable date -> assign mid score
                    freshness_scores.append(0.5)
            else:
                # No timestamp available -> unknown age, assign mid score
                freshness_scores.append(0.5)

        overall = (
            sum(freshness_scores) / max(len(freshness_scores), 1)
        )
        return overall, freshness_scores, stale_fields

    # ------------------------------------------------------------------
    # Dimension: Source Reliability
    # ------------------------------------------------------------------

    def _score_source_reliability(
        self,
        populated: list[str],
        field_meta: dict[str, dict],
    ) -> tuple[float, list[float]]:
        """
        Score based on known source trustworthiness.
        Returns (overall_reliability, per_field_scores).
        """
        source_scores: list[float] = []

        for field_name in populated:
            meta = field_meta.get(field_name, {})
            src = meta.get("source", "")

            if src:
                # Normalize source name for lookup
                src_normalized = src.lower().strip().replace(" ", "_").replace("-", "_")
                trust = _SOURCE_TRUST.get(src_normalized, 0.5)
            else:
                # No source attribution -> low trust
                trust = 0.4

            source_scores.append(trust)

        overall = (
            sum(source_scores) / max(len(source_scores), 1)
        )
        return overall, source_scores

    # ------------------------------------------------------------------
    # Dimension: Consistency
    # ------------------------------------------------------------------

    def _score_consistency(
        self,
        entity_data: dict[str, Any],
    ) -> tuple[float, list[str]]:
        """
        Check for contradictions between fields.
        Returns (score 0.0-1.0, list_of_issue_descriptions).
        1.0 = fully consistent, 0.0 = many contradictions.
        """
        checks: list[bool] = []
        issues: list[str] = []

        # Check 1: website and domain should agree
        website = str(entity_data.get("website", ""))
        domain = str(entity_data.get("domain", ""))
        if website and domain:
            domain_clean = domain.lower().replace("www.", "")
            website_clean = website.lower().replace("www.", "")
            consistent = domain_clean in website_clean
            checks.append(consistent)
            if not consistent:
                issues.append(
                    f"Domain '{domain}' not found in website '{website}'"
                )

        # Check 2: employee_count should be a positive number
        emp = entity_data.get("employee_count")
        if emp is not None:
            valid = isinstance(emp, (int, float)) and emp >= 0
            checks.append(valid)
            if not valid:
                issues.append(
                    f"Invalid employee_count: {emp} (expected non-negative number)"
                )

        # Check 3: founded_year should be reasonable (1800 - current year)
        year = entity_data.get("founded_year")
        if year is not None:
            current_year = datetime.now().year
            valid = isinstance(year, int) and 1800 <= year <= current_year
            checks.append(valid)
            if not valid:
                issues.append(
                    f"Invalid founded_year: {year} (expected 1800-{current_year})"
                )

        # Check 4: entity_type vs field presence consistency
        entity_type = entity_data.get("entity_type", "")
        if entity_type:
            entity_fields = set(entity_data.keys())
            for etype, exclusive_fields in _TYPE_EXCLUSIVE_FIELDS.items():
                if etype == entity_type:
                    continue
                # Fields that belong to other entity types shouldn't be here
                conflicting = entity_fields & exclusive_fields
                if conflicting:
                    # Only flag if more than 2 conflicting fields
                    # (one or two might be legitimate overlap)
                    if len(conflicting) > 2:
                        checks.append(False)
                        issues.append(
                            f"Entity type '{entity_type}' has fields "
                            f"typical of '{etype}': {conflicting}"
                        )

        # Check 5: date fields should be in logical order
        date_fields_ordered = [
            ("founded_year", "last_funding_round"),
            ("first_seen", "last_active"),
            ("created_at", "updated_at"),
            ("start_date", "end_date"),
        ]
        for earlier_field, later_field in date_fields_ordered:
            earlier = entity_data.get(earlier_field)
            later = entity_data.get(later_field)
            if earlier is not None and later is not None:
                try:
                    e_val = _to_comparable_date(earlier)
                    l_val = _to_comparable_date(later)
                    if e_val is not None and l_val is not None:
                        valid = e_val <= l_val
                        checks.append(valid)
                        if not valid:
                            issues.append(
                                f"Date order violation: {earlier_field}={earlier} "
                                f"should be before {later_field}={later}"
                            )
                except (ValueError, TypeError):
                    pass

        # Check 6: email format validation
        email = entity_data.get("email", "")
        if email:
            valid = bool(re.match(
                r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
                str(email),
            ))
            checks.append(valid)
            if not valid:
                issues.append(f"Invalid email format: {email}")

        # Check 7: URL format validation
        for url_field in ("website", "linkedin_url"):
            url = entity_data.get(url_field, "")
            if url:
                valid = bool(re.match(
                    r"^https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                    str(url),
                ))
                checks.append(valid)
                if not valid:
                    issues.append(f"Invalid URL format in {url_field}: {url}")

        # Check 8: funding_total_usd should be non-negative
        funding = entity_data.get("funding_total_usd")
        if funding is not None:
            valid = isinstance(funding, (int, float)) and funding >= 0
            checks.append(valid)
            if not valid:
                issues.append(
                    f"Invalid funding_total_usd: {funding} (expected non-negative)"
                )

        if not checks:
            return 0.8, issues  # no checks applicable -> assume decent

        score = sum(checks) / len(checks)
        return score, issues


# ── Helpers ───────────────────────────────────────────────────────────

def _to_comparable_date(value: Any) -> datetime | None:
    """
    Convert various date representations to a datetime for comparison.
    Handles: int (year), str (ISO-8601), datetime objects.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, int):
        # Treat as a year
        if 1800 <= value <= 2100:
            return datetime(value, 1, 1, tzinfo=timezone.utc)
        return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None
    return None
