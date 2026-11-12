"""Episode360 risk flags join only exact typed primary-subject RiskSignals."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EntityRef  # noqa: E402
from journeys.measurement.episodes.provider import (  # noqa: E402
    Episode360Provider,
    EpisodeSubjectGraphRead,
)
from shared.backend_interpretation.primitives import EpisodeRecord  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)

TENANT = "tenant-episode360-risk"
EPISODE_ID = "episode-risk-1"
SUBJECT_KIND = "user"
SUBJECT_ID = "user-risk-1"


class FakeEpisodeStore:
    def __init__(self, episode: EpisodeRecord) -> None:
        self.episode = episode

    async def get(self, tenant_id: str, episode_id: str) -> EpisodeRecord | None:
        if tenant_id == self.episode.tenant_id and episode_id == self.episode.episode_id:
            return self.episode
        return None

    async def list_page_by_tenant(self, *args, **kwargs):
        raise AssertionError("exact episode request must use the composite-key read")


class FakeRiskSignalSource:
    def __init__(self, rows: list[dict] | Exception) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    async def signals(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.rows, Exception):
            raise self.rows
        return self.rows


class FakeRelationshipReader:
    async def subject_history(self, *, tenant_id: str, subject_id: str):
        return EpisodeSubjectGraphRead(
            tenant_id=tenant_id,
            subject_id=subject_id,
        )


def _episode() -> EpisodeRecord:
    return EpisodeRecord(
        episode_id=EPISODE_ID,
        tenant_id=TENANT,
        subject=EntityRef(kind=SUBJECT_KIND, id=SUBJECT_ID),
        kind="support_case",
    )


def _risk_signal(
    signal_id: str,
    *,
    tenant_id: str = TENANT,
    subject_kind: str = SUBJECT_KIND,
    subject_id: str = SUBJECT_ID,
    evidence_id: str | None = None,
) -> dict:
    return {
        "signal_id": signal_id,
        "tenant_id": tenant_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "risk_dimension": "behavioral",
        "claim_state": "inferred",
        "confidence": 0.72,
        "evidence_refs": [
            {
                "id": evidence_id or f"evidence-{signal_id}",
                "type": "event",
                "source": "risk-detector",
                "observedAt": "2026-10-22T12:00:00+00:00",
            }
        ],
        "source": "aether.fraud.detector.behavioral",
        "detector_version": "3.1",
        "observed_at": "2026-10-22T12:00:00+00:00",
        "score": 0.61,
        "value": None,
    }


def _request() -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="episode360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="episode", id=EPISODE_ID),
        includeClaims=True,
    )


def _context(*, tenant_id: str = TENANT) -> ProjectionContext:
    return ProjectionContext(
        projectionId="episode360",
        tenantId=tenant_id,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )


def _section(result, section_id: str):
    return next(section for section in result.sections if section.id == section_id)


def _provider(source: FakeRiskSignalSource) -> Episode360Provider:
    return Episode360Provider(
        episode_store=FakeEpisodeStore(_episode()),
        subject_relationship_reader=FakeRelationshipReader(),
        risk_signal_source=source,
    )


@pytest.mark.asyncio
async def test_episode_risk_flags_join_exact_subject_and_preserve_evidence_and_epistemics():
    source = FakeRiskSignalSource([_risk_signal("signal-1")])
    result = await _provider(source).project(_request(), _context())

    assert source.calls == [
        {
            "tenant_id": TENANT,
            "subject_kind": SUBJECT_KIND,
            "subject_id": SUBJECT_ID,
            "limit": 101,
        }
    ]
    risk_flags = _section(result, "risk_flags").content
    assert "riskFlags" not in _section(result, "outcomes").content
    assert risk_flags["state"] == "degraded"
    assert risk_flags["coverage"] == "exact_episode_primary_subject_signals_only"
    assert risk_flags["subject"] == {"kind": SUBJECT_KIND, "id": SUBJECT_ID}
    assert risk_flags["count"] is None
    assert risk_flags["observedCount"] == 1
    assert risk_flags["flags"][0]["signalId"] == "signal-1"
    assert risk_flags["flags"][0]["claimState"] == "inferred"
    assert {ref["id"] for ref in risk_flags["evidenceRefs"]} == {
        "signal-1",
        "evidence-signal-1",
    }
    assert risk_flags["freshness"]["state"] == "unknown"
    assert risk_flags["policy"]["state"] == "unknown"

    slot = _section(result, "summary").content["requiredSlotCoverage"]["risk_flags"]
    assert slot["state"] == "degraded"
    assert slot["coverage"] == "exact_episode_primary_subject_signals_only"
    assert {ref["id"] for ref in slot["evidenceRefs"]} == {
        "signal-1",
        "evidence-signal-1",
    }
    claim = next(claim for claim in result.claims if claim.id.endswith("signal-1"))
    assert claim.claimState.value == "inferred"
    assert claim.domainSlotIds == ["risk_flags", "evidence_trace"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        _risk_signal("wrong-tenant", tenant_id="tenant-other"),
        _risk_signal("wrong-kind", subject_kind="agent"),
        _risk_signal("wrong-subject", subject_id="user-other"),
    ],
)
async def test_episode_risk_flags_reject_nonmatching_tenant_or_typed_subject(row):
    source = FakeRiskSignalSource([row])
    result = await _provider(source).project(_request(), _context())

    risk_flags = _section(result, "risk_flags").content
    assert risk_flags["state"] == "degraded"
    assert risk_flags["flags"] == []
    assert risk_flags["observedCount"] == 0
    assert risk_flags["evidenceRefs"] == []
    assert risk_flags["tenantMismatch"] is (row["tenant_id"] != TENANT)
    assert risk_flags["invalidRecords"] is (row["tenant_id"] == TENANT)
    assert not [claim for claim in result.claims if "risk-signal" in claim.id]


@pytest.mark.asyncio
async def test_episode_risk_flags_keep_empty_exact_read_unknown_not_absent():
    source = FakeRiskSignalSource([])
    result = await _provider(source).project(_request(), _context())

    risk_flags = _section(result, "risk_flags").content
    assert risk_flags["state"] == "unknown"
    assert risk_flags["coverage"] == "unknown"
    assert risk_flags["flags"] == []
    assert risk_flags["count"] is None
    assert "absence_not_established" in risk_flags["reason"]
    assert risk_flags["freshness"]["state"] == "unknown"
    assert risk_flags["policy"]["state"] == "unknown"


@pytest.mark.asyncio
async def test_episode_risk_flags_fail_closed_when_authority_is_unavailable():
    source = FakeRiskSignalSource(RuntimeError("private storage diagnostic"))
    result = await _provider(source).project(_request(), _context())

    risk_flags = _section(result, "risk_flags").content
    assert risk_flags["state"] == "unknown"
    assert risk_flags["flags"] == []
    assert risk_flags["evidenceRefs"] == []
    assert risk_flags["reason"] == "episode_risk_signal_authority_unavailable"


@pytest.mark.asyncio
async def test_episode_risk_flags_cap_records_and_mark_truncated_read():
    source = FakeRiskSignalSource([_risk_signal(f"signal-{index:03d}") for index in range(101)])
    result = await _provider(source).project(_request(), _context())

    risk_flags = _section(result, "risk_flags").content
    assert len(risk_flags["flags"]) == 100
    assert risk_flags["observedCount"] == 100
    assert risk_flags["truncated"] is True
    assert risk_flags["state"] == "degraded"
    assert "truncated" in risk_flags["reason"]


@pytest.mark.asyncio
async def test_episode_risk_flags_do_not_read_when_exact_episode_is_missing():
    source = FakeRiskSignalSource([])
    provider = _provider(source)
    request = ProjectionRequest(
        projectionId="episode360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="episode", id="episode-missing"),
    )
    result = await provider.project(request, _context())

    assert source.calls == []
    assert _section(result, "risk_flags").content["state"] == "unknown"


@pytest.mark.asyncio
async def test_episode_risk_flags_are_not_read_or_attached_to_outcomes_when_not_requested():
    source = FakeRiskSignalSource([_risk_signal("signal-private")])
    request = _request().model_copy(update={"includeSections": ["outcomes"]})
    result = await _provider(source).project(request, _context())

    assert source.calls == []
    assert all(section.id != "risk_flags" for section in result.sections)
    assert "riskFlags" not in _section(result, "outcomes").content
    assert "signal-private" not in str(_section(result, "outcomes").content)
