"""Profile prediction output DSR erasure scope and legal-hold behavior."""

from __future__ import annotations

import pytest

from governance.consent.erasure_planes import ErasureSubject, erase_profile360_plane


TENANT = "tenant-profile-dsr"
ENTITY = "canonical-entity-1"
USER = "user-1"


class _DeleteRepo:
    def __init__(self, count: int) -> None:
        self.count = count
        self.calls: list[tuple[str, str, list[str]]] = []

    async def delete_for_tenant_where(self, tenant_id, field, values):
        self.calls.append((tenant_id, field, list(values)))
        return self.count


def _subject() -> ErasureSubject:
    return ErasureSubject(
        tenant_id=TENANT,
        user_id=USER,
        entity_ids=frozenset({ENTITY}),
    )


def _install_repositories(monkeypatch, *, held=None):
    import governance.policy.repositories
    import identity.profile.prediction_authority as prediction_authority
    import repositories.repos
    import shared.storage.lifecycle

    profiles = _DeleteRepo(1)
    behavior = _DeleteRepo(2)
    chains = _DeleteRepo(3)
    predictions = _DeleteRepo(4)
    holds: list[tuple[str, str, str | None]] = []

    monkeypatch.setattr(repositories.repos, "_ProfileStore", lambda: profiles)
    monkeypatch.setattr(repositories.repos, "BehaviorProfileRepository", lambda: behavior)
    monkeypatch.setattr(repositories.repos, "JourneyChainRepository", lambda: chains)
    monkeypatch.setattr(
        repositories.repos,
        "tenant_record_id",
        lambda tenant, entity: f"{tenant}:{entity}",
    )
    monkeypatch.setattr(
        prediction_authority,
        "ProfilePredictionOutputRepository",
        lambda: predictions,
    )

    class _Lifecycle:
        async def active_hold(self, tenant_id, resource_type, subject_ref=None):
            holds.append((tenant_id, resource_type, subject_ref))
            if held and subject_ref == held["subject_ref"]:
                return held
            return None

    monkeypatch.setattr(shared.storage.lifecycle, "StorageLifecycle", _Lifecycle)
    return profiles, behavior, chains, predictions, holds


@pytest.mark.asyncio
async def test_profile_prediction_outputs_are_erased_for_exact_tenant_entities(monkeypatch):
    profiles, behavior, chains, predictions, holds = _install_repositories(monkeypatch)

    receipt = (await erase_profile360_plane(_subject()))["profile360_snapshots"]

    expected_entities = [ENTITY, USER]
    assert profiles.calls == [
        (TENANT, "id", [f"{TENANT}:{entity}" for entity in expected_entities])
    ]
    assert behavior.calls == [(TENANT, "entity_id", expected_entities)]
    assert chains.calls == [(TENANT, "entity_id", expected_entities)]
    assert predictions.calls == [(TENANT, "entity_id", expected_entities)]
    assert holds == [
        (TENANT, "profile_prediction_outputs", ENTITY),
        (TENANT, "profile_prediction_outputs", USER),
    ]
    assert receipt.status == "completed"
    assert receipt.records_impacted == 10
    assert receipt.detail["profile_prediction_outputs"] == 4


@pytest.mark.asyncio
async def test_profile_prediction_output_erasure_honors_exact_subject_legal_hold(monkeypatch):
    held = {
        "hold_id": "hold-profile-prediction",
        "subject_ref": ENTITY,
        "reason": "preserve active proceeding",
    }
    _profiles, _behavior, _chains, predictions, _holds = _install_repositories(
        monkeypatch, held=held
    )

    receipt = (await erase_profile360_plane(_subject()))["profile360_snapshots"]

    assert predictions.calls == []
    assert receipt.status == "skipped_legal_hold"
    assert receipt.policy_decision_id == "storage_legal_hold:hold-profile-prediction"
    assert receipt.blocked_reason == "preserve active proceeding"
    assert receipt.records_impacted == 6
    assert receipt.detail["profile_prediction_outputs_skipped_legal_hold"] == 1
