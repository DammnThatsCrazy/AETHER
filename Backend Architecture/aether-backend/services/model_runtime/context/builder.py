"""Grounded-synthesis context builder (ADR-008 D6).

The context builder assembles a tenant-scoped, freshness-bounded
:class:`~services.model_runtime.context.evidence.ContextBundle` from retrieval
results **before** any model synthesis. It is the deterministic front door of
the grounded-synthesis pipeline: everything the model may later claim must flow
through this assembly.

Guarantees enforced here, in fixed order (fail-closed):

1. **Tenant scope** — every retrieval item must belong to the requested
   ``tenant_id``. The requested tenant is server-authoritative; a single
   foreign-tenant item raises :class:`ContextScopeViolation` immediately.
2. **Freshness bound** — items older than ``budget.freshness_seconds`` are
   dropped (silently; no exception). Future-dated items are kept.
3. **Deduplication** — by ``reference_id``, first occurrence wins, preserving
   original order.
4. **Item/content bounds** — ``budget.max_items`` and
   ``budget.max_content_chars`` are enforced when materializing the evidence
   set; overflow raises ``EvidenceBounds``.

Boundaries (deliberate):

* The builder **never runs retrieval** — it consumes ``items``.
* It **never executes SQL / Gremlin / Cypher / GraphQL** and holds no query
  language — injection shielding belongs to the planner/validator layers.
* It **never touches credentials** — no secret material is read, written, or
  forwarded here. Secret-shaped text is rejected downstream by the
  ``EvidenceItem`` / ``ContextBundle`` field validators (``EvidenceUnsafe``).

The builder is synchronous and single-assembly-per-request: ``build`` stores the
requested scope/query so the private helpers can construct the self-describing
``EvidenceSet`` (which redundantly carries tenant/profile/query). A fresh
``ContextBuilder`` is created per assembly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from services.model_runtime.context.evidence import (
    ContextBundle,
    EvidenceBounds,
    EvidenceBudget,
    EvidenceItem,
    EvidenceSet,
    EvidenceUnsafe,
)

__all__ = [
    "ContextBuilder",
    "ContextScopeViolation",
    "RetrievalItem",
]


class ContextScopeViolation(Exception):
    """Raised when any retrieval item belongs to a tenant other than the request.

    The requested ``tenant_id`` is server-authoritative: a single foreign item
    fails the whole assembly (fail-closed) rather than being silently dropped,
    so out-of-tenant data can never reach a model.
    """


@dataclass(frozen=True)
class RetrievalItem:
    """A plain, pre-validation retrieval result fed into the builder.

    This is the raw input shape (owned by the builder); the builder validates
    and converts items into the frozen, secret-checked
    :class:`~services.model_runtime.context.evidence.EvidenceItem`.
    """

    reference_id: str
    source: str
    tenant_id: str
    content: str
    collected_at: datetime


@dataclass(frozen=True)
class _AssemblyContext:
    """Scope/query of the in-flight assembly, embedded into the evidence set."""

    tenant_id: str
    profile_id: str
    query: str
    created_at: datetime


class ContextBuilder:
    """Assembles a bounded, tenant-scoped :class:`ContextBundle` from retrieval items."""

    def __init__(self, *, budget: EvidenceBudget | None = None) -> None:
        self._budget = budget if budget is not None else EvidenceBudget()
        self._ctx: _AssemblyContext | None = None

    def build(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        query: str,
        items: Sequence[RetrievalItem],
        now: datetime | None = None,
    ) -> ContextBundle:
        """Assemble a context bundle, enforcing scope → freshness → dedupe → bounds.

        Scope rejection happens first (fail-closed), then staleness is filtered,
        then items are deduplicated by ``reference_id`` (first occurrence wins),
        then item/content bounds are enforced while materializing the
        :class:`~services.model_runtime.context.evidence.EvidenceSet`.
        """
        resolved_now = now if now is not None else datetime.now(timezone.utc)
        self._ctx = _AssemblyContext(
            tenant_id=tenant_id,
            profile_id=profile_id,
            query=query,
            created_at=resolved_now,
        )
        self._reject_foreign_tenant(items, tenant_id)
        kept = self._freshness_filter(items, self._budget, resolved_now)
        kept = self._dedupe(kept)
        evidence = self._to_evidence_set(kept, self._budget)
        return ContextBundle(
            tenant_id=tenant_id,
            profile_id=profile_id,
            query=query,
            evidence=evidence,
            created_at=resolved_now,
        )

    def _reject_foreign_tenant(
        self, items: Sequence[RetrievalItem], tenant_id: str
    ) -> None:
        """Raise :class:`ContextScopeViolation` on the first out-of-scope item."""
        for item in items:
            if item.tenant_id != tenant_id:
                raise ContextScopeViolation(
                    f"retrieval item {item.reference_id!r} belongs to tenant "
                    f"{item.tenant_id!r}, not requested tenant {tenant_id!r}"
                )

    def _freshness_filter(
        self,
        items: Sequence[RetrievalItem],
        budget: EvidenceBudget,
        now: datetime,
    ) -> list[RetrievalItem]:
        """Drop items older than ``budget.freshness_seconds``; keep future-dated."""
        kept: list[RetrievalItem] = []
        for item in items:
            age = (now - item.collected_at).total_seconds()
            if age <= budget.freshness_seconds:
                kept.append(item)
        return kept

    def _dedupe(self, items: Sequence[RetrievalItem]) -> list[RetrievalItem]:
        """Keep the first occurrence of each ``reference_id``, preserving order."""
        seen: set[str] = set()
        unique: list[RetrievalItem] = []
        for item in items:
            if item.reference_id in seen:
                continue
            seen.add(item.reference_id)
            unique.append(item)
        return unique

    def _to_evidence_set(
        self, items: Sequence[RetrievalItem], budget: EvidenceBudget
    ) -> EvidenceSet:
        """Materialize the evidence set, raising ``EvidenceBounds`` on overflow."""
        if len(items) > budget.max_items:
            raise EvidenceBounds(
                f"evidence exceeds budget max_items={budget.max_items}: "
                f"{len(items)} items"
            )
        for item in items:
            if len(item.content) > budget.max_content_chars:
                raise EvidenceBounds(
                    f"evidence content exceeds budget "
                    f"max_content_chars={budget.max_content_chars} "
                    f"(reference_id={item.reference_id!r})"
                )
        assert self._ctx is not None  # set by build() before assembly helpers run
        evidence_items = tuple(
            EvidenceItem(
                reference_id=item.reference_id,
                source=item.source,
                tenant_id=item.tenant_id,
                content=item.content,
                collected_at=item.collected_at,
            )
            for item in items
        )
        return EvidenceSet(
            tenant_id=self._ctx.tenant_id,
            profile_id=self._ctx.profile_id,
            query=self._ctx.query,
            items=evidence_items,
            created_at=self._ctx.created_at,
        )
