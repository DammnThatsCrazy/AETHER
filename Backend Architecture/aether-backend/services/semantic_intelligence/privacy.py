"""Semantic data-subject-rights handler — erasure and consent restriction.

Propagates a deletion or consent revocation across the semantic surfaces so a
revoked subject's semantic observations, sentiment, aggregate state and review
items do not persist. Produces a verifiable result (per-table counts + errors)
that binds into the DSR propagation record. Imitates
``services/measurement/privacy.py``.

Graph projections: the durable Gold relationship rows are the *source of truth*
the semantic graph projector turns into governed ``SEMANTIC_RELATES_TO`` edges.
A DSR that only removed the Gold rows would leave those projected edges LIVE in
the graph until the projector's next reconciliation sweep (a default six-hour
interval) — so both handlers revoke the subject's projections through the
canonical mutation gateway (the same path the projector uses) before they can
report ``completed=True``. A revocation failure is a DSR error (fail-closed).
"""

from __future__ import annotations

from typing import Any, Optional

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
    def __init__(
        self,
        *,
        graph_client: Optional[Any] = None,
        gateway: Optional[Any] = None,
    ) -> None:
        self._review_queue = SemanticReviewQueueRepository()
        # Injectable graph client + mutation gateway so tests can bind the DSR
        # to a private in-memory graph. Production passes neither: the graph
        # revocation path falls back to the process-wide client/gateway — the
        # same graph the semantic graph projector writes through.
        self._graph_client = graph_client
        self._gateway = gateway

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

    async def _revoke_subject_projections(
        self, tenant_id: str, subject_ref: str, errors: list[str]
    ) -> int:
        """Revoke every live ``SEMANTIC_RELATES_TO`` projection touching the subject.

        Deleting the durable Gold relationship rows is NOT enough: a previously
        projected graph edge (written by the semantic graph projector through the
        canonical mutation gateway) stays LIVE in the graph until the projector's
        next reconciliation sweep — a default six-hour interval. Direct graph
        consumers read the projected edge, not the Gold row, so a DSR that
        reported ``completed=True`` while the subject's relationship was still
        projected would leave an erased/restricted subject exposed as a graph
        relationship endpoint.

        This revokes — through the canonical mutation gateway, the SAME path
        ``graph_projector._revoke_projection`` uses (never a direct graph write)
        — every live projection for which ``subject_ref`` is an endpoint (source
        OR target). Fail-closed: a listing failure or any revocation failure is
        appended to ``errors`` and therefore flips the DSR ``completed`` to
        False, so a DSR never reports complete while a governed edge can still
        surface the subject.

        Returns the number of projections revoked.
        """
        from .graph_projector import _list_projected_edges_for_tenant, _revoke_projection
        from shared.graph.graph import get_graph_client
        from shared.graph.mutation_gateway import GraphMutationGateway

        graph_client = self._graph_client or get_graph_client()
        gateway = self._gateway or GraphMutationGateway(graph_client=graph_client)
        try:
            edges = await _list_projected_edges_for_tenant(graph_client, tenant_id)
        except Exception as exc:  # noqa: BLE001 — DSR must fail closed on graph errors
            errors.append(f"graph_list:{exc}")
            logger.exception("semantic graph projection list failed for %s", subject_ref)
            return 0
        # One gateway revocation per (source, target) pair; duplicate replica
        # projections of the same pair collapse to a single (idempotent) revoke.
        pairs: set[tuple[str, str]] = {
            (edge.from_vertex_id, edge.to_vertex_id)
            for edge in edges
            if subject_ref in (edge.from_vertex_id, edge.to_vertex_id)
        }
        revoked = 0
        for source, target in sorted(pairs):
            try:
                await _revoke_projection(gateway, tenant_id, source, target)
                revoked += 1
            except Exception as exc:  # noqa: BLE001 — one failed revoke fails the DSR
                errors.append(f"graph_revoke:{source}->{target}:{exc}")
                logger.exception(
                    "semantic graph revocation failed for %s (%s->%s)",
                    subject_ref,
                    source,
                    target,
                )
        return revoked

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

        # The Gold relationship rows are gone, but a previously projected graph
        # edge (written by the semantic graph projector) remains LIVE until the
        # projector's next reconciliation sweep — a default six-hour interval.
        # Revoke the subject's projections through the canonical mutation
        # gateway BEFORE reporting the DSR complete; a revocation failure is a
        # DSR error (fail-closed), never a silent ``completed=True``.
        graph_revocations = await self._revoke_subject_projections(
            tenant_id, subject_ref, errors
        )

        return {
            "tenant_id": tenant_id,
            "subject_ref": subject_ref,
            "deleted": deleted,
            "deleted_total": sum(deleted.values()),
            "recomputed": recomputed,
            "graph_revocations": graph_revocations,
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
        # Same as erasure: a restricted subject must not remain projected as a
        # graph relationship endpoint. Revoke its live projections through the
        # mutation gateway before `completed` can be reported (fail-closed).
        graph_revocations = await self._revoke_subject_projections(
            tenant_id, subject_ref, errors
        )
        return {
            "tenant_id": tenant_id,
            "subject_ref": subject_ref,
            "restricted": restricted,
            "restricted_total": sum(restricted.values()),
            "recomputed": recomputed,
            "graph_revocations": graph_revocations,
            "recompute_errors": recompute_errors,
            "status": ObservationStatus.CONSENT_RESTRICTED.value,
            "errors": errors,
            "completed": not errors,
        }
