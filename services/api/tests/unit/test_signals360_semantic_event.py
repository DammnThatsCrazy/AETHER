"""Exact-event semantic Silver metadata stays bounded and evidence-scoped."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "signals360-semantic-test-secret")

from intelligence.signals.signals360_provider import (  # noqa: E402
    ObservationQualityRead,
    RepositorySignal360Source,
    SemanticEventRead,
    Signals360Provider,
)
from intelligence.semantic_intelligence.repositories.base_fact_repo import (  # noqa: E402
    SemanticFactRepository,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)

TENANT = "tenant-signals-semantic"
EVENT_ID = "event-semantic-exact"


def _bronze_record() -> dict[str, Any]:
    return {
        "tenant_id": TENANT,
        "provider_record_id": EVENT_ID,
        "source": "sdk",
        "payload": {
            "event_type": "track",
            "context": {"identity_namespace": "site:trusted-site"},
            "observation_envelope": {
                "tenancy": {"tenant_id": TENANT},
                "observation": {
                    "observation_id": EVENT_ID,
                    "observation_type": "track",
                    "family": "core",
                    "occurred_at": "2026-10-20T10:00:00Z",
                    "ingested_at": "2026-10-20T10:01:00Z",
                },
                "source": {"source_instance": "site:trusted-site"},
                "quality": {"validation_state": "gateway:accepted"},
            },
        },
    }


def _semantic_row() -> dict[str, Any]:
    return {
        "observation_id": "sem-exact-1",
        "tenant_id": TENANT,
        "source_event_id": EVENT_ID,
        "source_namespace": "site:trusted-site",
        "source_type": "track",
        "occurred_at": "2026-10-20T10:00:00Z",
        "processed_at": "2026-10-20T10:02:00Z",
        "status": "classified",
        "model_id": "deterministic-semantic-classifier",
        "model_version": "1.0.0",
        "actor_ref": "private-actor",
        "topics": ["private-topic"],
        "evidence_refs": [{"source_ref": EVENT_ID, "source_type": "track"}],
    }


class _Source:
    def __init__(self, read: SemanticEventRead, record: dict[str, Any] | None = None) -> None:
        self.read = read
        self.record = record or _bronze_record()
        self.semantic_calls: list[tuple[str, str, int]] = []

    async def observation_quality(self, *, tenant_id: str, observation_id: str) -> ObservationQualityRead:
        assert (tenant_id, observation_id) == (TENANT, EVENT_ID)
        return ObservationQualityRead(self.record, True, True)

    async def semantic_observations_for_event(
        self, *, tenant_id: str, event_id: str, limit: int
    ) -> SemanticEventRead:
        self.semantic_calls.append((tenant_id, event_id, limit))
        return self.read


def _request(*, as_of: str | None = None) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="signals360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="event", id=EVENT_ID),
        includeSections=["classification"],
        includeClaims=True,
        asOf=as_of,
    )


def _context() -> ProjectionContext:
    return ProjectionContext(
        projectionId="signals360",
        tenantId=TENANT,
        registryState="implemented",
        dependencyState=[],
        warnings=[],
    )


def _classification(result: Any) -> Any:
    return next(section for section in result.sections if section.id == "classification")


@pytest.mark.asyncio
async def test_exact_semantic_row_exposes_only_model_metadata_and_evidence() -> None:
    source = _Source(SemanticEventRead(TENANT, EVENT_ID, (_semantic_row(),), True, True))

    result = await Signals360Provider(source=source).project(_request(), _context())

    section = _classification(result)
    assert source.semantic_calls == [(TENANT, EVENT_ID, 100)]
    assert section.content["semanticSignalState"] == "stored_model_output_observed"
    assert section.content["semanticObservations"] == [{
        "observationId": "sem-exact-1",
        "status": "classified",
        "modelId": "deterministic-semantic-classifier",
        "modelVersion": "1.0.0",
    }]
    assert section.content["semanticCorrectnessState"] == "unknown"
    assert section.content["semanticProducerCoverageState"] == "unknown"
    assert section.canonicalAuthorityRefs == [
        "events", "observations", "silver_semantic_observations"
    ]
    assert {ref["id"] for ref in section.content["evidenceRefs"]} == {
        EVENT_ID, "track", "sem-exact-1"
    }
    assert "private-actor" not in str(section.content)
    assert "private-topic" not in str(section.content)
    assert all(ref.id != "sem-exact-1" for claim in result.claims for ref in claim.evidenceRefs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"tenant_id": "foreign"}, "semantic_event_row_scope_mismatch"),
        ({"source_namespace": "site:other"}, "semantic_event_row_scope_mismatch"),
        ({"source_type": "page_view"}, "semantic_event_row_scope_mismatch"),
        ({"occurred_at": "2026-10-20T10:03:00Z"}, "semantic_event_row_evidence_mismatch"),
        ({"evidence_refs": []}, "semantic_event_row_evidence_mismatch"),
        ({"status": "deleted"}, "no_active_semantic_event_model_output"),
    ],
)
async def test_semantic_row_conflicts_remain_unknown(
    override: dict[str, Any], reason: str
) -> None:
    row = _semantic_row()
    row.update(override)
    source = _Source(SemanticEventRead(TENANT, EVENT_ID, (row,), True, True))

    result = await Signals360Provider(source=source).project(_request(), _context())

    section = _classification(result)
    assert section.content["semanticSignalState"] == "unknown"
    assert section.content["semanticSignalReason"] == reason
    assert section.canonicalAuthorityRefs == ["events", "observations"]
    assert "sem-exact-1" not in str(section.content)


@pytest.mark.asyncio
async def test_current_semantic_rows_are_not_read_for_as_of_request() -> None:
    source = _Source(SemanticEventRead(TENANT, EVENT_ID, (_semantic_row(),), True, True))

    result = await Signals360Provider(source=source).project(
        _request(as_of="2026-10-20T10:00:00Z"), _context()
    )

    assert source.semantic_calls == []
    assert _classification(result).content["semanticSignalReason"] == (
        "semantic_event_temporal_read_not_supported"
    )


class _FactReader:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str, int]] = []

    async def find_by_source_event(
        self, tenant_id: str, event_id: str, *, limit: int
    ) -> list[dict[str, Any]]:
        self.calls.append((tenant_id, event_id, limit))
        return self.rows[:limit]


@pytest.mark.asyncio
async def test_semantic_source_caps_reads_and_rejects_truncation() -> None:
    reader = _FactReader([_semantic_row() for _ in range(101)])

    read = await RepositorySignal360Source(
        semantic_observations=reader
    ).semantic_observations_for_event(tenant_id=TENANT, event_id=EVENT_ID, limit=100)

    assert reader.calls == [(TENANT, EVENT_ID, 101)]
    assert read.available is True
    assert read.complete is False
    assert read.rows == ()
    assert read.reason == "semantic_event_read_truncated"


@pytest.mark.asyncio
async def test_semantic_fact_exact_event_read_enforces_tenant_and_limit_in_memory() -> None:
    repo = SemanticFactRepository("silver_semantic_observations")
    repo._store = {
        "sem-b": {
            "tenant_id": TENANT,
            "source_event_id": EVENT_ID,
            "data": {"observation_id": "sem-b"},
        },
        "sem-a": {
            "tenant_id": TENANT,
            "source_event_id": EVENT_ID,
            "data": {"observation_id": "sem-a"},
        },
        "sem-foreign": {
            "tenant_id": "foreign",
            "source_event_id": EVENT_ID,
            "data": {"observation_id": "sem-foreign"},
        },
    }

    async def no_pool() -> None:
        return None

    repo._pool = no_pool
    assert await repo.find_by_source_event(TENANT, EVENT_ID, limit=1) == [
        {"observation_id": "sem-a"}
    ]
    assert await repo.find_by_source_event("foreign", EVENT_ID, limit=2) == [
        {"observation_id": "sem-foreign"}
    ]
    with pytest.raises(ValueError, match="limit must be positive"):
        await repo.find_by_source_event(TENANT, EVENT_ID, limit=0)
