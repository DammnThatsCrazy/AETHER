"""Typed repositories for event-time valuation persistence (services/valuation).

Alembic-owned tables from migration 20260902_event_time_valuation. One
TypedTableRepository subclass per table, mirroring the registry / stablecoin
typed-repo pattern (repositories/registry_repos.py): class attrs
``table_name``/``columns`` (REAL typed column names), ``jsonb_columns`` and
``conflict_key``.

Domain posture (house rules):
  - ``valuation_price_observations`` is GLOBAL append-only (NO tenant_id) —
    prices are objective market facts. ``observation_id`` is the deterministic
    content-hash natural key, so a replay of an identical fact is an idempotent
    no-op (ON CONFLICT (observation_id) DO NOTHING).
  - ``valuation_snapshots`` is tenant-scoped append-only immutable: conflict on
    (tenant_id, idempotency_key); execution_by_aether always False; evidence
    JSONB. Corrections APPEND a new superseding row and only ever update the
    back-pointer/status columns via ``mark_superseded`` (never the economic
    fact columns). Fact-table writes go through ``insert``; ``update_by_key`` is
    reserved for the immutability carve-out columns.
  - ``tenant_value_policies`` is mutable current-state config (one row per
    tenant): updates go through ``update_by_key``; first write inserts.

In-memory fallback is used under AETHER_ENV=local (no DB pool), so every one of
these repositories is DB-free testable.
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.typed_repo import TypedTableRepository


class ValuationPriceObservationRepo(TypedTableRepository):
    """Global append-only market price observations (no tenant_id)."""

    table_name = "valuation_price_observations"
    columns = (
        "observation_id",
        "asset_id",
        "deployment_id",
        "provider",
        "quote_asset_id",
        "price",
        "observed_at",
        "source",
        "source_record_id",
        "freshness_window_seconds",
        "received_at",
        "data",
    )
    jsonb_columns = frozenset({"data"})
    # observation_id is the deterministic natural-key content hash -> replay of
    # an identical fact collides here and is an idempotent no-op.
    conflict_key = ("observation_id",)

    async def update_by_key(self, key_filters: dict, changes: dict) -> bool:
        """Observations are immutable market facts — append-only, no carve-out.

        Any attempt to rewrite an existing observation (price, observed_at,
        provenance, …) is refused at the repository layer; a correction is a
        NEW observation appended through ``insert``/``observe_price``.
        """
        raise ValueError(
            "valuation_price_observations is append-only: observations are "
            "immutable and must not be updated in place; append a corrected "
            "observation instead"
        )

    async def lookup_candidates(
        self,
        asset_id: str,
        provider: str,
        *,
        deployment_id: Optional[str] = None,
        limit: int = 5000,
    ) -> list[dict]:
        """Most-recent-first candidate rows for ``(asset_id[, deployment_id],
        provider)``. Time filtering is applied by the caller (the store adapter)
        so the engine's ``observed_at <= effective_at`` cut is authoritative."""
        filters: dict[str, Any] = {"asset_id": asset_id, "provider": provider}
        if deployment_id is not None:
            filters["deployment_id"] = deployment_id
        return await self.find_many(
            filters, limit=limit, order_by="observed_at", descending=True,
        )


class ValuationSnapshotRepo(TypedTableRepository):
    """Tenant-scoped append-only immutable valuation snapshots."""

    table_name = "valuation_snapshots"
    columns = (
        "valuation_id",
        "tenant_id",
        "idempotency_key",
        "canonical_asset_id",
        "deployment_id",
        "economic_role",
        "native_amount",
        "native_currency",
        "reporting_asset_id",
        "reporting_amount",
        "valuation_basis",
        "price_status",
        "valuation_method",
        "provider",
        "conversion_refs",
        "evidence",
        "registry_version",
        "policy_version",
        "price_observation_ids",
        "supersedes_snapshot_id",
        "superseded_by_snapshot_id",
        "status",
        "computed_at",
        "effective_at",
        "execution_by_aether",
        "data",
    )
    jsonb_columns = frozenset({
        "conversion_refs", "evidence", "price_observation_ids", "data",
    })
    conflict_key = ("tenant_id", "idempotency_key")
    # Immutability carve-out: the ONLY columns a persisted snapshot may ever
    # change are the supersede back-pointer + status (a correction appends a
    # new snapshot; it never rewrites an economic fact in place).
    _IMMUTABILITY_CARVE_OUT = frozenset({"status", "superseded_by_snapshot_id"})

    async def update_by_key(self, key_filters: dict, changes: dict) -> bool:
        """Refuse any in-place change outside the immutability carve-out.

        ``valuation_snapshots`` are immutable economic facts. Generic mutation
        is blocked here so no caller (present or future) can silently rewrite
        reporting_amount / price_status / …; only ``mark_superseded`` may flip a
        current snapshot to ``superseded`` by keying on its real identity.
        """
        illegal = set(changes) - self._IMMUTABILITY_CARVE_OUT
        if illegal:
            raise ValueError(
                "valuation_snapshots are immutable: refusing to update columns "
                f"{sorted(illegal)} — only the carve-out columns "
                f"{sorted(self._IMMUTABILITY_CARVE_OUT)} may change, via "
                "mark_superseded (corrections APPEND a new snapshot)"
            )
        if set(key_filters) != {"tenant_id", "valuation_id"}:
            raise ValueError(
                "snapshot updates must key on exactly {tenant_id, valuation_id}"
            )
        return await super().update_by_key(key_filters, changes)

    async def find_current_for_asset(
        self,
        tenant_id: str,
        canonical_asset_id: str,
        *,
        limit: int = 100,
    ) -> list[dict]:
        """Most-recent-first current snapshots for a tenant + canonical asset."""
        return await self.find_many(
            {
                "tenant_id": tenant_id,
                "canonical_asset_id": canonical_asset_id,
                "status": "current",
            },
            limit=limit,
            order_by="effective_at",
            descending=True,
        )

    async def mark_superseded(
        self,
        tenant_id: str,
        valuation_id: str,
        superseded_by_snapshot_id: str,
    ) -> bool:
        """Immutable-fact carve-out: flip one snapshot to ``superseded`` and set
        its correction back-pointer. NEVER touches the economic fact columns.
        Refuses to supersede a snapshot that is not currently ``current`` (a
        row can be superseded exactly once, by its real correction)."""
        if valuation_id == superseded_by_snapshot_id:
            raise ValueError("a snapshot cannot supersede itself")
        existing = await self.find_one({
            "tenant_id": tenant_id, "valuation_id": valuation_id,
        })
        if existing is None:
            raise ValueError(
                f"snapshot {valuation_id!r} of tenant {tenant_id!r} not found"
            )
        if existing.get("status") != "current":
            raise ValueError(
                f"snapshot {valuation_id!r} is not current (status="
                f"{existing.get('status')!r}) — only a current snapshot may be "
                "superseded"
            )
        return await self.update_by_key(
            {"tenant_id": tenant_id, "valuation_id": valuation_id},
            {
                "status": "superseded",
                "superseded_by_snapshot_id": superseded_by_snapshot_id,
            },
        )


class TenantValuePolicyRepo(TypedTableRepository):
    """Mutable current-state per-tenant reporting policy (one row per tenant)."""

    table_name = "tenant_value_policies"
    columns = (
        "tenant_id",
        "policy_version",
        "reporting_asset_id",
        "allowed_reporting_asset_ids",
        "provider_chain_policy",
        "stale_threshold_seconds",
        "fallback_allowed",
        "data",
    )
    jsonb_columns = frozenset({"allowed_reporting_asset_ids", "data"})
    conflict_key = ("tenant_id",)
