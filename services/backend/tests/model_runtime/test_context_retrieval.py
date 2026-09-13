"""ADR-008 D6 retrieval seam tests — tenant-scoped, secret-free contracts."""

from __future__ import annotations

from datetime import datetime, timezone

from services.model_runtime.context.retrieval import (
    NoopRetriever,
    RetrievedRecord,
    RetrievalBounds,
    RetrievalScopeViolation,
    ScopedRetriever,
)

_SECRET_MARKERS = ("sk-", "AKIA", "Bearer ")


def _record(
    tenant_id: str = "tenant-a",
    reference_id: str = "ref-1",
    content: str = "approved transfer TXN-9001",
    metadata: dict[str, str] | None = None,
) -> RetrievedRecord:
    return RetrievedRecord(
        reference_id=reference_id,
        source="ledger",
        tenant_id=tenant_id,
        content=content,
        collected_at=datetime.now(timezone.utc),
        metadata=metadata or {},
    )


class _UnscopedSource:
    """Non-conforming source returning records regardless of tenant scope.

    Simulates a misbehaving retrieval implementation so the tests can prove
    ``ScopedRetriever`` enforces the tenant contract fail-closed.
    """

    def __init__(self, records: list[RetrievedRecord]) -> None:
        self._records = records

    async def retrieve(
        self, *, tenant_id: str, query: str, limit: int = 16
    ) -> list[RetrievedRecord]:
        return self._records


async def _raises(exc_type: type[Exception], call):
    """Assert that ``await call()`` raises ``exc_type``, plain asserts only."""
    try:
        await call()
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


async def test_noop_retriever_filters_by_tenant():
    retriever = NoopRetriever()
    retriever.seed(_record(tenant_id="tenant-a", reference_id="a-1"))
    retriever.seed(_record(tenant_id="tenant-b", reference_id="b-1"))
    retriever.seed(_record(tenant_id="tenant-a", reference_id="a-2"))

    results = await retriever.retrieve(tenant_id="tenant-a", query="txn")

    assert [r.reference_id for r in results] == ["a-1", "a-2"]
    assert all(r.tenant_id == "tenant-a" for r in results)


async def test_noop_retriever_respects_limit():
    retriever = NoopRetriever()
    for index in range(5):
        retriever.seed(_record(reference_id=f"ref-{index}"))

    results = await retriever.retrieve(tenant_id="tenant-a", query="q", limit=3)

    assert len(results) == 3
    assert [r.reference_id for r in results] == ["ref-0", "ref-1", "ref-2"]


async def test_scoped_retriever_passes_scoped_result():
    source = NoopRetriever([_record(reference_id="ref-1"), _record(reference_id="ref-2")])
    scoped = ScopedRetriever(source)

    results = await scoped.retrieve(tenant_id="tenant-a", query="q")

    assert [r.reference_id for r in results] == ["ref-1", "ref-2"]
    assert all(r.tenant_id == "tenant-a" for r in results)


async def test_scoped_retriever_foreign_tenant_raises():
    source = _UnscopedSource([_record(tenant_id="tenant-b", reference_id="foreign-1")])
    scoped = ScopedRetriever(source)

    await _raises(
        RetrievalScopeViolation,
        lambda: scoped.retrieve(tenant_id="tenant-a", query="q"),
    )


async def test_scoped_retriever_limit_out_of_range_raises():
    scoped = ScopedRetriever(NoopRetriever())

    for bad_limit in (0, 65):
        await _raises(
            RetrievalBounds,
            lambda bad=bad_limit: scoped.retrieve(
                tenant_id="tenant-a", query="q", limit=bad
            ),
        )


async def test_retrieved_record_never_contains_secret_markers():
    source = NoopRetriever([_record(content="Approved transfer reference TXN-9001")])

    results = await source.retrieve(tenant_id="tenant-a", query="q")

    assert len(results) == 1
    retrieved = results[0]
    payload = "\n".join(
        [
            retrieved.reference_id,
            retrieved.source,
            retrieved.tenant_id,
            retrieved.content,
            *retrieved.metadata.values(),
        ]
    )
    for marker in _SECRET_MARKERS:
        assert marker not in payload, f"secret marker {marker!r} leaked into a retrieved record"
