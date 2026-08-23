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
    "semantic_shadow_divergences",
)
_GOLD_SUBJECT_TABLES = (
    "gold_entity_semantic_state",
    "gold_entity_sentiment_state",
)

# Directed-pair Gold projections (relationship semantic + sentiment state). A
# subject participates in these as ``data->>'source_ref'`` or
# ``data->>'target_ref'`` — never on the ``subject_ref`` column, which holds the
# synthetic relationship ref — so the subject/actor predicates above cannot reach
# them. They are therefore propagated separately, matching on BOTH endpoints.
# On erasure the rows are hard-deleted (like the entity Gold tables). On consent
# restriction they are also REMOVED rather than tombstoned: the relationship
# reducer cannot persist an insufficient_data row (it only persists when
# ``support_count > 0``, so recompute cannot degrade a stale row), and the graph
# projector reads this table without a status filter, so a tombstone would still
# surface as a governed edge. Removing the recomputable projection is the only
# mechanism that guarantees an erased/restricted subject never surfaces as a
# relationship endpoint; reversibility lives in the tombstoned Silver evidence.
_GOLD_RELATIONSHIP_TABLES = (
    "gold_relationship_semantic_state",
    "gold_relationship_sentiment_state",
)

# Silver evidence tables whose Gold projections must be recomputed after a
# retraction/erasure (state ← semantic observations, sentiment ← sentiment obs).
_STATE_SILVER_TABLE = "silver_semantic_observations"
_SENTIMENT_SILVER_TABLE = "silver_sentiment_observations"


