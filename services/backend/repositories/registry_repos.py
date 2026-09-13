"""Typed repositories for the universal asset registry (services/assets).

Alembic-owned tables from migration 20260902_universal_asset_registry. One
TypedTableRepository subclass per table, mirroring the stablecoin typed repos
(repositories/stablecoin_repos.py — StablecoinAssetRepo / StablecoinDeploymentRepo
style): class attrs ``table_name``/``columns`` (REAL typed column names),
``jsonb_columns`` and ``conflict_key``. Global reference tables carry NO
tenant_id; the single tenant-scoped observational table
(registry_unresolved_asset_refs) carries the observational house rules
(execution_by_aether=False fail-closed, evidence JSONB, UNIQUE
(tenant_id, idempotency_key)).

Writes go through TypedTableRepository.insert(record) -> bool which is
INSERT .. ON CONFLICT (conflict_key) DO NOTHING, so register/upsert is
idempotent on canonical identity. Only current-state tables use
update_by_key; immutable registry rows are never mutated except status /
timestamp columns where the caller explicitly allows it.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from repositories.typed_repo import TypedTableRepository


class RegistryAssetRepo(TypedTableRepository):
    """Global reference table — canonical assets (no tenant_id)."""

    table_name = "registry_assets"
    columns = (
        "asset_id",
        "kind",
        "symbol",
        "name",
        "issuer",
        "display_decimals",
        "status",
        "data",
    )
    jsonb_columns = frozenset({"data"})
    conflict_key = ("asset_id",)


class RegistryChainRepo(TypedTableRepository):
    """Global reference table — registered chains (CAIP-2 chain_id)."""

    table_name = "registry_chains"
    columns = (
        "chain_id",
        "name",
        "network",
        "status",
        "vm",
        "native_currency",
        "first_seen_at",
        "last_seen_at",
        "deprecated_at",
        "data",
    )
    jsonb_columns = frozenset({"data"})
    conflict_key = ("chain_id",)


class RegistryFiatCurrencyRepo(TypedTableRepository):
    """Global reference table — ISO 4217 fiat metadata rows."""

    table_name = "registry_fiat_currencies"
    columns = (
        "iso_code",
        "numeric_code",
        "minor_units",
        "name",
        "symbol",
        "data",
    )
    jsonb_columns = frozenset({"data"})
    conflict_key = ("iso_code",)


class RegistryDeploymentRepo(TypedTableRepository):
    """Global reference table — per-chain / per-mint asset deployments."""

    table_name = "registry_asset_deployments"
    columns = (
        "deployment_id",
        "asset_id",
        "chain_id",
        "contract_or_mint",
        "decimals",
        "canonical_vs_bridged",
        "deployment_status",
        "token_standard",
        "first_seen_at",
        "last_seen_at",
        "deprecated_at",
        "data",
    )
    jsonb_columns = frozenset({"data"})
    conflict_key = ("deployment_id",)


class RegistryAliasRepo(TypedTableRepository):
    """Global reference table — legacy alias -> canonical target rows."""

    table_name = "registry_asset_aliases"
    columns = (
        "alias",
        "target_asset_id",
        "target_deployment_id",
        "verification",
        "first_seen_at",
        "last_seen_at",
        "note",
        "data",
    )
    jsonb_columns = frozenset({"data"})
    conflict_key = ("alias",)


class RegistryCapabilityRepo(TypedTableRepository):
    """Global reference table — support-capability claims.

    capability_id is a deterministic sha256 over the subject (asset_id /
    deployment_id, either may be null) + capability, so one subject+capability
    always collides on the PK (Postgres UNIQUE treats NULLs as distinct, so a
    composite UNIQUE over nullable columns would not dedupe).
    """

    table_name = "registry_asset_capabilities"
    columns = (
        "capability_id",
        "asset_id",
        "deployment_id",
        "capability",
        "data",
    )
    jsonb_columns = frozenset({"data"})
    conflict_key = ("capability_id",)

    @staticmethod
    def capability_key(
        capability: str,
        asset_id: Optional[str] = None,
        deployment_id: Optional[str] = None,
    ) -> str:
        basis = "|".join([
            asset_id or "",
            deployment_id or "",
            capability,
        ])
        return "cap:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


class RegistryUnresolvedAssetRepo(TypedTableRepository):
    """Tenant-scoped observational table — recorded unresolved references.

    One aggregation row per (tenant_id, raw_reference); sighting the same raw
    reference again bumps occurrence_count / last_seen_at rather than
    appending a duplicate (see ``record_unresolved``). Observational house
    rules apply: execution_by_aether is always False and evidence is optional.
    """

    table_name = "registry_unresolved_asset_refs"
    columns = (
        "tenant_id",
        "reference_id",
        "raw_reference",
        "reason",
        "occurrence_count",
        "first_seen_at",
        "last_seen_at",
        "idempotency_key",
        "evidence",
        "execution_by_aether",
    )
    jsonb_columns = frozenset({"evidence"})
    conflict_key = ("tenant_id", "idempotency_key")

    @staticmethod
    def reference_id(tenant_id: str, raw_reference: str) -> str:
        basis = f"{tenant_id}\x00{raw_reference}"
        return "unresolved:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def idempotency_key(tenant_id: str, raw_reference: str) -> str:
        basis = f"{tenant_id}\x00{raw_reference}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    async def record_unresolved(
        self,
        *,
        tenant_id: str,
        raw_reference: str,
        reason: str,
        evidence: Optional[dict[str, Any]] = None,
        seen_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record (or bump) one unresolved reference sighting.

        Returns an ``{inserted, occurrence_count, first_seen_at,
        last_seen_at}`` summary. Re-seen references aggregate in place — they
        are current-state sightings, not append-only immutable facts.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for an unresolved reference record")
        now = seen_at or _utc_now_iso()
        existing = await self.find_one({
            "tenant_id": tenant_id,
            "raw_reference": raw_reference,
        })
        if existing is not None:
            next_count = int(existing.get("occurrence_count") or 1) + 1
            await self.update_by_key(
                {"tenant_id": tenant_id, "raw_reference": raw_reference},
                {"occurrence_count": next_count, "last_seen_at": now},
            )
            return {
                "inserted": False,
                "occurrence_count": next_count,
                "first_seen_at": existing.get("first_seen_at") or now,
                "last_seen_at": now,
            }
        record = {
            "tenant_id": tenant_id,
            "reference_id": self.reference_id(tenant_id, raw_reference),
            "raw_reference": raw_reference,
            "reason": reason,
            "occurrence_count": 1,
            "first_seen_at": now,
            "last_seen_at": now,
            "idempotency_key": self.idempotency_key(tenant_id, raw_reference),
            "evidence": evidence,
            "execution_by_aether": False,
        }
        inserted = await self.insert(record)
        return {
            "inserted": inserted,
            "occurrence_count": 1,
            "first_seen_at": now,
            "last_seen_at": now,
        }


class RegistryMetaRepo(TypedTableRepository):
    """Global single-row ledger — deterministic registry_version.

    Rows are keyed by meta_id (the seeder writes one row, ``"registry"``). The
    version is a deterministic sha256 over the sorted canonical seed keys —
    never a wall-clock timestamp — so identical registry states always share
    one version (financial-normalization §6 / §10).
    """

    table_name = "registry_meta"
    columns = (
        "meta_id",
        "registry_version",
        "algorithm",
        "asset_count",
        "chain_count",
        "deployment_count",
        "fiat_count",
        "alias_count",
        "data",
    )
    jsonb_columns = frozenset({"data"})
    conflict_key = ("meta_id",)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
