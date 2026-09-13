"""Local repository contracts for versioned source-classification truth."""

from __future__ import annotations

from uuid import uuid4

import pytest

from services.measurement.repositories.touchpoint_repo import (
    TouchpointRepository,
    _reset_local_touchpoints,
)


@pytest.fixture(autouse=True)
def reset_local_store(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(
        "services.measurement.repositories.touchpoint_repo.get_pool",
        no_pool,
    )
    _reset_local_touchpoints()
    yield
    _reset_local_touchpoints()


def _initial_touchpoint(
    *,
    tenant_id: str = "tenant-a",
    touchpoint_id: str | None = None,
    idempotency_key: str = "shared-replay-key",
) -> dict:
    return {
        "tenant_id": tenant_id,
        "touchpoint_id": touchpoint_id or str(uuid4()),
        "profile_id": "profile-1",
        "occurred_at": "2026-07-01T12:00:00Z",
        "idempotency_key": idempotency_key,
        "channel": "referral",
        "source": "example.com",
        "medium": "referral",
        "source_class": "external_referral",
        "referral_mediation_type": "unknown_external_referral",
        "actor_type": "human",
        "journey_role": "discovery",
        "evidence_confidence": 0.65,
        "verification_level": "inferred",
        "source_classifier_version": "1.0",
        "normalized_referrer_domain": "example.com",
        "referrer_path_hash": "privacy-safe-path-hash",
        "source_classification_evidence": {"signals": ["external_referrer_domain"]},
        "attribution_eligible": True,
        "referrer": "https://example.com/",
    }


def _corrected_classification() -> dict:
    return {
        "channel": "ai_referral",
        "source": "openai",
        "medium": "ai_referral",
        "source_class": "ai_referral",
        "referral_mediation_type": "ai_mediated_human_referral",
        "ai_provider": "openai",
        "ai_product": "chatgpt",
        "actor_type": "human",
        "journey_role": "discovery",
        "evidence_confidence": 0.96,
        "verification_level": "verified_domain",
        "source_classifier_version": "2.0",
        "normalized_referrer_domain": "chatgpt.com",
        "referrer_path_hash": "privacy-safe-path-hash",
        "source_classification_evidence": {"signals": ["known_ai_referrer_domain"]},
        "attribution_eligible": True,
        "referrer": "https://chatgpt.com/",
    }


@pytest.mark.asyncio
async def test_ingestion_creates_one_current_immutable_revision() -> None:
    repo = TouchpointRepository()
    row = _initial_touchpoint()

    stored = await repo.upsert(row)
    history = await repo.classification_history("tenant-a", row["touchpoint_id"])

    assert stored["source_classification_id"]
    assert len(history) == 1
    assert history[0]["classification_id"] == stored["source_classification_id"]
    assert history[0]["classifier_version"] == "1.0"
    assert history[0]["reason"] == "ingestion"
    assert history[0]["is_current"] is True
    assert history[0]["classification"]["source"] == "example.com"


@pytest.mark.asyncio
async def test_reclassification_appends_and_links_revision_without_rewriting_prior() -> None:
    repo = TouchpointRepository()
    row = _initial_touchpoint()
    await repo.upsert(row)
    original = (await repo.classification_history("tenant-a", row["touchpoint_id"]))[0]
    original_snapshot = dict(original["classification"])

    corrected = await repo.apply_source_classification(
        "tenant-a",
        row["touchpoint_id"],
        _corrected_classification(),
        input_hash="input-v2",
        reason="historical_reclassification:2.0",
        job_id="job-1",
    )
    history = await repo.classification_history("tenant-a", row["touchpoint_id"])

    assert len(history) == 2
    prior, current = history
    assert prior["classification"] == original_snapshot
    assert prior["is_current"] is False
    assert prior["superseded_by"] == current["classification_id"]
    assert current["previous_classification_id"] == prior["classification_id"]
    assert current["is_current"] is True
    assert current["prior_classification"]["source"] == "example.com"
    assert current["classification"]["source"] == "openai"
    assert corrected["source_classification_id"] == current["classification_id"]
    assert corrected["ai_provider"] == "openai"


@pytest.mark.asyncio
async def test_same_classifier_version_and_input_hash_is_idempotent() -> None:
    repo = TouchpointRepository()
    row = _initial_touchpoint()
    await repo.upsert(row)
    corrected = _corrected_classification()

    first = await repo.apply_source_classification(
        "tenant-a",
        row["touchpoint_id"],
        corrected,
        input_hash="same-input",
        reason="repair",
    )
    replay = await repo.apply_source_classification(
        "tenant-a",
        row["touchpoint_id"],
        {**corrected, "source": "must-not-overwrite-on-replay"},
        input_hash="same-input",
        reason="repair-retry",
    )
    history = await repo.classification_history("tenant-a", row["touchpoint_id"])

    assert len(history) == 2
    assert replay["source_classification_id"] == first["source_classification_id"]
    assert replay["source"] == "openai"
    assert sum(1 for revision in history if revision["is_current"]) == 1


@pytest.mark.asyncio
async def test_local_idempotency_key_is_tenant_scoped_like_postgres() -> None:
    repo = TouchpointRepository()
    tenant_a = _initial_touchpoint(tenant_id="tenant-a")
    tenant_b = _initial_touchpoint(tenant_id="tenant-b")

    stored_a = await repo.upsert(tenant_a)
    stored_b = await repo.upsert(tenant_b)

    assert stored_a["tenant_id"] == "tenant-a"
    assert stored_b["tenant_id"] == "tenant-b"
    assert stored_a["touchpoint_id"] != stored_b["touchpoint_id"]
    assert await repo.get("tenant-a", stored_b["touchpoint_id"]) is None
    assert await repo.get("tenant-b", stored_a["touchpoint_id"]) is None


@pytest.mark.asyncio
async def test_health_is_tenant_scoped_and_counts_all_verified_levels() -> None:
    repo = TouchpointRepository()
    await repo.upsert(_initial_touchpoint(tenant_id="tenant-a", idempotency_key="a-1"))
    verified_domain = _initial_touchpoint(tenant_id="tenant-a", idempotency_key="a-2")
    verified_domain.update(
        {
            "verification_level": "verified_domain",
            "ai_provider": "openai",
            "referral_mediation_type": "ai_mediated_human_referral",
        }
    )
    await repo.upsert(verified_domain)
    excluded = _initial_touchpoint(tenant_id="tenant-a", idempotency_key="a-3")
    excluded.update(
        {
            "verification_level": "verified_click_id",
            "attribution_eligible": False,
            "ai_provider": "openai",
            "referral_mediation_type": "crawler_discovery",
        }
    )
    await repo.upsert(excluded)
    await repo.upsert(_initial_touchpoint(tenant_id="tenant-b", idempotency_key="b-1"))

    health = await repo.source_classification_health("tenant-a")

    assert health["summary"] == {
        "total": 3,
        "classified": 3,
        "unclassified": 0,
        "excluded": 1,
        "verified": 2,
    }
    assert health["providers"] == [{"name": "openai", "count": 2}]
    assert {item["name"] for item in health["mediation"]} == {
        "unknown_external_referral",
        "ai_mediated_human_referral",
        "crawler_discovery",
    }
