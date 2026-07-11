"""Unit tests for fragment-aware identity repair (PR5 slice).

Covers the non-mutating split preview, the three execution modes
(create_new_entity / restore_pre_merge_entity / move_to_existing_entity),
the typed rejections (cross-tenant fragment, campaign-only sameness, identity
cycle), split-event recording, and idempotent-ish re-runs.

Runs entirely against the in-memory backend (AETHER_ENV=local) — no DB, no
Redis, no HTTP server. Follows the reset_in_memory_stores() +
IdentityResolutionRepository() pattern.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

# Stub heavy optional dependencies before imports
_STUBBED: list[str] = []
for _mod in (
    "jwt",
    "cryptography",
    "cryptography.hazmat",
    "cryptography.hazmat.primitives",
    "cryptography.hazmat.primitives.asymmetric",
    "cryptography.hazmat.primitives.asymmetric.ec",
    "cryptography.hazmat.bindings",
    "cryptography.hazmat.bindings._rust",
    "cryptography.hazmat._oid",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
        _STUBBED.append(_mod)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.audit import IdentityAuditWriter  # noqa: E402
from services.identity.conflicts import IdentityConflictManager  # noqa: E402
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.models import (  # noqa: E402
    ConfidenceTier,
    EdgeType,
    EntityType,
    IdentitySignalType,
    SubjectStatus,
)
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402

TENANT = "tenant-frag-1"
ACTOR = "operator-1"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _build_resolver() -> tuple[IdentityResolutionService, IdentityResolutionRepository]:
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    graph_writer = IdentityGraphWriter(repo, metrics)
    audit_writer = IdentityAuditWriter(repo)
    conflict_manager = IdentityConflictManager(repo)
    resolver = IdentityResolutionService(
        repo=repo,
        graph_writer=graph_writer,
        audit_writer=audit_writer,
        conflict_manager=conflict_manager,
        metrics=metrics,
    )
    return resolver, repo


async def _seed_alias(
    repo: IdentityResolutionRepository,
    entity_id: str,
    alias_type: IdentitySignalType = IdentitySignalType.EMAIL_HASH,
    alias_hash: str = "hash-email-1",
    tenant_id: str = TENANT,
) -> dict:
    return await repo.upsert_alias(
        tenant_id=tenant_id,
        canonical_entity_id=entity_id,
        alias_type=alias_type,
        alias_value_hash=alias_hash,
        alias_display_value_redacted="e***@example.com",
        source="seed",
        confidence=1.0,
        confidence_tier=ConfidenceTier.DETERMINISTIC,
    )


async def _seed_observation(
    repo: IdentityResolutionRepository,
    entity_id: str,
    signal_type: IdentitySignalType = IdentitySignalType.EMAIL_HASH,
    signal_hash: str = "hash-email-1",
    tenant_id: str = TENANT,
    event_id: str = "evt-seed-1",
) -> dict:
    return await repo.create_signal_observation(
        tenant_id=tenant_id,
        source_event_id=event_id,
        source_platform="web",
        source_sdk="js",
        signal_type=signal_type,
        signal_value_hash=signal_hash,
        raw_value_redacted="e***@example.com",
        canonical_entity_id=entity_id,
    )


async def _active_alias_ids(
    repo: IdentityResolutionRepository, entity_id: str
) -> list[str]:
    rows = await repo.get_entity_aliases(TENANT, entity_id, include_revoked=False)
    return [r["id"] for r in rows]


# ---------------------------------------------------------------------------
# Preview is non-mutating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_is_non_mutating():
    resolver, repo = _build_resolver()
    source = "entity-src"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    alias = await _seed_alias(repo, source)
    obs = await _seed_observation(repo, source)

    result = await resolver.preview_fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [alias["id"]], "observation_ids": [obs["id"]]},
        mode="create_new_entity",
        actor_id=ACTOR,
        reason="bad merge",
    )

    assert result["allowed"] is True
    assert result["aliases_to_reassign"] == [alias["id"]]
    assert result["observations_to_relink"] == [obs["id"]]

    # Nothing changed: alias still active on source, no split events, no new subjects.
    assert await _active_alias_ids(repo, source) == [alias["id"]]
    reloaded_obs = await repo.get_observation_by_id(obs["id"])
    assert reloaded_obs["canonical_entity_id"] == source
    assert await repo.get_recent_splits(TENANT) == []


# ---------------------------------------------------------------------------
# create_new_entity mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_new_entity_moves_aliases_and_observations():
    resolver, repo = _build_resolver()
    source = "entity-src"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    alias = await _seed_alias(repo, source)
    obs = await _seed_observation(repo, source)

    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [alias["id"]], "observation_ids": [obs["id"]]},
        mode="create_new_entity",
        actor_id=ACTOR,
        reason="split fragment onto new entity",
    )

    assert result["allowed"] is True
    new_entity = result["resulting_entity_id"]
    assert new_entity and new_entity != source

    # Alias moved: source has none active, new entity has one active.
    assert await _active_alias_ids(repo, source) == []
    new_aliases = await repo.get_entity_aliases(TENANT, new_entity)
    assert len(new_aliases) == 1
    assert new_aliases[0]["alias_value_hash"] == "hash-email-1"

    # Observation relinked to the new entity.
    reloaded_obs = await repo.get_observation_by_id(obs["id"])
    assert reloaded_obs["canonical_entity_id"] == new_entity
    assert result["moved_observation_ids"] == [obs["id"]]

    # New subject exists and is active.
    subj = await repo.get_subject_by_canonical_entity_id(TENANT, new_entity)
    assert subj is not None and subj["status"] == SubjectStatus.ACTIVE.value


# ---------------------------------------------------------------------------
# restore_pre_merge_entity mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_pre_merge_entity_mode():
    resolver, repo = _build_resolver()
    pre_merge = "entity-pre-merge"
    survivor = "entity-survivor"
    await repo.create_subject(TENANT, survivor, EntityType.HUMAN)

    # Record the historical merge and tombstone the pre-merge entity into survivor.
    merge_event = await repo.create_merge_event(
        tenant_id=TENANT,
        from_entity_id=pre_merge,
        into_entity_id=survivor,
        resulting_entity_id=survivor,
        confidence=1.0,
        confidence_tier=ConfidenceTier.DETERMINISTIC,
        reason_codes=["manual_operator_merge"],
        source_event_ids=[],
        actor_type="operator",
        actor_id=ACTOR,
    )
    await repo.mark_subject_merged_by_canonical_id(TENANT, pre_merge, survivor)

    alias = await _seed_alias(repo, survivor)

    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=survivor,
        fragments={"alias_ids": [alias["id"]]},
        mode="restore_pre_merge_entity",
        actor_id=ACTOR,
        reason="undo bad merge",
        source_merge_event_id=merge_event["id"],
    )

    assert result["allowed"] is True
    assert result["resulting_entity_id"] == pre_merge

    # Alias reassigned to the restored pre-merge entity; survivor loses it.
    assert await _active_alias_ids(repo, survivor) == []
    restored_aliases = await repo.get_entity_aliases(TENANT, pre_merge)
    assert len(restored_aliases) == 1

    # Pre-merge subject reactivated (tombstone cleared).
    subj = await repo.get_subject_by_canonical_entity_id(TENANT, pre_merge)
    assert subj["status"] == SubjectStatus.ACTIVE.value
    assert subj.get("merged_into_entity_id") is None


@pytest.mark.asyncio
async def test_restore_requires_merge_event():
    resolver, repo = _build_resolver()
    survivor = "entity-survivor"
    await repo.create_subject(TENANT, survivor, EntityType.HUMAN)
    alias = await _seed_alias(repo, survivor)

    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=survivor,
        fragments={"alias_ids": [alias["id"]]},
        mode="restore_pre_merge_entity",
        actor_id=ACTOR,
        reason="undo",
        source_merge_event_id=None,
    )
    assert result["allowed"] is False
    assert result["rejection_reason"] == "source_merge_event_required"


# ---------------------------------------------------------------------------
# move_to_existing_entity mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_to_existing_entity_mode():
    resolver, repo = _build_resolver()
    source = "entity-src"
    target = "entity-target"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    await repo.create_subject(TENANT, target, EntityType.HUMAN)
    alias = await _seed_alias(repo, source)

    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [alias["id"]]},
        mode="move_to_existing_entity",
        actor_id=ACTOR,
        reason="reassign to correct identity",
        target_entity_id=target,
    )

    assert result["allowed"] is True
    assert result["resulting_entity_id"] == target
    assert await _active_alias_ids(repo, source) == []
    assert len(await repo.get_entity_aliases(TENANT, target)) == 1


@pytest.mark.asyncio
async def test_move_to_missing_target_rejected():
    resolver, repo = _build_resolver()
    source = "entity-src"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    alias = await _seed_alias(repo, source)

    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [alias["id"]]},
        mode="move_to_existing_entity",
        actor_id=ACTOR,
        reason="reassign",
        target_entity_id="does-not-exist",
    )
    assert result["allowed"] is False
    assert result["rejection_reason"] == "target_entity_not_found"


# ---------------------------------------------------------------------------
# Typed rejections: cross-tenant, campaign-only sameness, identity cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_fragment_blocked():
    resolver, repo = _build_resolver()
    source = "entity-src"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    # Alias owned by a DIFFERENT tenant.
    foreign_alias = await _seed_alias(repo, "entity-foreign", tenant_id="tenant-other")

    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [foreign_alias["id"]]},
        mode="create_new_entity",
        actor_id=ACTOR,
        reason="split",
    )
    assert result["allowed"] is False
    assert result["rejection_reason"] == "cross_tenant_fragment_blocked"
    assert "cross_tenant_fragment_blocked" in result["reason_codes"]

    # Non-mutating on rejection: foreign alias still active under its tenant.
    foreign_rows = await repo.get_entity_aliases("tenant-other", "entity-foreign")
    assert len(foreign_rows) == 1


@pytest.mark.asyncio
async def test_campaign_only_sameness_blocked():
    resolver, repo = _build_resolver()
    source = "entity-src"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    # Fragment carries ONLY a campaign attribution observation — no identity signal.
    campaign_obs = await _seed_observation(
        repo, source, signal_type=IdentitySignalType.CAMPAIGN_ID, signal_hash="camp-xyz"
    )

    # Preview surfaces the typed rejection without mutating.
    preview = await resolver.preview_fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"observation_ids": [campaign_obs["id"]]},
        mode="create_new_entity",
        actor_id=ACTOR,
        reason="split campaign fragment",
    )
    assert preview["allowed"] is False
    assert preview["rejection_reason"] == "campaign_only_sameness_blocked"

    # Execute is likewise blocked and records no split.
    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"observation_ids": [campaign_obs["id"]]},
        mode="create_new_entity",
        actor_id=ACTOR,
        reason="split campaign fragment",
    )
    assert result["allowed"] is False
    assert result["rejection_reason"] == "campaign_only_sameness_blocked"
    assert await repo.get_recent_splits(TENANT) == []


@pytest.mark.asyncio
async def test_campaign_fragment_with_identity_signal_allowed():
    """A fragment mixing campaign + a real identity signal is NOT campaign-only."""
    resolver, repo = _build_resolver()
    source = "entity-src"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    campaign_obs = await _seed_observation(
        repo, source, signal_type=IdentitySignalType.CAMPAIGN_ID, signal_hash="camp-xyz"
    )
    email_obs = await _seed_observation(
        repo, source, signal_type=IdentitySignalType.EMAIL_HASH,
        signal_hash="hash-email-1", event_id="evt-2",
    )

    result = await resolver.preview_fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"observation_ids": [campaign_obs["id"], email_obs["id"]]},
        mode="create_new_entity",
        actor_id=ACTOR,
        reason="split",
    )
    assert result["allowed"] is True


@pytest.mark.asyncio
async def test_move_to_same_entity_is_identity_cycle():
    resolver, repo = _build_resolver()
    source = "entity-src"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    alias = await _seed_alias(repo, source)

    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [alias["id"]]},
        mode="move_to_existing_entity",
        actor_id=ACTOR,
        reason="oops",
        target_entity_id=source,
    )
    assert result["allowed"] is False
    assert result["rejection_reason"] == "identity_cycle_detected"


@pytest.mark.asyncio
async def test_non_operator_actor_rejected():
    resolver, repo = _build_resolver()
    source = "entity-src"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    alias = await _seed_alias(repo, source)

    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [alias["id"]]},
        mode="create_new_entity",
        actor_id="analyst-1",
        actor_type="system",
        reason="split",
    )
    assert result["allowed"] is False
    assert result["rejection_reason"] == "split_policy_denied"


# ---------------------------------------------------------------------------
# Split-event recording + SAME_AS edge revocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_split_event_recorded_with_fragment_payload():
    resolver, repo = _build_resolver()
    source = "entity-src"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    alias = await _seed_alias(repo, source)

    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [alias["id"]]},
        mode="create_new_entity",
        actor_id=ACTOR,
        reason="record me",
    )
    assert result["split_event_id"]

    splits = await repo.get_split_history(TENANT, source)
    assert len(splits) == 1
    event = splits[0]
    assert event["id"] == result["split_event_id"]
    assert event["mode"] == "create_new_entity"
    assert event["fragment"]["alias_ids"] == [alias["id"]]
    assert event["actor_id"] == ACTOR


@pytest.mark.asyncio
async def test_same_as_edges_revoked_on_move():
    resolver, repo = _build_resolver()
    source = "entity-src"
    target = "entity-target"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    await repo.create_subject(TENANT, target, EntityType.HUMAN)
    alias = await _seed_alias(repo, source)

    # A stale SAME_AS edge between source and target (the bad-merge residue).
    edge = await repo.create_identity_edge(
        tenant_id=TENANT,
        source_entity_id=source,
        target_entity_id=target,
        edge_type=EdgeType.SAME_AS,
        confidence=1.0,
        confidence_tier=ConfidenceTier.DETERMINISTIC,
        reason_codes=["manual_operator_merge"],
        source_event_ids=[],
    )

    result = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [alias["id"]]},
        mode="move_to_existing_entity",
        actor_id=ACTOR,
        reason="split + revoke edge",
        target_entity_id=target,
    )
    assert result["allowed"] is True
    assert edge["id"] in result["revoked_edge_ids"]

    reloaded = await repo.revoke_identity_edge(edge["id"])  # idempotent read of state
    assert reloaded["revoked_at"] is not None


# ---------------------------------------------------------------------------
# Idempotent-ish: re-running never leaves duplicate active aliases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rerun_does_not_duplicate_active_aliases():
    resolver, repo = _build_resolver()
    source = "entity-src"
    await repo.create_subject(TENANT, source, EntityType.HUMAN)
    alias = await _seed_alias(repo, source)

    first = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [alias["id"]]},
        mode="create_new_entity",
        actor_id=ACTOR,
        reason="first",
    )
    assert first["allowed"] is True
    assert first["moved_alias_ids"]

    # Re-run with the (now revoked) original alias id: nothing new moves.
    second = await resolver.fragment_split(
        tenant_id=TENANT,
        entity_id=source,
        fragments={"alias_ids": [alias["id"]]},
        mode="create_new_entity",
        actor_id=ACTOR,
        reason="second",
    )
    assert second["allowed"] is True
    assert second["moved_alias_ids"] == []

    # Exactly one active alias with that hash across the whole tenant.
    active = await repo.find_aliases_by_signal(TENANT, IdentitySignalType.EMAIL_HASH, "hash-email-1")
    assert len(active) == 1


# ---------------------------------------------------------------------------
# Route-level: permission gating
# ---------------------------------------------------------------------------


class _PermTenant:
    def __init__(self, permissions):
        self.tenant_id = TENANT
        self.user_id = ACTOR
        self.permissions = set(permissions)

    def require_permission(self, perm: str) -> None:
        from shared.common.common import ForbiddenError
        if perm not in self.permissions and "admin" not in self.permissions:
            raise ForbiddenError(f"Missing permission: {perm}")


class _PermRequest:
    def __init__(self, permissions):
        self.state = MagicMock()
        self.state.tenant = _PermTenant(permissions)


@pytest.mark.asyncio
async def test_execute_requires_write_permission(monkeypatch):
    from shared.common.common import ForbiddenError
    from services.identity import routes
    from services.identity.schemas import IdentityFragmentSplitRequest

    resolver, _ = _build_resolver()
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)

    body = IdentityFragmentSplitRequest(
        entity_id="entity-src", fragments={"alias_ids": ["a"]},
        mode="create_new_entity", reason="x",
    )
    read_only = _PermRequest({"read"})
    with pytest.raises(ForbiddenError):
        await routes.execute_fragment_split(body, read_only)


@pytest.mark.asyncio
async def test_preview_route_returns_envelope(monkeypatch):
    from services.identity import routes
    from services.identity.schemas import IdentitySplitPreviewRequest

    resolver, repo = _build_resolver()
    await repo.create_subject(TENANT, "entity-src", EntityType.HUMAN)
    alias = await _seed_alias(repo, "entity-src")
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)

    body = IdentitySplitPreviewRequest(
        entity_id="entity-src", fragments={"alias_ids": [alias["id"]]},
        mode="create_new_entity", reason="preview",
    )
    response = await routes.preview_fragment_split(body, _PermRequest({"read"}))
    assert "data" in response
    assert response["data"]["allowed"] is True
    assert response["data"]["aliases_to_reassign"] == [alias["id"]]


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def cleanup_stubs():
    yield
    for mod in _STUBBED:
        sys.modules.pop(mod, None)
