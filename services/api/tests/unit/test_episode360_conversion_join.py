"""Episode360 exact episode-outcome joins into conversion-event coverage."""

from __future__ import annotations

import json
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
from journeys.measurement.episodes.provider import Episode360Provider  # noqa: E402
from shared.backend_interpretation.primitives import EpisodeRecord  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)

TENANT = "tenant-episode360-conversion-join"
EPISODE_ID = "episode-conversion-join-1"


def _episode(outcome_ids: list[str]) -> EpisodeRecord:
    return EpisodeRecord(
        episode_id=EPISODE_ID,
        tenant_id=TENANT,
        subject=EntityRef(kind="user", id="user-1"),
        kind="support_case",
        outcome_ids=outcome_ids,
    )


def _outcome(
    outcome_id: str,
    *,
    tenant_id: str = TENANT,
    definition_ref: str = "campaign_conversion",
) -> dict:
    return {
        "outcome_id": outcome_id,
        "tenant_id": tenant_id,
        "definition_ref": definition_ref,
        "state": "final",
        "claim_type": "observed",
        "achieved_at": "2026-10-20T12:05:00+00:00",
        "updated_at": "2026-10-20T12:06:00+00:00",
        "value_amount": "125.00",
        "value_currency": "USD",
        "evidence_refs": [
            {
                "id": f"event-{outcome_id}",
                "type": "event",
                "source": "silver_outcome_facts",
                "observedAt": "2026-10-20T12:05:00+00:00",
            }
        ],
        "private_payload": "must-not-be-projected",
    }


class FakeEpisodeStore:
    def __init__(self, episode: EpisodeRecord) -> None:
        self.episode = episode

    async def get(self, tenant_id: str, episode_id: str) -> EpisodeRecord | None:
        if tenant_id == self.episode.tenant_id and episode_id == self.episode.episode_id:
            return self.episode
        return None

    async def list_page_by_tenant(self, *args, **kwargs):
        raise AssertionError("exact episode read should not query a tenant page")


class FakeOutcomeSource:
    def __init__(self, rows: dict[str, dict | None]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str]] = []

    async def get(self, tenant_id: str, outcome_id: str):
        self.calls.append((tenant_id, outcome_id))
        return self.rows.get(outcome_id)


def _request() -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="episode360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="episode", id=EPISODE_ID),
        includeClaims=True,
    )


def _context() -> ProjectionContext:
    return ProjectionContext(
        projectionId="episode360",
        tenantId=TENANT,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )


def _section(result, section_id: str):
    return next(section for section in result.sections if section.id == section_id)


@pytest.mark.asyncio
async def test_episode_conversion_slot_joins_only_explicit_tenant_outcomes(monkeypatch):
    from shared.backend_interpretation import flags, stores

    source = FakeOutcomeSource(
        {
            "outcome-conversion": _outcome("outcome-conversion"),
            "outcome-task": _outcome(
                "outcome-task", definition_ref="agent_task_completion"
            ),
        }
    )
    monkeypatch.setattr(flags, "outcome_truth_store_enabled", lambda: True)
    monkeypatch.setattr(stores, "OutcomeTruthStore", lambda: source)
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(
            _episode(["outcome-conversion", "outcome-task"])
        )
    ).project(_request(), _context())

    assert source.calls == [
        (TENANT, "outcome-conversion"),
        (TENANT, "outcome-task"),
    ]
    outcomes = _section(result, "outcomes").content
    conversions = outcomes["conversionEvents"]
    assert conversions["state"] == "degraded"
    assert conversions["coverage"] == "exact_episode_outcome_ids_only"
    assert conversions["requestedOutcomeIds"] == [
        "outcome-conversion",
        "outcome-task",
    ]
    assert conversions["resolvedOutcomeIds"] == [
        "outcome-conversion",
        "outcome-task",
    ]
    assert conversions["observedCount"] == 1
    assert conversions["events"] == [
        {
            "outcomeId": "outcome-conversion",
            "episodeIds": [EPISODE_ID],
            "conversionType": "campaign_conversion",
            "outcomeState": "final",
            "claimType": "observed",
            "occurredAt": "2026-10-20T12:05:00+00:00",
            "evidenceRefs": [
                {
                    "id": "event-outcome-conversion",
                    "type": "event",
                    "source": "silver_outcome_facts",
                    "observedAt": "2026-10-20T12:05:00+00:00",
                }
            ],
        }
    ]
    assert conversions["freshness"]["state"] == "unknown"
    assert conversions["policy"]["state"] == "unknown"
    assert {ref["id"] for ref in conversions["evidenceRefs"]} == {
        "event-outcome-conversion",
        "event-outcome-task",
    }

    required = _section(result, "summary").content["requiredSlotCoverage"][
        "conversion_events"
    ]
    assert required["state"] == "degraded"
    assert required["coverage"] == "exact_episode_outcome_ids_only"
    assert required["evidenceRefs"] == conversions["evidenceRefs"]
    conversion_claims = [
        claim
        for claim in result.claims
        if "conversion_events" in claim.domainSlotIds
    ]
    assert len(conversion_claims) == 1
    assert conversion_claims[0].evidenceRefs[0].id == "event-outcome-conversion"
    serialized = json.dumps(result.model_dump(mode="json"))
    assert "must-not-be-projected" not in serialized
    assert '"value_amount"' not in serialized


@pytest.mark.asyncio
async def test_episode_conversion_slot_omits_cross_tenant_rows_and_keeps_unknown_state():
    source = FakeOutcomeSource(
        {
            "outcome-cross-tenant": _outcome(
                "outcome-cross-tenant", tenant_id="tenant-other"
            ),
            "outcome-missing": None,
        }
    )
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(
            _episode(["outcome-cross-tenant", "outcome-missing"])
        ),
        outcome_source=source,
    ).project(_request(), _context())

    conversions = _section(result, "outcomes").content["conversionEvents"]
    assert conversions["state"] == "unknown"
    assert conversions["events"] == []
    assert conversions["evidenceRefs"] == []
    assert conversions["reason"] == "canonical_outcome_truth_scope_mismatch"
    required = _section(result, "summary").content["requiredSlotCoverage"][
        "conversion_events"
    ]
    assert required["state"] == "unknown"
    assert required["evidenceRefs"] == []
    assert "episode_outcome_tenant_scope_mismatch" in result.degradedReasons


@pytest.mark.asyncio
async def test_episode_conversion_slot_stays_unknown_when_canonical_store_is_disabled(monkeypatch):
    from shared.backend_interpretation import flags

    monkeypatch.setattr(flags, "outcome_truth_store_enabled", lambda: False)
    result = await Episode360Provider(
        episode_store=FakeEpisodeStore(_episode(["outcome-conversion"]))
    ).project(_request(), _context())

    conversions = _section(result, "outcomes").content["conversionEvents"]
    assert conversions["state"] == "unknown"
    assert conversions["reason"] == "canonical_outcome_truth_store_disabled"
    assert conversions["events"] == []
    assert conversions["freshness"]["state"] == "unknown"
    assert conversions["policy"]["state"] == "unknown"
    assert "episode_outcome_truth_store_disabled" in result.degradedReasons