class SemanticPrivacyHandler:
    def __init__(self) -> None:
        self._review_queue = SemanticReviewQueueRepository()

    async def _affected_subjects(
        self, tenant_id: str, ref: str, table: str, sink: list[str]
    ) -> set[str]:
        """Subjects whose Gold aggregate ``ref`` feeds in ``table`` (as subject/actor).

        ``sink`` collects recompute-path failures — a separate list from the DSR
        ``errors`` contract, since an aggregate-refresh miss must NOT be reported
        as a failure to remove the subject's data (see the handlers).
        """
        try:
            return await SemanticFactRepository(table).subjects_touched_by(tenant_id, ref)
        except Exception as exc:  # pragma: no cover — defensive
            sink.append(f"{table}:subjects_touched_by:{exc}")
            return set()

    async def _recompute_gold(
        self,
        tenant_id: str,
        state_subjects: set[str],
        sentiment_subjects: set[str],
        sink: list[str],
    ) -> int:
        """Re-derive Gold state/sentiment for the affected subjects (resilient).

        A function-level import breaks the ``reducers`` ↔ ``privacy`` cycle. One
        failing entity never aborts the DSR flow — it is logged and recorded in
        ``sink`` (surfaced as ``recompute_errors``, never as a data-removal failure).
        """
        from . import reducers

        recomputed = 0
        for subject in state_subjects:
            try:
                await reducers.recompute_entity_state(tenant_id, subject)
                recomputed += 1
            except Exception as exc:  # pragma: no cover — defensive
                sink.append(f"recompute_state:{subject}:{exc}")
                logger.exception("semantic gold state recompute failed for %s", subject)
        for subject in sentiment_subjects:
            try:
                await reducers.recompute_entity_sentiment(tenant_id, subject)
                recomputed += 1
            except Exception as exc:  # pragma: no cover — defensive
                sink.append(f"recompute_sentiment:{subject}:{exc}")
                logger.exception("semantic gold sentiment recompute failed for %s", subject)
        return recomputed

    async def handle_erasure(self, tenant_id: str, subject_ref: str) -> dict[str, Any]:
        """Hard-delete a subject's semantic data; return a verification result."""
        deleted: dict[str, int] = {}
        errors: list[str] = []
        recompute_errors: list[str] = []
        # Capture affected aggregates BEFORE deletion, while the actor→subject
        # links still exist. Exclude subject_ref itself: its own Gold rows are
        # deleted below and must stay deleted (recomputing would re-create an
        # empty state row).
        state_subjects = await self._affected_subjects(
            tenant_id, subject_ref, _STATE_SILVER_TABLE, recompute_errors
        ) - {subject_ref}
        sentiment_subjects = await self._affected_subjects(
            tenant_id, subject_ref, _SENTIMENT_SILVER_TABLE, recompute_errors
        ) - {subject_ref}
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
        # Directed-pair Gold: erase every relationship the subject is an endpoint
        # of (source OR target), so no overlay edge involving it can survive the
        # DSR completing (the relationship reducer persists only observed pairs,
        # and a deleted row is never re-created once the Silver evidence is gone).
        for table in _GOLD_RELATIONSHIP_TABLES:
            repo = SemanticFactRepository(table)
            try:
                deleted[table] = await repo.delete_by_endpoint(tenant_id, subject_ref)
            except Exception as exc:  # pragma: no cover — defensive
                errors.append(f"{table}:{exc}")
                logger.exception("semantic relationship erasure failed for %s", table)
        try:
            deleted["semantic_review_queue"] = await self._review_queue.purge_by_subject(
                tenant_id, subject_ref
            )
        except Exception as exc:  # pragma: no cover — defensive
            errors.append(f"semantic_review_queue:{exc}")

        # Rebuild OTHER subjects' Gold so this actor's now-deleted contributions
        # no longer linger in their aggregates. Recompute failures are surfaced
        # separately (recompute_errors) and never flip `completed` — the subject's
        # data was still fully deleted, and the DSR job must not retry the whole
        # erasure over a stale aggregate on an unrelated subject.
        recomputed = await self._recompute_gold(
            tenant_id, state_subjects, sentiment_subjects, recompute_errors
        )

        return {
            "tenant_id": tenant_id,
            "subject_ref": subject_ref,
            "deleted": deleted,
            "deleted_total": sum(deleted.values()),
            "recomputed": recomputed,
            "recompute_errors": recompute_errors,
            "errors": errors,
            "completed": not errors,
        }

    async def handle_restriction(self, tenant_id: str, subject_ref: str) -> dict[str, Any]:
        """Consent revocation short of erasure → mark rows CONSENT_RESTRICTED."""
        restricted: dict[str, int] = {}
        errors: list[str] = []
        recompute_errors: list[str] = []
        # Capture affected aggregates BEFORE tombstoning (tombstoning keeps the
        # rows, so the links survive either way, but mirror the erasure ordering).
        state_subjects = await self._affected_subjects(
            tenant_id, subject_ref, _STATE_SILVER_TABLE, recompute_errors
        )
        sentiment_subjects = await self._affected_subjects(
            tenant_id, subject_ref, _SENTIMENT_SILVER_TABLE, recompute_errors
        )
        for table in _SILVER_SUBJECT_TABLES:
            repo = SemanticFactRepository(table)
            try:
                count = await repo.tombstone_by_subject(tenant_id, subject_ref)
                count += await repo.tombstone_by_actor(tenant_id, subject_ref)
                restricted[table] = count
            except Exception as exc:  # pragma: no cover — defensive
                errors.append(f"{table}:{exc}")
        # Directed-pair Gold: remove every relationship the subject is an endpoint
        # of (source OR target). See _GOLD_RELATIONSHIP_TABLES for why restriction
        # removes (not tombstones) these recomputable projections — a tombstoned
        # row would still be read and projected as a governed edge, and the
        # relationship reducer cannot degrade a stale row to insufficient_data.
        for table in _GOLD_RELATIONSHIP_TABLES:
            repo = SemanticFactRepository(table)
            try:
                restricted[table] = await repo.delete_by_endpoint(tenant_id, subject_ref)
            except Exception as exc:  # pragma: no cover — defensive
                errors.append(f"{table}:{exc}")
        # Recompute every affected aggregate, INCLUDING subject_ref itself: its
        # rows are now consent_restricted, so its state (and sentiment) reduce to
        # insufficient_data (correct), and other subjects lose its contribution.
        # Recompute failures are surfaced separately and never flip `completed`.
        recomputed = await self._recompute_gold(
            tenant_id, state_subjects, sentiment_subjects, recompute_errors
        )
        return {
            "tenant_id": tenant_id,
            "subject_ref": subject_ref,
            "restricted": restricted,
            "restricted_total": sum(restricted.values()),
            "recomputed": recomputed,
            "recompute_errors": recompute_errors,
            "status": ObservationStatus.CONSENT_RESTRICTED.value,
            "errors": errors,
            "completed": not errors,
        }
