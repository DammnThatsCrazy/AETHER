"""Semantic data-subject-rights handler — erasure and consent restriction.

Propagates a deletion or consent revocation across the semantic surfaces so a
revoked subject's semantic observations, sentiment, aggregate state and review
items do not persist. Produces a verifiable result (per-table counts + errors)
that binds into the DSR propagation record. Imitates
``services/measurement/privacy.py``.
"""

from __future__ import annotations

from typing import Any

from shared.logger.logger import get_logger

from .models import ObservationStatus
from .repositories.base_fact_repo import SemanticFactRepository
from .repositories.review_queue_repo import SemanticReviewQueueRepository

logger = get_logger("aether.semantic.privacy")

# Subject-linked semantic tables an erasure/restriction must reach.
_SILVER_SUBJECT_TABLES = (
    "silver_semantic_observations",
    "silver_sentiment_observations",
    "silver_semantic_entity_mentions",
    "silver_semantic_subject_links",
    "silver_semantic_claims",
)
_GOLD_SUBJECT_TABLES = (
    "gold_entity_semantic_state",
    "gold_entity_sentiment_state",
)


class SemanticPrivacyHandler:
    def __init__(self) -> None:
        self._review_queue = SemanticReviewQueueRepository()

    async def handle_erasure(self, tenant_id: str, subject_ref: str) -> dict[str, Any]:
        """Hard-delete a subject's semantic data; return a verification result."""
        deleted: dict[str, int] = {}
        errors: list[str] = []
        for table in _SILVER_SUBJECT_TABLES + _GOLD_SUBJECT_TABLES:
            repo = SemanticFactRepository(table)
            try:
                count = await repo.delete_by_subject(tenant_id, subject_ref)
                # A DSR subject is also an actor: erase observations they authored.
                count += await repo.delete_by_actor(tenant_id, subject_ref)
                deleted[table] = count
            except Exception as exc:  # pragma: no cover — defensive
                errors.append(f"{table}:{exc}")
                logger.exception("semantic erasure failed for %s", table)
        try:
            deleted["semantic_review_queue"] = await self._review_queue.purge_by_subject(
                tenant_id, subject_ref
            )
        except Exception as exc:  # pragma: no cover — defensive
            errors.append(f"semantic_review_queue:{exc}")

        return {
            "tenant_id": tenant_id,
            "subject_ref": subject_ref,
            "deleted": deleted,
            "deleted_total": sum(deleted.values()),
            "errors": errors,
            "completed": not errors,
        }

    async def handle_restriction(self, tenant_id: str, subject_ref: str) -> dict[str, Any]:
        """Consent revocation short of erasure → mark rows CONSENT_RESTRICTED."""
        restricted: dict[str, int] = {}
        errors: list[str] = []
        for table in _SILVER_SUBJECT_TABLES:
            repo = SemanticFactRepository(table)
            try:
                count = await repo.tombstone_by_subject(tenant_id, subject_ref)
                count += await repo.tombstone_by_actor(tenant_id, subject_ref)
                restricted[table] = count
            except Exception as exc:  # pragma: no cover — defensive
                errors.append(f"{table}:{exc}")
        return {
            "tenant_id": tenant_id,
            "subject_ref": subject_ref,
            "restricted": restricted,
            "restricted_total": sum(restricted.values()),
            "status": ObservationStatus.CONSENT_RESTRICTED.value,
            "errors": errors,
            "completed": not errors,
        }
