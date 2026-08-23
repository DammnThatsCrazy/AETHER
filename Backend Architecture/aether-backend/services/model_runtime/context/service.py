"""ContextService — public facade for the grounded-synthesis context layer.

ADR-008 D6 retrieval-before-synthesis: Aether executes all retrieval; the model
synthesizes ONLY from assembled, tenant-scoped evidence. ``ContextService`` is
the one-call entry point the grounded-synthesis layer (later commits) consumes.
It wires the retrieval seam (:class:`ScopedRetriever`) -> the context builder
(:class:`ContextBuilder`) -> the assembler (:class:`ContextAssembler`) -> the
prompt builder (:class:`GroundedPromptBuilder`) into two methods:

* ``build_context`` — async; retrieve records for the tenant and assemble a
  :class:`~services.model_runtime.context.evidence.ContextBundle`.
* ``render_prompt`` — sync; render a bundle into the bounded, injection-guarded
  synthesis prompt with ``[ref:...]`` citations.

The facade never runs retrieval itself beyond the injected retriever, and it
never touches credentials. Every context-layer exception (``EvidenceUnsafe``,
``ContextScopeViolation``, ``RetrievalScopeViolation``, ``RetrievalBounds``,
``EvidenceBounds``, ``PromptSizeError``, ``InjectionGuardError``) propagates
unchanged so the pipeline fails closed.
"""

from __future__ import annotations

from services.model_runtime.context.assembly import ContextAssembler
from services.model_runtime.context.builder import ContextBuilder
from services.model_runtime.context.evidence import ContextBundle
from services.model_runtime.context.prompt import GroundedPromptBuilder
from services.model_runtime.context.retrieval import (
    NoopRetriever,
    ScopedRetriever,
)

__all__ = ["ContextService"]


class ContextService:
    """Facade wiring retrieval-before-synthesis for grounded answers.

    All components are injectable for testing; defaults compose the
    server-authoritative tenant-scoped retrieval wrapper around an in-memory
    no-op source, a default context builder, and a default prompt builder.
    """

    def __init__(
        self,
        *,
        retriever: ScopedRetriever | None = None,
        builder: ContextBuilder | None = None,
        prompt_builder: GroundedPromptBuilder | None = None,
        assembler: ContextAssembler | None = None,
    ) -> None:
        if retriever is None:
            retriever = ScopedRetriever(NoopRetriever())
        if builder is None:
            builder = ContextBuilder()
        if assembler is None:
            assembler = ContextAssembler(retriever=retriever, builder=builder)
        if prompt_builder is None:
            prompt_builder = GroundedPromptBuilder()
        self._retriever = retriever
        self._builder = builder
        self._assembler = assembler
        self._prompt_builder = prompt_builder

    async def build_context(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        query: str,
        limit: int = 16,
        instructions: str = "",
    ) -> ContextBundle:
        """Retrieve tenant-scoped evidence and assemble a synthesis context.

        Retrieval-before-synthesis: the injected retriever (wrapped for tenant
        scope when defaulted) returns records, the builder assembles a
        :class:`ContextBundle`, and the caller-supplied ``instructions`` are
        carried through for the prompt layer. Context-layer exceptions
        propagate (fail-closed).
        """
        return await self._assembler.assemble(
            tenant_id=tenant_id,
            profile_id=profile_id,
            query=query,
            limit=limit,
            instructions=instructions,
        )

    def render_prompt(self, bundle: ContextBundle) -> str:
        """Render a bundle into the bounded, injection-guarded synthesis prompt.

        Sync render through the prompt builder, which adds ``[ref:...]``
        citations per evidence item and raises ``InjectionGuardError`` /
        ``PromptSizeError`` rather than ever emitting unsafe text.
        """
        return self._prompt_builder.build(bundle)
