"""Durable repositories for the semantic-sentiment Silver/Gold fact tables.

These repositories replace the process-local in-memory store as the production
backend for semantic observations, sentiment, entity/relationship/campaign state,
narratives, episodes and cascades. They write the typed columns the migration
``20260702_semantic_sentiment`` defines plus the full model payload into ``data``
(JSONB), keyed idempotently on ``data->>'idempotency_key'``.

Local/test execution (``get_pool() is None``) transparently falls back to the
shared ``_IN_MEMORY_STORES`` registry so behaviour matches the rest of the
backend's dual-mode repositories (see ``repositories.repos``).
"""

from __future__ import annotations

from .base_fact_repo import SemanticFactRepository
from .review_queue_repo import SemanticReviewQueueRepository

__all__ = ["SemanticFactRepository", "SemanticReviewQueueRepository"]
