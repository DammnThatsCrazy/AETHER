"""Grounded-context assembly: retrieval-before-synthesis orchestration (ADR-008 D6).

The grounded-synthesis pipeline runs retrieval before synthesis: Aether
retrieves a tenant-scoped evidence set and the model synthesizes ONLY from the
resulting context. ``ContextAssembler`` is that orchestration seam — it runs
the retrieval call, maps the returned records into retrieval items, passes them
through the builder, and yields the single ``ContextBundle`` that a downstream
grounded-synthesis call may use. No other input is permitted.

The pipeline is fail-closed by construction: exceptions from the retrieval seam
(``RetrievalScopeViolation`` / ``RetrievalBounds``) and from the builder
(``ContextScopeViolation`` / ``EvidenceBounds`` / ``EvidenceUnsafe``) propagate
unchanged — they are never swallowed into a bundle, so a scope, bounds, or
secret-marker violation aborts before any synthesis context exists.

``assemble_from_records`` is a synchronous convenience for callers and tests
that already hold tenant-scoped records: it seeds a no-op retriever with those
records and runs the same assembly path, so no store is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

from services.model_runtime.context.builder import ContextBuilder, RetrievalItem
from services.model_runtime.context.evidence import ContextBundle
from services.model_runtime.context.retrieval import (
    NoopRetriever,
    RetrievedRecord,
    ScopedRetriever,
)

__all__ = ["ContextAssembler", "assemble_from_records"]


class ContextAssembler:
    """Runs the retrieval seam and yields the only allowed synthesis context."""

    def __init__(
        self, *, retriever: ScopedRetriever, builder: ContextBuilder | None = None
    ) -> None:
        self._retriever = retriever
        self._builder = builder if builder is not None else ContextBuilder()

    async def assemble(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        query: str,
        limit: int = 16,
        instructions: str = "",
    ) -> ContextBundle:
        # 1) Retrieval seam — tenant-scoped records or a retrieval exception.
        records = await self._retriever.retrieve(
            tenant_id=tenant_id, query=query, limit=limit
        )
        # 2) Map records into retrieval items for the builder.
        items = [
            RetrievalItem(
                reference_id=r.reference_id,
                source=r.source,
                tenant_id=r.tenant_id,
                content=r.content,
                collected_at=r.collected_at,
            )
            for r in records
        ]
        # 3) Builder produces the context bundle (or raises fail-closed).
        bundle = self._builder.build(
            tenant_id=tenant_id, profile_id=profile_id, query=query, items=items
        )
        # 4) Attach synthesis instructions as a bounded field — no injection vector.
        #    ``model_copy(update=...)`` does NOT re-run field validators, so
        #    caller-supplied instructions would bypass ContextBundle's
        #    secret-marker rejection. Rebuild through ContextBundle validation
        #    so instructions (including PEM ``-----BEGIN`` material) pass the
        #    same EvidenceUnsafe gate as every other context field before they
        #    can reach the synthesizer.
        bundle = ContextBundle.model_validate(
            {**bundle.model_dump(), "synthesis_instructions": instructions}
        )
        # 5) Return the bundle — the ONLY input a downstream synthesis call may use.
        return bundle


def assemble_from_records(
    assembler: ContextAssembler,
    *,
    tenant_id: str,
    profile_id: str,
    query: str,
    records: Sequence[RetrievedRecord],
    instructions: str = "",
) -> ContextBundle:
    """Run the assembly path from already-held records without touching stores.

    A sync convenience: seeds a store-free :class:`NoopRetriever` with the
    caller's records and runs the same ``ContextAssembler.assemble`` path,
    reusing ``assembler``'s builder. Returns the assembled bundle (await the
    returned coroutine).
    """
    seeded = ContextAssembler(
        retriever=NoopRetriever(records), builder=assembler._builder
    )
    return seeded.assemble(
        tenant_id=tenant_id,
        profile_id=profile_id,
        query=query,
        instructions=instructions,
    )
