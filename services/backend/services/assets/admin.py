"""Registry-admin facade + automated-discovery pipeline (W5, C5-ADMIN).

Wave-5 registry-admin surface for the universal asset registry
(services/assets). Two additive, observation-only building blocks sit on top of
the existing ``UniversalAssetRegistry``:

  1. ``RegistryAdminFacade`` — a thin, permission-checked service facade for
     *review-and-apply* of canonical reference data (register asset / chain /
     fiat / deployment / alias + reference reads). These are data-integrity
     operations. Aether records canonical reference data; it NEVER originates,
     signs, or settles a transfer. ``execution_by_aether`` stays False
     everywhere, and applied rows are written only when a global-ADMIN actor
     explicitly posts them (human apply — nothing is auto-applied).

  2. ``AssetDiscoveryPipeline`` — an automated-discovery SKELETON implementing
     the lifecycle ``unresolved → candidate → verified → active``:

       unresolved = rows the registry already records through
                    ``record_unresolved`` (registry_unresolved_asset_refs)
       candidate  = an unresolved reference a resolver seam can now plausibly
                    map (the stablecoin canonical-identity seam is consulted
                    here); produced as a *suggestion* — never auto-written
       verified   = a human / global-admin confirms the candidate mapping
       active     = the verified mapping is applied through the admin facade as
                    an alias/registration (explicit human apply)

     The skeleton lives entirely on existing tables
     (registry_assets / registry_asset_aliases / registry_unresolved_asset_refs)
     plus the typed in-memory repositories under AETHER_ENV=local — there is NO
     new Alembic migration, and candidate/verified state is derived in-service
     (not persisted) precisely so nothing auto-advances past the human gate.
     It is honest scaffolding: it surfaces suggested mappings for a human to
     review; it does not fabricate identity, coerce an unknown reference, or
     register anything on its own.

Gating / honest scope: this module defines no FastAPI surface. The router
(``admin_routes.py``) mounts behind ``settings.assets.admin_enabled`` (default
OFF) and every route is global-ADMIN gated; facade methods re-check the actor
permission at the service boundary so callers cannot bypass the gate. None of
this behavior is lending, underwriting, or execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.auth.auth import Permissions
from shared.common.common import ForbiddenError
from services.assets.models import (
    AssetAlias,
    AssetDeployment,
    CanonicalAsset,
    ChainReference,
    FiatCurrencyMetadata,
)
from services.assets.registry import UniversalAssetRegistry

# Sentinel tenant for platform-scope review of observational unresolved rows
# (matches the registry's own tenant-less sighting attribution).
_PLATFORM_TENANT = "platform"

# ── Discovery lifecycle stages ────────────────────────────────────────────────
UNRESOLVED = "unresolved"
CANDIDATE = "candidate"
VERIFIED = "verified"
ACTIVE = "active"
DISCOVERY_STAGES = (UNRESOLVED, CANDIDATE, VERIFIED, ACTIVE)


class AdminActor:
    """Service-layer identity for one registry-admin action.

    A route constructs an ``AdminActor`` only AFTER its global-ADMIN gate has
    passed and passes it into facade/pipeline methods, which re-check at the
    service boundary (defense in depth): service methods stay permission-checked
    even if a future caller forgets the route gate.

    The wrapped ``tenant`` exposes the repo-standard authorization surface —
    ``tenant_id`` plus ``require_permission``/``has_permission`` (e.g.
    ``shared.auth.auth.TenantContext``). ``principal`` is the audit label
    recorded on applied reference-data rows / discovery confirmations.
    """

    def __init__(
        self,
        tenant: Any,
        *,
        principal: Optional[str] = None,
    ) -> None:
        if tenant is None:
            raise ValueError("AdminActor requires an authenticated tenant context")
        self.tenant = tenant
        self.principal = (
            principal
            or getattr(tenant, "user_id", None)
            or getattr(tenant, "tenant_id", None)
            or _PLATFORM_TENANT
        )

    @classmethod
    def from_tenant(cls, tenant: Any) -> "AdminActor":
        return cls(tenant)

    @property
    def tenant_id(self) -> str:
        return getattr(self.tenant, "tenant_id", None) or _PLATFORM_TENANT

    def authorize(self, permission: str = Permissions.ADMIN) -> "AdminActor":
        """Fail-closed permission re-check at the service boundary."""
        require = getattr(self.tenant, "require_permission", None)
        if require is None:
            raise ForbiddenError(
                f"Missing permission: {permission} (no tenant authorization surface)"
            )
        try:
            require(permission)
        except ForbiddenError:
            raise
        except Exception as exc:  # typed and untyped permission adapters
            raise ForbiddenError(str(exc)) from exc
        return self


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _observation_only(result: dict[str, Any], actor: AdminActor) -> dict[str, Any]:
    """Annotate a registry write result with the observation-only invariant.

    Reference-data rows carry no execution column; the marker is recorded on the
    result + applied-by audit label so callers can prove the write was an
    observe/record action, never an execution_by_aether=True one.
    """
    out = dict(result)
    out["execution_by_aether"] = False
    out["applied_by"] = actor.principal
    return out


class RegistryAdminFacade:
    """Thin, permission-checked facade over the UniversalAssetRegistry.

    Every method authorizes a global-ADMIN actor and then either reads registry
    reference data or applies an explicitly-posted reference-data write through
    the existing registry facade. This facade adds review ergonomics and audit
    labels; it never re-implements registry logic and never executes anything.
    """

    def __init__(self, registry: Optional[UniversalAssetRegistry] = None) -> None:
        self.registry = registry or UniversalAssetRegistry()

    # ── reference reads (global-ADMIN review) ─────────────────────────────

    async def status(self, actor: AdminActor) -> dict[str, Any]:
        actor.authorize(Permissions.ADMIN)
        meta = await self.registry.get_meta()
        return {
            "registry_version": self.registry.current_registry_version(),
            "ledger": meta,
            "asset_count": await self.registry.assets.count(),
            "chain_count": await self.registry.chains.count(),
            "deployment_count": await self.registry.deployments.count(),
            "fiat_count": await self.registry.fiats.count(),
            "alias_count": await self.registry.aliases.count(),
            "unresolved_count": await self.registry.unresolved.count(),
            "observation_only": True,
            "execution_by_aether": False,
        }

    async def get_asset(self, actor: AdminActor, asset_id: str) -> Optional[dict]:
        actor.authorize(Permissions.ADMIN)
        return await self.registry.get_asset(asset_id)

    async def list_assets(
        self,
        actor: AdminActor,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        actor.authorize(Permissions.ADMIN)
        return await self.registry.assets.find_many(limit=limit, offset=offset)

    async def list_aliases(
        self,
        actor: AdminActor,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        actor.authorize(Permissions.ADMIN)
        return await self.registry.aliases.find_many(limit=limit, offset=offset)

    async def list_unresolved(
        self,
        actor: AdminActor,
        *,
        tenant_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Tenant-scoped review of recorded unresolved references.

        Unresolved rows are tenant-scoped observations; a review is always
        scoped to one tenant (platform sentinel when the caller names none) so
        the admin surface never silently enumerates another tenant's sightings.
        """
        actor.authorize(Permissions.ADMIN)
        scope = tenant_id or _PLATFORM_TENANT
        rows = await self.registry.unresolved.find_many(
            {"tenant_id": scope}, limit=limit, offset=offset,
        )
        return {"scope": scope, "items": rows, "count": len(rows)}

    # ── reference-data apply (explicit human/global-admin posts only) ──────

    async def register_asset(
        self, actor: AdminActor, payload: CanonicalAsset | dict,
    ) -> dict[str, Any]:
        actor.authorize(Permissions.ADMIN)
        result = await self.registry.register_asset(payload)
        return _observation_only(result, actor)

    async def register_chain(
        self, actor: AdminActor, payload: ChainReference | dict,
    ) -> dict[str, Any]:
        actor.authorize(Permissions.ADMIN)
        result = await self.registry.register_chain(payload)
        return _observation_only(result, actor)

    async def register_fiat(
        self, actor: AdminActor, payload: FiatCurrencyMetadata | dict,
    ) -> dict[str, Any]:
        actor.authorize(Permissions.ADMIN)
        result = await self.registry.register_fiat(payload)
        return _observation_only(result, actor)

    async def register_deployment(
        self, actor: AdminActor, payload: AssetDeployment | dict,
    ) -> dict[str, Any]:
        actor.authorize(Permissions.ADMIN)
        result = await self.registry.register_deployment(payload)
        return _observation_only(result, actor)

    async def register_alias(
        self,
        actor: AdminActor,
        payload: AssetAlias | dict,
        *,
        note: Optional[str] = None,
    ) -> dict[str, Any]:
        """Apply one legacy alias -> canonical target mapping.

        The mapping is written through the registry (idempotent upsert on the
        lowercased alias). ``execution_by_aether`` is always False; the apply is
        reference data recorded by Aether, never an executed transfer.
        """
        actor.authorize(Permissions.ADMIN)
        record = (
            dict(payload)
            if isinstance(payload, dict)
            else AssetAlias.model_validate(payload).model_dump(exclude_none=True)
        )
        if note:
            record["note"] = note
        record.setdefault(
            "note",
            f"registry-admin review-and-apply by {actor.principal}; "
            "execution_by_aether=False",
        )
        result = await self.registry.register_alias(record)
        return _observation_only(result, actor)


