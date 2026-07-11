"""Identity merge-correctness foundation.

Covers the confirmed silent bugs fixed in the identity-correctness change:
  1. merge tombstones written by CANONICAL entity id (both merge paths),
  2. survivor-redirect following the tombstone chain (cycle/hop safe),
  3. signal observations linked to their resolved entity,
  4. the measurement consumer reading the real IDENTITY_MERGED payload keys.

All in-memory (AETHER_ENV=local); no DB/Redis/HTTP.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

for _mod in ("jwt", "cryptography", "cryptography.hazmat"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.models import IdentitySignalType, SubjectStatus  # noqa: E402
from services.identity.redirects import redirect_fields, resolve_entity_redirect  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402

TENANT = "tenant-merge"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.fixture
def repo():
    return IdentityResolutionRepository()


# ── merge tombstone by canonical id ──────────────────────────────────────────


async def test_tombstone_by_canonical_id_on_existing_subject(repo):
    await repo.create_subject(TENANT, "entity-secondary")
    await repo.create_subject(TENANT, "entity-primary")

    await repo.mark_subject_merged_by_canonical_id(TENANT, "entity-secondary", "entity-primary")

    row = await repo.get_subject_by_canonical_entity_id(TENANT, "entity-secondary")
    assert row["status"] == SubjectStatus.MERGED.value
    assert row["merged_into_entity_id"] == "entity-primary"


async def test_tombstone_creates_row_when_subject_missing(repo):
    # No subject row exists for the merged entity (alias-only owner).
    await repo.mark_subject_merged_by_canonical_id(TENANT, "ghost-entity", "entity-primary")

    row = await repo.get_subject_by_canonical_entity_id(TENANT, "ghost-entity")
    assert row is not None
    assert row["status"] == SubjectStatus.MERGED.value
    assert row["merged_into_entity_id"] == "entity-primary"


async def test_tombstone_is_tenant_scoped(repo):
    await repo.create_subject(TENANT, "e1")
    await repo.mark_subject_merged_by_canonical_id(TENANT, "e1", "e2")
    # Another tenant's lookup of the same id sees nothing.
    assert await repo.get_subject_by_canonical_entity_id("other-tenant", "e1") is None


# ── survivor redirect ────────────────────────────────────────────────────────


async def test_resolve_surviving_follows_chain(repo):
    await repo.create_subject(TENANT, "a")
    await repo.create_subject(TENANT, "b")
    await repo.create_subject(TENANT, "c")
    await repo.mark_subject_merged_by_canonical_id(TENANT, "a", "b")
    await repo.mark_subject_merged_by_canonical_id(TENANT, "b", "c")

    assert await repo.resolve_surviving_canonical_entity_id(TENANT, "a") == "c"
    assert await repo.resolve_surviving_canonical_entity_id(TENANT, "b") == "c"


async def test_active_entity_resolves_to_itself(repo):
    await repo.create_subject(TENANT, "solo")
    assert await repo.resolve_surviving_canonical_entity_id(TENANT, "solo") == "solo"


async def test_unknown_entity_resolves_to_itself(repo):
    assert await repo.resolve_surviving_canonical_entity_id(TENANT, "nope") == "nope"


async def test_cycle_does_not_loop_forever(repo):
    await repo.create_subject(TENANT, "x")
    await repo.create_subject(TENANT, "y")
    await repo.mark_subject_merged_by_canonical_id(TENANT, "x", "y")
    await repo.mark_subject_merged_by_canonical_id(TENANT, "y", "x")  # cycle
    result = await repo.resolve_surviving_canonical_entity_id(TENANT, "x", max_hops=5)
    assert result in ("x", "y")  # terminates at a safe id, no infinite loop


async def test_resolve_entity_redirect_helper(repo):
    await repo.create_subject(TENANT, "sec")
    await repo.create_subject(TENANT, "surv")
    await repo.mark_subject_merged_by_canonical_id(TENANT, "sec", "surv")

    resolved, redirected = await resolve_entity_redirect(repo, TENANT, "sec")
    assert resolved == "surv" and redirected is True

    resolved2, redirected2 = await resolve_entity_redirect(repo, TENANT, "surv")
    assert resolved2 == "surv" and redirected2 is False


def test_redirect_fields_shape():
    assert redirect_fields("a", "a") == {"resolved_entity_id": "a", "redirected": False}
    assert redirect_fields("a", "b") == {"resolved_entity_id": "b", "redirected": True}


# ── observation → entity linkage ─────────────────────────────────────────────


async def test_observation_backfill_makes_entity_lookup_work(repo):
    # Observation persisted before the entity is known (no canonical id yet).
    await repo.create_signal_observation(
        tenant_id=TENANT,
        source_event_id="evt-1",
        source_platform="web",
        source_sdk="js",
        signal_type=IdentitySignalType.EMAIL_HASH,
        signal_value_hash="hash-1",
    )
    # Before backfill: entity-scoped lookup finds nothing.
    assert await repo.get_observations_for_entity(TENANT, "entity-1") == []

    # After resolution the resolver links the event's observations to the entity.
    updated = await repo.set_observations_canonical_entity(TENANT, "evt-1", "entity-1")
    assert updated == 1

    found = await repo.get_observations_for_entity(TENANT, "entity-1")
    assert len(found) == 1
    assert found[0]["canonical_entity_id"] == "entity-1"


async def test_observation_created_with_canonical_id(repo):
    await repo.create_signal_observation(
        tenant_id=TENANT,
        source_event_id="evt-2",
        source_platform="web",
        source_sdk="js",
        signal_type=IdentitySignalType.EMAIL_HASH,
        signal_value_hash="hash-2",
        canonical_entity_id="entity-2",
    )
    found = await repo.get_observations_for_entity(TENANT, "entity-2")
    assert len(found) == 1


async def test_backfill_is_idempotent(repo):
    await repo.create_signal_observation(
        tenant_id=TENANT, source_event_id="evt-3", source_platform="web", source_sdk="js",
        signal_type=IdentitySignalType.EMAIL_HASH, signal_value_hash="h3",
    )
    assert await repo.set_observations_canonical_entity(TENANT, "evt-3", "e3") == 1
    assert await repo.set_observations_canonical_entity(TENANT, "evt-3", "e3") == 0  # no-op


# ── measurement consumer reads the real payload keys ─────────────────────────


async def test_consumer_reads_primary_secondary_keys(monkeypatch):
    from shared.events.events import Event, Topic
    from services.measurement.identity_consumer import MeasurementIdentityConsumer

    consumer = MeasurementIdentityConsumer(producer=MagicMock())

    calls: list[tuple[str, str, str]] = []

    async def _fake_rebuild(tenant_id, profile_id, reason):
        calls.append((tenant_id, profile_id, reason))

    monkeypatch.setattr(consumer, "_rebuild_and_reattribute", _fake_rebuild)

    event = Event(
        topic=Topic.IDENTITY_MERGED,
        tenant_id=TENANT,
        source_service="identity",
        payload={
            "primary_entity_id": "survivor-1",
            "secondary_entity_id": "consumed-1",
            "canonical_entity_id": "survivor-1",
        },
    )
    await consumer.on_identity_merged(event)

    profiles = {c[1] for c in calls}
    assert "survivor-1" in profiles, "survivor not recomputed from primary_entity_id"
    assert "consumed-1" in profiles, "consumed profile not recomputed from secondary_entity_id"


async def test_consumer_legacy_keys_still_work(monkeypatch):
    from shared.events.events import Event, Topic
    from services.measurement.identity_consumer import MeasurementIdentityConsumer

    consumer = MeasurementIdentityConsumer(producer=MagicMock())
    calls: list[str] = []

    async def _fake_rebuild(tenant_id, profile_id, reason):
        calls.append(profile_id)

    monkeypatch.setattr(consumer, "_rebuild_and_reattribute", _fake_rebuild)

    event = Event(
        topic=Topic.IDENTITY_MERGED,
        tenant_id=TENANT,
        source_service="identity",
        payload={"surviving_profile_id": "legacy-surv"},
    )
    await consumer.on_identity_merged(event)
    assert calls == ["legacy-surv"]
