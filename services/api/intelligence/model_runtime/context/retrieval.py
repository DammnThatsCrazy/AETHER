"""ADR-008 D6 retrieval seam — Aether-side, tenant-scoped, secret-free.

Aether executes all retrieval; a model never receives direct DB authority.
This module is the retrieval SEAM: a Protocol (``RetrievalSource``) that
Aether-side services implement, plus a server-authoritative wrapper
(``ScopedRetriever``) that enforces tenant scope on every result.

This module never executes queries itself — it only shapes and validates the
result set a caller hands back. No raw SQL/Gremlin/Cypher/GraphQL/tool
execution appears anywhere here, and it never logs or stores credentials.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

__all__ = [
    "NoopRetriever",
    "RetrievedRecord",
    "RetrievalBounds",
    "RetrievalScopeViolation",
    "RetrievalSource",
    "ScopedRetriever",
]


class RetrievalScopeViolation(Exception):
    """A retrieved record escaped its tenant scope; the seam fails closed."""


class RetrievalBounds(Exception):
    """The requested retrieval limit is outside the supported 1..64 window."""


@dataclass(frozen=True)
class RetrievedRecord:
    """One retrieval result handed back to the caller for shaping/validation.

    ``metadata`` carries plain-string, bounded tags only — never credentials.
    """

    reference_id: str
    source: str
    tenant_id: str
    content: str
    collected_at: datetime
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class RetrievalSource(Protocol):
    """Protocol for Aether-side retrieval sources.

    Implementations run scoped retrieval against Aether stores and return
    only ``tenant_id``-scoped records. Never credentials, never raw query
    text.
    """

    async def retrieve(
        self, *, tenant_id: str, query: str, limit: int = 16
    ) -> list[RetrievedRecord]: ...


class ScopedRetriever:
    """Server-authoritative wrapper enforcing tenant scope on every result.

    Delegates to the supplied ``RetrievalSource`` and then enforces the
    retrieval contract fail-closed: any record whose ``tenant_id`` does not
    match the requested tenant aborts the whole call with
    ``RetrievalScopeViolation``, and an out-of-range ``limit`` (must be in
    1..64) is rejected up front with ``RetrievalBounds`` before any store is
    touched.
    """

    _MIN_LIMIT = 1
    _MAX_LIMIT = 64

    def __init__(self, source: RetrievalSource) -> None:
        self._source = source

    async def retrieve(
        self, *, tenant_id: str, query: str, limit: int = 16
    ) -> list[RetrievedRecord]:
        if limit < self._MIN_LIMIT or limit > self._MAX_LIMIT:
            raise RetrievalBounds(
                f"retrieval limit {limit} out of supported range "
                f"{self._MIN_LIMIT}..{self._MAX_LIMIT}"
            )

        records = await self._source.retrieve(tenant_id=tenant_id, query=query, limit=limit)

        for record in records:
            if record.tenant_id != tenant_id:
                raise RetrievalScopeViolation(
                    f"record {record.reference_id!r} from source {record.source!r} "
                    f"escaped tenant scope {tenant_id!r}"
                )
        return records


class NoopRetriever:
    """In-memory test double; never touches Aether stores.

    Returns seeded records filtered to the requested ``tenant_id`` and sliced
    to ``limit``. Serves as the canonical conforming ``RetrievalSource`` for
    tests.
    """

    def __init__(self, records: Sequence[RetrievedRecord] | None = None) -> None:
        self._records = list(records) if records is not None else []

    def seed(self, record: RetrievedRecord) -> None:
        """Add a single record to the in-memory result set."""
        self._records.append(record)

    async def retrieve(
        self, *, tenant_id: str, query: str, limit: int = 16
    ) -> list[RetrievedRecord]:
        return [record for record in self._records if record.tenant_id == tenant_id][:limit]