class AssetDiscoveryPipeline:
    """Automated-discovery SKELETON: unresolved → candidate → verified → active.

    The pipeline READS recorded unresolved references, RUNS resolver seams to
    produce candidate mappings a human may confirm, and only ever writes when a
    human/global-admin applies a VERIFIED mapping through the admin facade. No
    step auto-writes a registration, coerces an unknown reference, or deletes
    the immutable unresolved observation.
    """

    def __init__(
        self,
        registry: Optional[UniversalAssetRegistry] = None,
        facade: Optional[RegistryAdminFacade] = None,
    ) -> None:
        self.registry = registry or UniversalAssetRegistry()
        self.facade = facade or RegistryAdminFacade(self.registry)

    # ── stage: unresolved ────────────────────────────────────────────────

    async def unresolved_rows(
        self,
        *,
        tenant_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Recorded unresolved references (stage ``unresolved``), tenant-scoped.

        Each row is annotated with the empty canonical-mapping fields the later
        stages fill in, so the lifecycle reads cleanly end-to-end.
        """
        scope = tenant_id or _PLATFORM_TENANT
        rows = await self.registry.unresolved.find_many(
            {"tenant_id": scope}, limit=limit, offset=offset,
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["stage"] = UNRESOLVED
            item["canonical_asset_id"] = None
            item["canonical_deployment_id"] = None
            item["resolution_method"] = None
            out.append(item)
        return out

    # ── stage: candidate ──────────────────────────────────────────────────

    async def candidate_for(self, unresolved_row: dict[str, Any]) -> Optional[dict]:
        """Produce ONE suggested mapping for an unresolved reference, or None.

        A candidate exists only when a resolver seam can now *plausibly* map the
        unresolved reference to canonical identity. The stablecoin
        canonical-identity seam is consulted (it reads alias rows, registered
        asset/deployment rows and exactly-one symbol matches — all against this
        registry); a reference no seam can map today yields NO candidate and
        stays unresolved. Never guessed, never auto-written.
        """
        raw = (unresolved_row or {}).get("raw_reference")
        if not raw:
            return None
        from services.stablecoin.canonical_identity import (
            StablecoinCanonicalIdentityResolver,
        )

        identity = await StablecoinCanonicalIdentityResolver(
            universal_registry=self.registry,
        ).resolve(str(raw))
        if not identity.resolved:
            return None
        # An alias mapping needs an anchored canonical asset; a deployment-only
        # echo with no asset anchor is not a mapping we can apply.
        if not identity.canonical_asset_id:
            return None
        return {
            "stage": CANDIDATE,
            "raw_reference": str(raw),
            "tenant_id": unresolved_row.get("tenant_id"),
            "unresolved_reason": unresolved_row.get("reason"),
            "canonical_asset_id": identity.canonical_asset_id,
            "canonical_deployment_id": identity.canonical_deployment_id,
            "resolution_method": identity.resolution_method,
            "suggestion_kind": "alias",
            "registry_version": identity.registry_version,
        }

    async def suggest_candidates(
        self,
        *,
        tenant_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Run every tenant-scoped unresolved reference through the seam.

        Returns suggested candidate mappings ONLY — the pipeline never applies
        them. Each candidate requires a human/global-admin confirm (verified)
        and an explicit apply (active) before any row is written.
        """
        items: list[dict[str, Any]] = []
        for row in await self.unresolved_rows(
            tenant_id=tenant_id, limit=limit, offset=offset,
        ):
            candidate = await self.candidate_for(row)
            if candidate is not None:
                items.append(candidate)
        return {
            "items": items,
            "count": len(items),
            "note": (
                "candidates are suggestions for a human/global-admin to "
                "confirm and apply; nothing is auto-registered"
            ),
        }

    # ── stage: verified (human confirm, no write) ─────────────────────────

    @staticmethod
    def confirm(
        candidate: dict[str, Any],
        *,
        reviewer: str,
        reviewed_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Mark a candidate as confirmed by a human / global-admin.

        Pure, non-persisted transition: ``verified`` still requires an explicit
        ``apply`` before anything is written. Nothing is stored here — the
        confirm gate is a human decision the caller carries to apply.
        """
        if (candidate or {}).get("stage") != CANDIDATE:
            raise ValueError("only a candidate may be confirmed (stage=verified)")
        out = dict(candidate)
        out["stage"] = VERIFIED
        out["reviewed_by"] = reviewer
        out["reviewed_at"] = reviewed_at or _utc_now_iso()
        return out

    # ── stage: active (explicit human apply, writes through the facade) ───

    async def apply(
        self,
        verified: dict[str, Any],
        *,
        actor: AdminActor,
    ) -> dict[str, Any]:
        """Apply a VERIFIED mapping as an alias row (stage ``active``).

        Writes happen ONLY here and ONLY for a human/global-admin-confirmed
        mapping; the write is an idempotent alias registration through the
        registry (execution_by_aether False). The unresolved observation that
        originally recorded the sighting is immutable and is left in place —
        the new alias lets future references resolve.
        """
        if (verified or {}).get("stage") != VERIFIED:
            raise ValueError(
                "only a VERIFIED mapping may be applied (unresolved->candidate->"
                "verified->active); a human/global-admin must confirm first"
            )
        actor.authorize(Permissions.ADMIN)
        reviewer = verified.get("reviewed_by") or actor.principal
        note = (
            "automated-discovery active mapping "
            f"(stage={ACTIVE}, reviewer={reviewer}); execution_by_aether=False"
        )
        result = await self.facade.register_alias(
            actor,
            {
                "alias": verified["raw_reference"],
                "target_asset_id": verified["canonical_asset_id"],
                "target_deployment_id": verified.get("canonical_deployment_id"),
                "verification": "verified",
            },
            note=note,
        )
        out = dict(result)
        out["stage"] = ACTIVE
        out["reviewed_by"] = reviewer
        out["canonical_asset_id"] = verified["canonical_asset_id"]
        out["canonical_deployment_id"] = verified.get("canonical_deployment_id")
        return out
