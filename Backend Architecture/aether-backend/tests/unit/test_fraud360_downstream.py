"""Fraud360 Phase-6 downstream — material-hypothesis → comparison-finding handoff.

Covers the honest projection contract: only MATERIAL hypotheses with a
mappable suspicion claim become finding candidates (never ``candidate``-state
suspicions, never ``unknown`` claims); candidates carry a causal claim capped by
their evidence basis; the materialization path respects the comparison-plane
``enabled`` flag (disabled ⇒ an honest skipped envelope, never an implicit
enable), applies noise-control watchlists without silently dropping suppressed
findings, and dispositions delegate to :class:`FindingsService` (no parallel
lifecycle).
"""

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

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.fraud360.contracts import (  # noqa: E402
    EpistemicStatus,
    FraudHypothesis,
    FraudHypothesisState,
)
from services.fraud360.downstream import (  # noqa: E402
    DISABLED_ENVELOPE,
    FINDING_TYPE,
    dispose_finding,
    hypothesis_to_finding_candidate,
    material_hypotheses_to_findings,
)
from services.fraud360.store import FraudHypothesisRepository  # noqa: E402
from services.intelligence.comparison.findings import (  # noqa: E402
    FindingRecord,
    FindingsService,
)
from services.intelligence.comparison.watchlists import (  # noqa: E402
    NoiseControls,
    WatchlistDefinition,
)

TENANT = "tenant-a"
DEFINITION_ID = "fraud360.test.def"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _material(
    hypothesis_id: str,
    *,
    subject_id: str = "ent_1",
    materiality: float = 0.8,
    patterns: tuple[str, ...] = ("circular_value_flow",),
    claim_state: EpistemicStatus = EpistemicStatus.DERIVED,
    state: FraudHypothesisState = FraudHypothesisState.MATERIAL,
) -> FraudHypothesis:
    return FraudHypothesis(
        hypothesis_id=hypothesis_id,
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id=subject_id,
        state=state,
        claim_state=claim_state,
        materiality=materiality,
        matched_pattern_ids=list(patterns),
    )


# ── hypothesis → finding candidate ─────────────────────────────────────────

def test_candidate_none_when_hypothesis_not_material():
    assert (
        hypothesis_to_finding_candidate(
            _material("h-cand", state=FraudHypothesisState.CANDIDATE)
        )
        is None
    )
    assert (
        hypothesis_to_finding_candidate(
            _material("h-supported", state=FraudHypothesisState.SUPPORTED)
        )
        is None
    )


def test_candidate_none_when_claim_has_no_honest_causal_projection():
    assert (
        hypothesis_to_finding_candidate(
            _material("h-unknown", claim_state=EpistemicStatus.UNKNOWN)
        )
        is None
    )


def test_material_hypothesis_projects_a_contract_valid_finding_candidate():
    hypothesis = _material("h-1", materiality=0.8)
    candidate = hypothesis_to_finding_candidate(hypothesis)
    assert candidate is not None
    # deterministic, content-derived id
    assert candidate["id"].startswith("ff_")
    assert candidate["id"] == hypothesis_to_finding_candidate(hypothesis)["id"]
    assert candidate["tenant_id"] == TENANT
    assert candidate["finding_type"] == FINDING_TYPE
    assert candidate["comparison_run_id"] == ""
    assert candidate["dimension"] == "fraud_risk"
    assert candidate["metric"] == "circular_value_flow"
    assert candidate["causal_claim"] == "inferred"  # derived suspicion ≤ its ceiling
    assert candidate["evidence_basis"] == "model_inference"
    # a candidate that materializes never fabricates a score/claim past its basis
    record = FindingRecord(**candidate)
    assert record.fact_linkage in ("linked", "pending")
    assert record.disposition == "informational"


# ── materialization (respects the comparison-plane enabled flag) ───────────

async def test_materialization_disabled_returns_honest_skipped_envelope():
    result = await material_hypotheses_to_findings(
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id="ent_1",
        definition_id=DEFINITION_ID,
        watchlists=[],
        enabled=False,
    )
    assert result == DISABLED_ENVELOPE
    # nothing was written while disabled
    rows = await FindingsService().list(TENANT)
    assert rows == []


async def test_materialization_creates_only_material_findings_and_records_suppression():
    repo = FraudHypothesisRepository()
    # material + well-scored → created; material but below the floor → suppressed;
    # material but claim with no honest projection → skipped; candidate → ignored.
    await repo.create(TENANT, _material("h-high", materiality=0.8))
    await repo.create(TENANT, _material("h-low", materiality=0.2, patterns=("wallet_abuse",)))
    await repo.create(
        TENANT, _material("h-unknown", claim_state=EpistemicStatus.UNKNOWN)
    )
    await repo.create(
        TENANT, _material("h-cand", state=FraudHypothesisState.CANDIDATE)
    )

    watchlist = WatchlistDefinition(
        watchlist_id="wl-floor",
        tenant_id=TENANT,
        name="materiality-floor-0.5",
        noise=NoiseControls(materiality_floor=0.5),
    )
    result = await material_hypotheses_to_findings(
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id="ent_1",
        hypothesis_repo=repo,
        definition_id=DEFINITION_ID,
        watchlists=[watchlist],
        enabled=True,
    )

    assert result["created"] == 1
    assert result["suppressed"] == 1
    assert result["skipped"] == 1
    assert result["errors"] == 0

    outcomes = {r["hypothesis_id"]: r for r in result["records"]}
    assert outcomes["h-high"]["outcome"] == "created"
    assert outcomes["h-low"]["outcome"] == "suppressed"
    assert outcomes["h-low"]["suppression_reason"] == "below_materiality_floor:0.5"
    assert outcomes["h-unknown"]["outcome"] == "skipped"
    assert "h-cand" not in outcomes  # candidate-state suspicion never materializes

    # suppression is never silent: the suppressed finding IS persisted
    low_finding = await FindingsService().get(
        TENANT, outcomes["h-low"]["finding_id"]
    )
    assert low_finding["disposition"] == "suppressed"
    assert low_finding["suppression_reason"].startswith("below_materiality_floor")
    # distinct metric → the two materialized findings were not dedupe-collapsed
    assert result["created"] == 1


# ── disposition delegation ─────────────────────────────────────────────────

async def test_dispose_finding_delegates_to_findings_service():
    repo = FraudHypothesisRepository()
    await repo.create(TENANT, _material("h-dispose", materiality=0.8))
    result = await material_hypotheses_to_findings(
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id="ent_1",
        hypothesis_repo=repo,
        definition_id=DEFINITION_ID,
        watchlists=[],  # no watchlist → allowed (no noise controls)
        enabled=True,
    )
    assert result["created"] == 1
    finding_id = result["records"][0]["finding_id"]

    updated = await dispose_finding(
        TENANT, finding_id, "monitor", actor_id="op_1"
    )
    assert updated["disposition"] == "monitor"
    assert len(updated["disposition_history"]) == 1
    assert updated["disposition_history"][0]["actor_id"] == "op_1"

    fetched = await FindingsService().get(TENANT, finding_id)
    assert fetched["disposition"] == "monitor"
