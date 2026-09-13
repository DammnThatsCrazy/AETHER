"""W5 registry admin + automated-discovery skeleton — DB-free in-memory run.

Typed repos fall back to shared in-memory stores when no DB pool is configured
(AETHER_ENV=local), so the full unresolved→candidate→verified→active lifecycle
runs without a database. Coverage:

* the four-stage discovery lifecycle on the in-memory repos, including that a
  suggestion NEVER auto-writes and the immutable unresolved observation is kept;
* a resolver seam (the stablecoin canonical-identity seam) surfacing a candidate
  for an unresolved legacy id only once the registry can verify a target;
* an unverifiable reference staying unresolved (never coerced/zeroed/fabricated);
* admin apply registering the alias through the registry with
  execution_by_aether always False, and non-admin actors refused at the facade;
* the admin surface being flag-gated OFF by default (fail-closed 404 for even an
  ADMIN principal) and the apply capability (admin_mode) gating writes.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi import HTTPException

import config.settings as settings_module
from repositories.typed_repo import reset_typed_in_memory_stores
from services.assets import admin_routes
from services.assets.admin import (
    ACTIVE,
    CANDIDATE,
    UNRESOLVED,
    VERIFIED,
    AdminActor,
    AssetDiscoveryPipeline,
    RegistryAdminFacade,
)
from services.assets.models import AssetAlias, CanonicalAsset
from services.assets.registry import UniversalAssetRegistry
from shared.auth.auth import Permissions, Role, TenantContext
from shared.common.common import ForbiddenError

TENANT = "tenant-alpha"


@pytest.fixture(autouse=True)
def _clean_typed_stores():
    reset_typed_in_memory_stores()
    yield
    reset_typed_in_memory_stores()


def _tenant(role: Role = Role.ADMIN, *, user_id: str = "admin@example") -> TenantContext:
    return TenantContext(tenant_id=TENANT, role=role, user_id=user_id)


def _actor(role: Role = Role.ADMIN, *, user_id: str = "admin@example") -> AdminActor:
    return AdminActor.from_tenant(_tenant(role, user_id=user_id))


async def _seeded() -> UniversalAssetRegistry:
    registry = UniversalAssetRegistry()
    await registry.seed_all()
    return registry


async def _recorded_unresolved(registry: UniversalAssetRegistry, raw: str) -> dict:
    return await registry.record_unresolved(
        raw, "unknown_symbol", tenant_id=TENANT,
        evidence={"native": {"amount": "1", "currency": raw}},
    )


# ── unresolved → candidate → verified → active lifecycle ─────────────────────

@pytest.mark.asyncio
async def test_discovery_lifecycle_full_unresolved_to_active_on_inmemory_repos():
    registry = await _seeded()
    pipeline = AssetDiscoveryPipeline(registry=registry)
    await _recorded_unresolved(registry, "ZZZZQ")

    # Stage 1 — unresolved: recorded, explicit, no guessed canonical id.
    unresolved = await pipeline.unresolved_rows(tenant_id=TENANT)
    assert len(unresolved) == 1
    assert unresolved[0]["stage"] == UNRESOLVED
    assert unresolved[0]["raw_reference"] == "ZZZZQ"
    assert unresolved[0]["canonical_asset_id"] is None

    # No candidate while no registry row can verify the reference.
    assert (await pipeline.suggest_candidates(tenant_id=TENANT))["count"] == 0

    # Registry expansion (an explicit admin registration) makes the reference
    # plausibly mappable → the seam now surfaces ONE candidate.
    actor = _actor()
    await RegistryAdminFacade(registry=registry).register_asset(
        actor,
        CanonicalAsset(
            id="crypto:ZZZZQ", kind="crypto", symbol="ZZZZQ",
            name="ZZZZQ Token", display_decimals=8, status="active",
        ),
    )
    suggested = await pipeline.suggest_candidates(tenant_id=TENANT)
    assert suggested["count"] == 1
    candidate = suggested["items"][0]
    assert candidate["stage"] == CANDIDATE
    assert candidate["raw_reference"] == "ZZZZQ"
    assert candidate["canonical_asset_id"] == "crypto:ZZZZQ"
    assert candidate["resolution_method"] == "symbol_verified"

    # Suggestion produced NO auto-write: alias count unchanged and the
    # unresolved observation is still the only recorded row.
    alias_count_before_apply = await registry.aliases.count()
    unresolved_rows = await pipeline.unresolved_rows(tenant_id=TENANT)
    assert len(unresolved_rows) == 1
    assert await registry.aliases.count() == alias_count_before_apply

    # Stage 3 — verified: a human/global-admin confirms the candidate (no write).
    verified = AssetDiscoveryPipeline.confirm(candidate, reviewer=actor.principal)
    assert verified["stage"] == VERIFIED
    assert verified["reviewed_by"] == actor.principal
    assert await registry.aliases.count() == alias_count_before_apply

    # Stage 4 — active: an explicit apply registers the alias through the registry.
    result = await pipeline.apply(verified, actor=actor)
    assert result["stage"] == ACTIVE
    assert result["inserted"] is True
    assert result["execution_by_aether"] is False
    assert result["canonical_asset_id"] == "crypto:ZZZZQ"

    alias = await registry.resolve_alias("zzzzq")
    assert alias is not None
    assert alias["target_asset_id"] == "crypto:ZZZZQ"
    assert alias["verification"] == "verified"
    # The immutable unresolved observation is retained (supersede-by-alias, not deletion).
    assert await registry.unresolved.count() == 1
    assert (await registry.unresolved.find_one({"tenant_id": TENANT}))["execution_by_aether"] is False


@pytest.mark.asyncio
async def test_stablecoin_alias_seam_surfaces_candidate_never_auto_writes():
    # A legacy id observed while the registry held nothing to verify it…
    registry = UniversalAssetRegistry()
    pipeline = AssetDiscoveryPipeline(registry=registry)
    await _recorded_unresolved(registry, "usdc")
    assert (await pipeline.suggest_candidates(tenant_id=TENANT))["count"] == 0
    assert await registry.aliases.count() == 0

    # …becomes mappable once the canonical seed lands its legacy bridge aliases.
    await registry.seed_all()
    suggested = await pipeline.suggest_candidates(tenant_id=TENANT)
    assert suggested["count"] == 1
    candidate = suggested["items"][0]
    assert candidate["stage"] == CANDIDATE
    assert candidate["raw_reference"] == "usdc"
    assert candidate["canonical_asset_id"] == "stablecoin:USDC"
    assert candidate["canonical_deployment_id"] is None
    assert candidate["resolution_method"] == "asset_alias"

    # Surfacing the candidate wrote NOTHING: alias count is exactly the seed's,
    # and running discovery again adds no row.
    alias_count = await registry.aliases.count()
    assert alias_count > 0
    await pipeline.suggest_candidates(tenant_id=TENANT)
    assert await registry.aliases.count() == alias_count
    assert await registry.unresolved.count() == 1


@pytest.mark.asyncio
async def test_unverifiable_ref_stays_unresolved_never_coerced_or_fabricated():
    registry = await _seeded()
    pipeline = AssetDiscoveryPipeline(registry=registry)
    await _recorded_unresolved(registry, "NOTACOINX")

    # No seam maps it → no candidate, stage stays unresolved, no guessed ids.
    assert (await pipeline.suggest_candidates(tenant_id=TENANT))["count"] == 0
    rows = await pipeline.unresolved_rows(tenant_id=TENANT)
    assert len(rows) == 1
    row = rows[0]
    assert row["stage"] == UNRESOLVED
    assert row["canonical_asset_id"] is None
    assert row["canonical_deployment_id"] is None
    assert row["raw_reference"] == "NOTACOINX"

    # The seam itself leaves it unresolved and nothing was registered for it.
    from services.stablecoin.canonical_identity import (
        StablecoinCanonicalIdentityResolver,
    )

    identity = await StablecoinCanonicalIdentityResolver(
        universal_registry=registry,
    ).resolve("NOTACOINX")
    assert identity.resolved is False
    assert identity.canonical_asset_id is None
    assert await registry.resolve_alias("notacoinx") is None
    stored = await registry.unresolved.find_one({"tenant_id": TENANT})
    assert stored["occurrence_count"] == 1
    assert stored["execution_by_aether"] is False


# ── Admin apply: execution_by_aether False; permission-checked writes ────────

@pytest.mark.asyncio
async def test_admin_apply_registers_alias_with_execution_by_aether_false():
    registry = await _seeded()
    facade = RegistryAdminFacade(registry=registry)
    actor = _actor()

    result = await facade.register_alias(
        actor,
        AssetAlias(
            alias="oldbridge",
            target_asset_id="stablecoin:USDC",
            verification="verified",
        ),
        note="reviewed by admin; execution_by_aether=False",
    )
    assert result["inserted"] is True
    assert result["execution_by_aether"] is False
    assert result["applied_by"] == actor.principal

    alias = await registry.resolve_alias("oldbridge")
    assert alias is not None
    assert alias["target_asset_id"] == "stablecoin:USDC"
    assert alias["verification"] == "verified"
    assert "reviewed by admin" in (alias.get("note") or "")


@pytest.mark.asyncio
async def test_admin_writes_require_global_admin_actor():
    registry = await _seeded()
    facade = RegistryAdminFacade(registry=registry)
    viewer = _actor(role=Role.VIEWER, user_id="viewer@example")

    # A viewer (READ-only) is refused at the facade service boundary.
    with pytest.raises(ForbiddenError):
        await facade.register_asset(
            viewer,
            CanonicalAsset(
                id="token:eip155:8453:0xviewer", kind="token",
                symbol="VIEWERCOIN", status="active",
            ),
        )
    with pytest.raises(ForbiddenError):
        await facade.register_alias(
            viewer, {"alias": "viewcoin", "target_asset_id": "stablecoin:USDC"},
        )

    # The discovery pipeline refuses to apply for a non-admin too (verified or not).
    pipeline = AssetDiscoveryPipeline(registry=registry)
    candidate = await pipeline.candidate_for({"raw_reference": "usdc"})
    assert candidate is not None
    verified = AssetDiscoveryPipeline.confirm(candidate, reviewer=viewer.principal)
    with pytest.raises(ForbiddenError):
        await pipeline.apply(verified, actor=viewer)


# ── Flag-gated OFF by default: no admin surface reachable while disabled ─────

class _State:
    pass


class _FakeRequest:
    def __init__(self, tenant: TenantContext) -> None:
        self.state = _State()
        self.state.tenant = tenant


def test_admin_flags_default_off():
    cfg = settings_module.UniversalAssetRegistryConfig()
    assert cfg.admin_enabled is False
    assert cfg.admin_mode is False
    assert settings_module.settings.assets.admin_enabled is False
    assert settings_module.settings.assets.admin_mode is False


def test_admin_gate_fail_closed_when_disabled_and_apply_capability_gates_writes(
    monkeypatch: pytest.MonkeyPatch,
):
    admin_tenant = _tenant()  # global ADMIN — still refused while flag is off.
    request = _FakeRequest(admin_tenant)

    disabled = dataclasses.replace(
        settings_module.settings.assets, admin_enabled=False, admin_mode=False,
    )
    monkeypatch.setattr(settings_module.settings, "assets", disabled)
    with pytest.raises(HTTPException) as exc:
        admin_routes._gate(request)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        admin_routes._gate_apply(request)
    assert exc.value.status_code == 404

    # admin_enabled on but admin_mode (apply capability) still off: reads gate
    # passes; write/apply routes remain inert (404), never reachable.
    review_only = dataclasses.replace(
        settings_module.settings.assets, admin_enabled=True, admin_mode=False,
    )
    monkeypatch.setattr(settings_module.settings, "assets", review_only)
    assert admin_routes._gate(request) == TENANT
    with pytest.raises(HTTPException) as exc:
        admin_routes._gate_apply(request)
    assert exc.value.status_code == 404

    # Both on: the global-ADMIN gate and the apply capability pass.
    enabled = dataclasses.replace(
        settings_module.settings.assets, admin_enabled=True, admin_mode=True,
    )
    monkeypatch.setattr(settings_module.settings, "assets", enabled)
    assert admin_routes._gate(request) == TENANT
    assert admin_routes._gate_apply(request) == TENANT

    # A non-ADMIN principal is refused even when both flags are on.
    viewer_request = _FakeRequest(_tenant(role=Role.VIEWER))
    with pytest.raises(HTTPException) as exc:
        admin_routes._gate(viewer_request)
    assert exc.value.status_code == 403
