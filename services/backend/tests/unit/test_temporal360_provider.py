"""Temporal360 provider tests (phase 2, T2.2/T2.3).

Pins the provider's contract: a valid, typed ``ProjectionResult`` on a fresh
registry; KNOWN_NOW/KNOWN_THEN/COMPARE served honestly; unsupported or
incomplete temporal modes degrade with a typed warning and never raise;
``unknown`` subjects, empty windows and ``not_applicable`` reconstruction stay
distinct states; tenant scope is server-authoritative; no write path.
"""

from __future__ import annotations

from typing import Optional

import pytest

from shared.intelligence_projections.contracts import (
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import (
    ContractVersionIncompatible,
    DuplicateProjection,
    ProjectionNotFound,
)
from shared.intelligence_projections.registry import ProviderRegistry

from services.operational_intelligence.models import TimeRangeFilter
from services.temporal360.history_replay import SubjectEvent, SubjectHistory
from services.temporal360.provider import (
    OUTPUT_SECTIONS,
    Temporal360Provider,
    register_provider,
)

TENANT = "tenant_t360"
SUBJECT_A = "a"

T1 = "2026-01-01T00:00:00+00:00"
T3 = "2026-01-03T00:00:00+00:00"
T4 = "2026-01-04T00:00:00+00:00"
T5 = "2026-01-05T00:00:00+00:00"


# ── Canned subject histories (mirror the deterministic T2.1 ledger scenario) ─


def _vertex_created(rec: str, off: int) -> SubjectEvent:
    return SubjectEvent(
        recorded_at=rec,
        ledger_offset=off,
        kind="vertex_created",
        operation="node_created",
        aggregate_type="node",
        aggregate_id=SUBJECT_A,
        mutation_id=f"m{off}",
        valid_from=rec,
        vertex_id=SUBJECT_A,
        changed={"status": {"before": None, "after": "active"}},
    )


def _edge_added(rec: str, off: int) -> SubjectEvent:
    return SubjectEvent(
        recorded_at=rec,
        ledger_offset=off,
        kind="edge_added",
        operation="edge_created",
        aggregate_type="edge",
        aggregate_id="a:b:SAME_AS",
        mutation_id=f"m{off}",
        valid_from=rec,
        edge_type="SAME_AS",
        from_vertex_id="a",
        to_vertex_id="b",
    )


def _vertex_superseded(rec: str, off: int) -> SubjectEvent:
    return SubjectEvent(
        recorded_at=rec,
        ledger_offset=off,
        kind="vertex_superseded",
        operation="node_updated",
        aggregate_type="node",
        aggregate_id=SUBJECT_A,
        mutation_id=f"m{off}",
        valid_from=rec,
        vertex_id=SUBJECT_A,
        changed={"status": {"before": "active", "after": "archived"}},
    )


def _edge_revoked(rec: str, off: int) -> SubjectEvent:
    return SubjectEvent(
        recorded_at=rec,
        ledger_offset=off,
        kind="edge_revoked",
        operation="edge_expired",
        aggregate_type="edge",
        aggregate_id="a:b:SAME_AS",
        mutation_id=f"m{off}",
        valid_from=None,
        edge_type="SAME_AS",
        from_vertex_id="a",
        to_vertex_id="b",
        reason="corrected",
    )


def _history_now() -> SubjectHistory:
    events = (
        _vertex_created(T1, 1),
        _edge_added(T3, 3),
        _vertex_superseded(T4, 4),
        _edge_revoked(T5, 5),
    )
    return SubjectHistory(
        subject_id=SUBJECT_A,
        as_of=None,
        present=True,
        vertex={"status": "archived"},
        first_recorded=T1,
        last_recorded=T5,
        event_count=len(events),
        events=events,
        live_edges=(),  # the edge was added at T3 then revoked at T5
        vertex_supersessions=1,
        incident_edge_adds=1,
        incident_edge_revocations=1,
        digest="now-digest",
    )


def _history_then(rec: str) -> SubjectHistory:
    """KNOWN_THEN at ``rec``: between T3 and T4 (vertex active, edge live)."""
    events = (_vertex_created(T1, 1), _edge_added(T3, 3))
    return SubjectHistory(
        subject_id=SUBJECT_A,
        as_of=rec,
        present=True,
        vertex={"status": "active"},
        first_recorded=T1,
        last_recorded=T3,
        event_count=len(events),
        events=events,
        live_edges=(("SAME_AS", "a", "b"),),  # the edge is live at τ
        vertex_supersessions=0,
        incident_edge_adds=1,
        incident_edge_revocations=0,
        digest="then-digest",
    )


def _history_unknown() -> SubjectHistory:
    return SubjectHistory(
        subject_id=SUBJECT_A,
        as_of=None,
        present=False,
        vertex=None,
        first_recorded=None,
        last_recorded=None,
        event_count=0,
        events=(),
        live_edges=(),
        vertex_supersessions=0,
        incident_edge_adds=0,
        incident_edge_revocations=0,
        digest="empty-digest",
    )


class _FakeTemporalReader:
    """Strictly tenant-scoped canned reader (raises for unknown tenants)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Optional[str]]] = []
        self._store = {
            (TENANT, SUBJECT_A): (_history_now(), _history_then(T3)),
        }
        self._strict = True

    async def subject_history(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        as_of: Optional[str] = None,
    ) -> SubjectHistory:
        self.calls.append((tenant_id, subject_id, as_of))
        if tenant_id != TENANT:
            raise KeyError(f"no data for tenant {tenant_id!r}")
        if (tenant_id, subject_id) not in self._store:
            return _history_unknown()
        now, then = self._store[(tenant_id, subject_id)]
        return then if as_of is not None else now


# ── Registration gates (fresh registry) ─────────────────────────────────────


def test_register_provider_on_fresh_registry() -> None:
    registry = ProviderRegistry()
    register_provider(registry)
    assert registry.get("temporal360") is not None
    assert registry.sources().get("temporal360") == "services/temporal360"
    assert "temporal360" in registry.availability()


def test_duplicate_different_object_raises() -> None:
    registry = ProviderRegistry()
    register_provider(registry)
    with pytest.raises(DuplicateProjection):
        Temporal360Provider()  # different instance for same id
        registry.register(Temporal360Provider(), source="services/temporal360")


def test_version_mismatch_raises() -> None:
    registry = ProviderRegistry()

    class WrongVersionProvider:
        projection_id = "temporal360"
        contract_version = "0.99.0"  # wrong MAJOR vs the registry contract

    with pytest.raises(ContractVersionIncompatible):
        registry.register(WrongVersionProvider(), source="tests")


def test_unknown_projection_id_raises() -> None:
    registry = ProviderRegistry()

    class UnknownProvider:
        projection_id = "not_a_real_360"
        contract_version = "1.0.0"

    with pytest.raises(ProjectionNotFound):
        registry.register(UnknownProvider(), source="tests")


def test_no_auto_registration_at_import() -> None:
    registry = ProviderRegistry()
    assert registry.get("temporal360") is None


# ── Provider projection behavior ────────────────────────────────────────────


def _request(*, mode: Optional[str] = None, time_range: Optional[TimeRangeFilter] = None) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="temporal360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=SUBJECT_A),
        temporalMode=mode,
        timeRange=time_range,
    )


async def _context(request: ProjectionRequest):
    return await ProviderRegistry().build_context("temporal360", request)


def _sections_by_id(result):
    return {s.id: s for s in result.sections}


@pytest.mark.asyncio
async def test_window_projection_is_a_valid_typed_result() -> None:
    provider = Temporal360Provider(reader=_FakeTemporalReader())
    request = _request(mode="window")
    context = await _context(request)
    result = await provider.project(request, context)

    assert result.projectionId == "temporal360"
    assert result.tenantId == TENANT
    assert result.generatedAt
    assert result.degradedReasons == []
    assert result.temporalMode == "window"
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)

    sections = _sections_by_id(result)
    assert sections["summary"].state == "available"
    assert sections["summary"].content["subject_known"] is True
    assert sections["state"].state == "available"
    assert sections["timeline"].state == "available"
    assert sections["timeline"].content["count"] == 4
    assert sections["evidence"].state == "available"
    assert sections["evidence"].content["count"] == 4

    # Claims are evidence-grounded.
    assert result.claims
    assert all(c.evidenceRefs for c in result.claims)


@pytest.mark.asyncio
async def test_window_slices_timeline_and_never_renders_empty_as_zero() -> None:
    provider = Temporal360Provider(reader=_FakeTemporalReader())
    # A window strictly after the last event -> zero overlap.
    request = _request(
        mode="window",
        time_range=TimeRangeFilter(from_="2099-01-01T00:00:00+00:00", to="2099-12-31T00:00:00+00:00"),
    )
    context = await _context(request)
    result = await provider.project(request, context)

    sections = _sections_by_id(result)
    assert sections["timeline"].state == "unknown"
    assert sections["timeline"].content["count"] == 0
    assert sections["timeline"].content["total"] == 4
    assert sections["findings"].content["findings"]  # window.no_observations


@pytest.mark.asyncio
async def test_as_of_serves_known_then_and_corrections() -> None:
    provider = Temporal360Provider(reader=_FakeTemporalReader())
    tau = "2026-01-03T12:00:00+00:00"
    request = _request(mode="as_of", time_range=TimeRangeFilter(from_=tau))
    context = await _context(request)
    result = await provider.project(request, context)

    assert result.asOf == tau
    sections = _sections_by_id(result)
    # Reconstruction state is available (authority landed in T2.1).
    state_dims = {d["id"]: d["state"] for d in sections["state"].content["dimensions"]}
    assert state_dims["knowledge_reconstruction"] == "available"
    # The reader only ever reconstructs for the request tenant + subject.
    reader = provider._reader
    assert reader.calls[-1] == (TENANT, SUBJECT_A, tau)

    # Vertex superseded + edge revoked since τ are surfaced as corrections.
    findings = sections["findings"].content["findings"]
    codes = {f["code"] for f in findings}
    assert "correction.vertex_superseded" in codes
    assert "correction.edge_revoked" in codes
    assert any(c.id == "corrections.since_as_of" for c in result.claims)


@pytest.mark.asyncio
async def test_compare_surfaces_revocation_findings() -> None:
    provider = Temporal360Provider(reader=_FakeTemporalReader())
    request = _request(mode="compare", time_range=TimeRangeFilter(from_=T3))
    context = await _context(request)
    result = await provider.project(request, context)

    assert result.temporalMode == "compare"
    sections = _sections_by_id(result)
    codes = {f["code"] for f in sections["findings"].content["findings"]}
    assert "correction.edge_revoked" in codes
    assert "correction.vertex_superseded" in codes


@pytest.mark.asyncio
async def test_as_of_without_instant_degrades_never_raises() -> None:
    provider = Temporal360Provider(reader=_FakeTemporalReader())
    request = _request(mode="as_of", time_range=None)
    context = await _context(request)
    result = await provider.project(request, context)

    sections = _sections_by_id(result)
    assert sections["summary"].state == "degraded"
    assert sections["summary"].content["mode"] == "KNOWN_NOW"  # honest label
    state_dims = {d["id"]: d["state"] for d in sections["state"].content["dimensions"]}
    assert state_dims["mode"] == "degraded"
    assert sections["findings"].content["findings"][0]["code"] == "mode.degraded"
    assert result.degradedReasons == []


@pytest.mark.asyncio
async def test_unsupported_mode_degrades_never_raises() -> None:
    provider = Temporal360Provider(reader=_FakeTemporalReader())
    request = _request(mode="forever")
    context = await _context(request)
    result = await provider.project(request, context)

    sections = _sections_by_id(result)
    assert sections["summary"].state == "degraded"
    assert sections["summary"].content["mode"] == "KNOWN_NOW"


@pytest.mark.asyncio
async def test_unknown_subject_is_typed_unknown_never_fabricated() -> None:
    provider = Temporal360Provider(reader=_FakeTemporalReader())
    request = ProjectionRequest(
        projectionId="temporal360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id="ghost"),
        temporalMode="window",
    )
    context = await _context(request)
    result = await provider.project(request, context)

    sections = _sections_by_id(result)
    assert sections["summary"].state == "missing"
    assert sections["summary"].content["subject_known"] is False
    assert sections["timeline"].state == "missing"
    assert sections["evidence"].state == "empty"
    assert sections["state"].content["dimensions"][0]["state"] == "unknown"
    assert sections["findings"].content["findings"][0]["code"] == "subject.unknown"


@pytest.mark.asyncio
async def test_tenant_isolation_never_projects_other_tenants() -> None:
    provider = Temporal360Provider(reader=_FakeTemporalReader())
    request = ProjectionRequest(
        projectionId="temporal360",
        tenantId="tenant_other",
        subject=ProjectionSubject(kind="entity", id=SUBJECT_A),
        temporalMode="window",
    )
    context = await _context(request)
    result = await provider.project(request, context)

    # The strict reader refuses; the provider degrades instead of surfacing
    # canned data, and never fabricates another tenant's truth.
    assert result.tenantId == "tenant_other"
    sections = _sections_by_id(result)
    assert sections["summary"].content["subject_known"] is False
    assert sections["timeline"].state == "missing"


def test_provider_is_read_only() -> None:
    assert Temporal360Provider.graph_mutation_policy == "read_only"
