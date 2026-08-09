"""ContextAssembler orchestration tests (ADR-008 D6).

Retrieval-before-synthesis: the assembler runs the retrieval seam, maps records
into retrieval items, and yields the single :class:`ContextBundle` a downstream
grounded-synthesis call may use. The suite is fail-closed by construction:
retrieval-scope, retrieval-bounds, evidence-bounds, context-scope, and
secret-marker violations all abort before any bundle is produced, and the
exceptions propagate unchanged.

Plain asserts plus the ``_raises`` helper only (async-aware via pytest-asyncio
auto mode) — no fixture or mock libraries, so this suite runs under the minimal
test runtime used by some CI environments.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

from services.model_runtime.context.assembly import (
    ContextAssembler,
    assemble_from_records,
)
from services.model_runtime.context.builder import (
    ContextBuilder,
    ContextScopeViolation,
)
from services.model_runtime.context.evidence import (
    ContextBundle,
    EvidenceBounds,
    EvidenceUnsafe,
)
from services.model_runtime.context.retrieval import (
    NoopRetriever,
    RetrievedRecord,
    RetrievalBounds,
    RetrievalScopeViolation,
    ScopedRetriever,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record(
    *,
    tenant_id: str = "t1",
    reference_id: str = "r1",
    content: str = "plain evidence",
    source: str = "aether.records.ledger.tx-1",
    collected_at: datetime | None = None,
) -> RetrievedRecord:
    return RetrievedRecord(
        reference_id=reference_id,
        source=source,
        tenant_id=tenant_id,
        content=content,
        collected_at=collected_at if collected_at is not None else _now(),
    )


async def _raises(exc_type, func):
    """Assert that calling func() raises exc_type; awaits coroutine results."""
    try:
        result = func()
        if inspect.isawaitable(result):
            await result
    except exc_type:
        return
    except Exception as err:  # noqa: BLE001 - plain-assert suite
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


class _BoomSource:
    """RetrievalSource that fails loudly if its retrieve is ever called."""

    async def retrieve(self, *, tenant_id: str, query: str, limit: int):
        raise AssertionError(
            "assemble_from_records must not call the assembler's own retriever"
        )


class _ManyRecordsSource:
    """RetrievalSource returning more records than the default evidence budget."""

    async def retrieve(self, *, tenant_id: str, query: str, limit: int):
        return [
            _record(tenant_id=tenant_id, reference_id=f"r{i}", content=f"record {i}")
            for i in range(65)
        ]


class _ForeignLeakingSource:
    """RetrievalSource returning a record for a different tenant (seam must reject)."""

    async def retrieve(self, *, tenant_id: str, query: str, limit: int):
        return [_record(tenant_id="t2", reference_id="r-foreign", content="foreign data")]


class _UnscopedSource:
    """Source that returns a foreign-tenant record without a seam-level scope check.

    Deliberately bypasses :class:`ScopedRetriever` so the builder's own
    fail-closed tenant enforcement is exercised.
    """

    async def retrieve(self, *, tenant_id: str, query: str, limit: int):
        return [_record(tenant_id="t2", reference_id="r-foreign", content="foreign data")]


async def test_assemble_returns_bundle_with_all_items_and_instructions():
    assembler = ContextAssembler(retriever=_BoomSource())
    records = [
        _record(reference_id="r1", content="alpha"),
        _record(reference_id="r2", content="beta"),
        _record(reference_id="r3", content="gamma"),
    ]
    bundle = await assemble_from_records(
        assembler,
        tenant_id="t1",
        profile_id="p1",
        query="what is my balance",
        records=records,
        instructions="answer strictly from the evidence",
    )
    assert isinstance(bundle, ContextBundle)
    assert bundle.tenant_id == "t1"
    assert bundle.profile_id == "p1"
    assert bundle.query == "what is my balance"
    assert bundle.synthesis_instructions == "answer strictly from the evidence"
    assert [item.reference_id for item in bundle.evidence.items] == ["r1", "r2", "r3"]
    assert [item.content for item in bundle.evidence.items] == ["alpha", "beta", "gamma"]
    assert [item.source for item in bundle.evidence.items] == [
        "aether.records.ledger.tx-1"
    ] * 3
    assert all(item.tenant_id == "t1" for item in bundle.evidence.items)


async def test_assembler_runs_direct_retrieval_path():
    retriever = NoopRetriever(
        [
            _record(reference_id="r1", content="alpha"),
            _record(reference_id="r2", content="beta"),
        ]
    )
    assembler = ContextAssembler(retriever=retriever)
    bundle = await assembler.assemble(
        tenant_id="t1", profile_id="p1", query="q", instructions="direct"
    )
    assert [item.reference_id for item in bundle.evidence.items] == ["r1", "r2"]
    assert bundle.synthesis_instructions == "direct"


async def test_empty_records_yield_empty_bundle():
    assembler = ContextAssembler(retriever=_BoomSource())
    bundle = await assemble_from_records(
        assembler,
        tenant_id="t1",
        profile_id="p1",
        query="q",
        records=[],
        instructions="keep it short",
    )
    assert bundle.evidence.items == ()
    assert bundle.tenant_id == "t1"
    assert bundle.profile_id == "p1"
    assert bundle.query == "q"
    assert bundle.synthesis_instructions == "keep it short"


async def test_assemble_from_records_returns_bundle_without_touching_stores():
    # The seeded assembler carries a retriever that fails loudly if called;
    # a passing test proves assemble_from_records never touches a store.
    assembler = ContextAssembler(retriever=_BoomSource())
    bundle = await assemble_from_records(
        assembler,
        tenant_id="t1",
        profile_id="p1",
        query="q",
        records=[_record(reference_id="r1"), _record(reference_id="r2")],
        instructions="summarize",
    )
    assert [item.reference_id for item in bundle.evidence.items] == ["r1", "r2"]
    assert bundle.synthesis_instructions == "summarize"


async def test_assembler_accepts_explicit_builder():
    assembler = ContextAssembler(retriever=NoopRetriever(), builder=ContextBuilder())
    bundle = await assembler.assemble(tenant_id="t1", profile_id="p1", query="q")
    assert bundle.tenant_id == "t1"
    assert bundle.evidence.items == ()


async def test_foreign_tenant_record_raises_retrieval_scope_violation():
    # Fail-closed: the seam rejects out-of-tenant data before any bundle exists.
    retriever = ScopedRetriever(_ForeignLeakingSource())
    assembler = ContextAssembler(retriever=retriever)
    await _raises(
        RetrievalScopeViolation,
        lambda: assembler.assemble(tenant_id="t1", profile_id="p1", query="q"),
    )


async def test_retrieval_bounds_propagate_fail_closed():
    # Fail-closed: an out-of-range retrieval limit aborts before any bundle.
    retriever = ScopedRetriever(_BoomSource())
    assembler = ContextAssembler(retriever=retriever)
    await _raises(
        RetrievalBounds,
        lambda: assembler.assemble(tenant_id="t1", profile_id="p1", query="q", limit=200),
    )


async def test_record_set_over_budget_raises_evidence_bounds():
    # Fail-closed: more evidence than the budget allows aborts at the builder.
    retriever = ScopedRetriever(_ManyRecordsSource())
    assembler = ContextAssembler(retriever=retriever)
    await _raises(
        EvidenceBounds,
        lambda: assembler.assemble(tenant_id="t1", profile_id="p1", query="q"),
    )


async def test_secret_marker_in_record_content_surfaces_evidence_unsafe():
    # Credential-shaped text in a retrieved record must never reach a model:
    # it surfaces as EvidenceUnsafe from the builder path, fail-closed.
    assembler = ContextAssembler(retriever=_BoomSource())
    for marker in ("sk-", "AKIA"):
        await _raises(
            EvidenceUnsafe,
            lambda marker=marker: assemble_from_records(
                assembler,
                tenant_id="t1",
                profile_id="p1",
                query="q",
                records=[_record(reference_id="r1", content=f"key {marker} value")],
            ),
        )


async def test_builder_context_scope_violation_propagates_fail_closed():
    # Defense in depth: even if the seam is bypassed, the builder rejects a
    # foreign-tenant item and the exception propagates — never a bundle.
    assembler = ContextAssembler(retriever=_UnscopedSource())
    await _raises(
        ContextScopeViolation,
        lambda: assembler.assemble(tenant_id="t1", profile_id="p1", query="q"),
    )
