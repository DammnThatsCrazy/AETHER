"""High-level valuation orchestration — canonicalize → observe → value → persist.

Sits above the W2 pure engine (services/valuation/engine.py) and the concrete
Wave-3 adapters (services/valuation/adapters.py). It is PURE OF HTTP: routes
call these methods and translate failures; nothing here reads a request or
raises an HTTP status.

Flow (``value_and_persist``):
  1. read the tenant's current value policy (tenant_value_policies) if present;
  2. canonicalize the native payload through the real registry (RegistryPort
     adapter) and read/ensure price observations (ObservationStorePort adapter);
  3. run the pure ``engine.value_at`` -> a ValuationSnapshot whose valuation_id
     is a deterministic content hash (identical inputs at the same effective_at
     reproduce the same id);
  4. persist a tenant valuation_snapshot with APPEND semantics — a correction
     that supplies ``supersedes_snapshot_id`` records a NEW superseding snapshot
     and flips the prior snapshot's status to ``superseded`` (the economic fact
     is never updated in place); execution_by_aether is always False.

House rules: reporting currency is a canonical asset id (never a bare symbol),
reporting_amount NULL means UNAVAILABLE (never coerced to 0), all amounts are
Decimal / decimal strings (floats rejected by the contract validators), and
this service only ever OBSERVES — it never originates or settles a transfer.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Mapping, Optional

from services.assets.registry import UniversalAssetRegistry
from services.valuation.adapters import (
    ValuationObservationStore,
    ValuationRegistryPort,
)
from services.valuation.engine import value_at
from services.valuation.ingest import observe_price
from services.valuation.models import (
    MarketPriceObservation,
    TenantValuePolicy,
    ValuationSnapshot,
)
from services.valuation.price_providers import USD_ASSET_ID
from services.valuation.repositories import (
    TenantValuePolicyRepo,
    ValuationPriceObservationRepo,
    ValuationSnapshotRepo,
)

DEFAULT_REPORTING_ASSET_ID = USD_ASSET_ID
DEFAULT_POLICY_CHAIN = "default"
_INITIAL_POLICY_VERSION = "1"


def _json_safe(value: Any) -> Any:
    """Recursively convert Decimal to str for JSON-safe responses (never float)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    return value


def _snapshot_json(snapshot: ValuationSnapshot) -> dict[str, Any]:
    return _json_safe(snapshot.model_dump())


def _next_policy_version(existing: Optional[dict]) -> str:
    if existing is None or not existing.get("policy_version"):
        return _INITIAL_POLICY_VERSION
    try:
        return str(int(existing["policy_version"]) + 1)
    except (TypeError, ValueError):
        # A non-numeric stored label is treated as an opaque seed; bump with a
        # monotonic numeric suffix so provenance keeps advancing.
        return f"{existing['policy_version']}:1"


class ValuationService:
    """Orchestration facade over the valuation engine + persistence repos.

    All repositories default to their DB-free in-memory fallback under
    AETHER_ENV=local; every async seam is the same one a DB-backed deployment
    uses.
    """

    def __init__(
        self,
        *,
        registry: Optional[UniversalAssetRegistry] = None,
        observation_repo: Optional[ValuationPriceObservationRepo] = None,
        snapshot_repo: Optional[ValuationSnapshotRepo] = None,
        policy_repo: Optional[TenantValuePolicyRepo] = None,
    ) -> None:
        self.registry = registry or UniversalAssetRegistry()
        self.observation_store = ValuationObservationStore(
            observation_repo or ValuationPriceObservationRepo(),
        )
        self.observation_repo = (
            observation_repo or self.observation_store.repo
        )
        self.snapshots = snapshot_repo or ValuationSnapshotRepo()
        self.policies = policy_repo or TenantValuePolicyRepo()

    def _registry_port(self, tenant_id: str) -> ValuationRegistryPort:
        return ValuationRegistryPort(self.registry, tenant_id=tenant_id)

    async def _require_registered_reporting_assets(
        self, asset_ids: list[str], *, context: str,
    ) -> None:
        """Resolve-never-invent guard for reporting/allowed asset ids.

        A reporting currency must be a canonical asset the registry actually
        knows (a namespaced id present in registry_assets). Phantom units are
        rejected at the write boundary so no snapshot or policy is ever
        persisted as denominated in a unit the registry cannot verify — new
        reporting currencies arrive through registry data (seeding), not code.
        """
        unknown: list[str] = []
        for asset_id in asset_ids:
            if not asset_id:
                continue
            if await self.registry.get_asset(asset_id) is None:
                unknown.append(asset_id)
        if unknown:
            raise ValueError(
                f"{context} references reporting asset ids unknown to the "
                "registry (register/seed the asset first): "
                + ", ".join(sorted(set(unknown)))
            )

    # ── policy ─────────────────────────────────────────────────────────────

    async def read_policy(self, tenant_id: str) -> Optional[dict[str, Any]]:
        row = await self.policies.find_one({"tenant_id": tenant_id})
        if row is None:
            return None
        return _json_safe(row)

    async def reporting_asset_id_for(self, tenant_id: str) -> str:
        """Resolve the tenant's reporting asset id for rollup/display entry points.

        Defaults to ``fiat:USD`` when the tenant has no policy row or the row
        does not select a reporting asset. Rollup callers pass the result as
        ``reporting_asset_id`` to ``services.value.safe_rollup`` so derived
        totals are keyed by the tenant's reporting policy (the USD-first
        contract is the base case and is unchanged when no policy exists).
        """
        row = await self.policies.find_one({"tenant_id": tenant_id})
        if row is None:
            return DEFAULT_REPORTING_ASSET_ID
        reporting = row.get("reporting_asset_id") or (
            (row.get("allowed_reporting_asset_ids") or [DEFAULT_REPORTING_ASSET_ID])[0]
        )
        return str(reporting)

    async def _policy_model(self, tenant_id: str) -> Optional[TenantValuePolicy]:
        row = await self.policies.find_one({"tenant_id": tenant_id})
        if row is None:
            return None
        return self._policy_from_row(row)

    @staticmethod
    def _policy_from_row(row: Mapping[str, Any]) -> TenantValuePolicy:
        allowed = list(row.get("allowed_reporting_asset_ids") or ["fiat:USD"])
        return TenantValuePolicy(
            tenant_id=str(row["tenant_id"]),
            allowed_reporting_asset_ids=allowed,
            provider_chain_policy=str(row.get("provider_chain_policy") or "default"),
            stale_threshold_seconds=row.get("stale_threshold_seconds"),
            fallback_allowed=bool(row.get("fallback_allowed", False)),
            policy_version=row.get("policy_version"),
        )

    async def upsert_policy(
        self,
        tenant_id: str,
        *,
        allowed_reporting_asset_ids: Optional[list[str]] = None,
        reporting_asset_id: Optional[str] = None,
        provider_chain_policy: Optional[str] = None,
        stale_threshold_seconds: Optional[int] = None,
        fallback_allowed: bool = False,
    ) -> dict[str, Any]:
        """Create-or-update the tenant's current value policy (one row/tenant).

        ``policy_version`` is maintained monotonically by the service and is
        carried onto snapshots as provenance. A re-PUT of the exact current
        policy is an idempotent no-op (no version bump).
        """
        allowed = list(allowed_reporting_asset_ids or ["fiat:USD"])
        reporting = reporting_asset_id or allowed[0] if allowed else DEFAULT_REPORTING_ASSET_ID
        if reporting not in allowed:
            raise ValueError(
                f"reporting_asset_id {reporting!r} must be one of allowed "
                f"reporting asset ids: {allowed}"
            )
        await self._require_registered_reporting_assets(
            [reporting, *allowed], context="policy"
        )
        chain = provider_chain_policy or DEFAULT_POLICY_CHAIN
        existing = await self.policies.find_one({"tenant_id": tenant_id})

        def _same(row: Mapping[str, Any]) -> bool:
            return (
                row.get("reporting_asset_id") == reporting
                and list(row.get("allowed_reporting_asset_ids") or []) == allowed
                and row.get("provider_chain_policy") == chain
                and row.get("stale_threshold_seconds") == stale_threshold_seconds
                and bool(row.get("fallback_allowed", False)) == fallback_allowed
            )

        if existing is not None:
            if _same(existing):
                return {"inserted": False, "updated": False,
                        "policy_version": existing["policy_version"],
                        "policy": _json_safe(existing)}
            next_version = _next_policy_version(existing)
            await self.policies.update_by_key(
                {"tenant_id": tenant_id},
                {
                    "policy_version": next_version,
                    "reporting_asset_id": reporting,
                    "allowed_reporting_asset_ids": allowed,
                    "provider_chain_policy": chain,
                    "stale_threshold_seconds": stale_threshold_seconds,
                    "fallback_allowed": fallback_allowed,
                },
            )
            row = dict(existing)
            row.update({
                "policy_version": next_version,
                "reporting_asset_id": reporting,
                "allowed_reporting_asset_ids": allowed,
                "provider_chain_policy": chain,
                "stale_threshold_seconds": stale_threshold_seconds,
                "fallback_allowed": fallback_allowed,
            })
            return {"inserted": False, "updated": True,
                    "policy_version": next_version, "policy": _json_safe(row)}

        record = {
            "tenant_id": tenant_id,
            "policy_version": _INITIAL_POLICY_VERSION,
            "reporting_asset_id": reporting,
            "allowed_reporting_asset_ids": allowed,
            "provider_chain_policy": chain,
            "stale_threshold_seconds": stale_threshold_seconds,
            "fallback_allowed": fallback_allowed,
        }
        inserted = await self.policies.insert(record)
        return {"inserted": inserted, "updated": False,
                "policy_version": record["policy_version"],
                "policy": _json_safe(record)}

    # ── price observation ingest ───────────────────────────────────────────

    async def record_price_observation(
        self,
        observation: Any,
        *,
        received_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record one price observation through the single append path.

        Idempotent: a replay of an identical fact (same natural key) returns the
        existing record and does not append a duplicate.
        """
        stored = await observe_price(
            self.observation_store, observation, received_at=received_at,
        )
        return {
            "observation": _json_safe(stored.model_dump()),
            "observation_id": stored.observation_id,
        }

    # ── valuation + persist ────────────────────────────────────────────────

    async def value_and_persist(
        self,
        *,
        tenant_id: str,
        native: Any,
        effective_at: Any,
        reporting_asset_id: Optional[str] = None,
        deployment_id: Optional[str] = None,
        valuation_basis: str = "event_time",
        economic_role: Any = "unknown",
        supersedes_snapshot_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Canonicalize → value → persist a tenant valuation snapshot.

        Returns a JSON-safe summary with ``snapshot`` (the persisted model),
        ``valuation_id``, ``inserted`` (whether a new row was appended) and
        ``superseded_snapshot_id`` (set when this snapshot corrected a prior
        one). Re-valuing identical inputs at the same effective_at reproduces
        the same valuation_id and is a no-op.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required to value and persist")

        policy_model = await self._policy_model(tenant_id)
        if reporting_asset_id is None:
            if policy_model is not None:
                reporting_asset_id = policy_model.allowed_reporting_asset_ids[0] \
                    if policy_model.allowed_reporting_asset_ids else DEFAULT_REPORTING_ASSET_ID
            else:
                reporting_asset_id = DEFAULT_REPORTING_ASSET_ID
        reporting_asset_id = str(reporting_asset_id)
        # Resolve-never-invent: the snapshot must never be persisted as
        # denominated in a reporting unit the registry cannot verify. (A
        # registered-but-unpriced currency is fine — it yields missing_rate, not
        # a phantom label.)
        await self._require_registered_reporting_assets(
            [reporting_asset_id], context="value"
        )

        port = self._registry_port(tenant_id)
        snapshot = await value_at(
            native,
            effective_at=effective_at,
            reporting_asset_id=reporting_asset_id,
            deployment_id=deployment_id,
            valuation_basis=valuation_basis,
            registry=port,
            observations=self.observation_store,
            tenant_policy=policy_model,
            economic_role=economic_role,
            tenant_id=tenant_id,
        )

        # Idempotent replay no-op: the content-hash valuation_id already exists.
        # Checked BEFORE supersede validation so re-issuing a fully-applied
        # correction is a no-op returning the persisted row (its stored
        # supersedes back-pointer) rather than re-raising "already superseded".
        existing = await self.snapshots.find_one({
            "tenant_id": tenant_id,
            "valuation_id": snapshot.valuation_id,
        })
        if existing is not None:
            return {
                "valuation_id": snapshot.valuation_id,
                "inserted": False,
                "superseded_snapshot_id": existing.get("supersedes_snapshot_id"),
                "snapshot": _json_safe(existing),
            }

        if supersedes_snapshot_id is not None:
            if supersedes_snapshot_id == snapshot.valuation_id:
                raise ValueError(
                    "the correction reproduces the identical valuation_id — "
                    "nothing to supersede (identical inputs at the same "
                    "effective_at)"
                )
            prior = await self.snapshots.find_one({
                "tenant_id": tenant_id,
                "valuation_id": supersedes_snapshot_id,
            })
            if prior is None:
                raise ValueError(
                    f"supersedes_snapshot_id {supersedes_snapshot_id!r} is not a "
                    f"snapshot of tenant {tenant_id!r}"
                )
            if prior.get("status") != "current":
                raise ValueError(
                    f"snapshot {supersedes_snapshot_id!r} is already superseded"
                )

        idempotency_key = _snapshot_idempotency_key(
            tenant_id, snapshot.valuation_id, supersedes_snapshot_id,
        )
        record = self._snapshot_record(
            snapshot, tenant_id=tenant_id, idempotency_key=idempotency_key,
            supersedes_snapshot_id=supersedes_snapshot_id, native=native,
        )
        inserted = await self.snapshots.insert(record)

        superseded_id: Optional[str] = None
        if inserted and supersedes_snapshot_id is not None:
            await self.snapshots.mark_superseded(
                tenant_id, supersedes_snapshot_id, snapshot.valuation_id,
            )
            superseded_id = supersedes_snapshot_id

        stored = await self.snapshots.find_one({
            "tenant_id": tenant_id,
            "valuation_id": snapshot.valuation_id,
        })
        snapshot_json = _json_safe(stored) if stored is not None else _snapshot_json(snapshot)
        return {
            "valuation_id": snapshot.valuation_id,
            "inserted": inserted,
            "superseded_snapshot_id": superseded_id,
            "snapshot": snapshot_json,
        }

    @staticmethod
    def _snapshot_record(
        snapshot: ValuationSnapshot,
        *,
        tenant_id: str,
        idempotency_key: str,
        supersedes_snapshot_id: Optional[str],
        native: Any,
    ) -> dict[str, Any]:
        """Map a ValuationSnapshot onto the typed valuation_snapshots row."""
        evidence: Optional[dict[str, Any]] = None
        if isinstance(native, Mapping):
            evidence = {"native": {
                k: (str(v) if isinstance(v, Decimal) else v)
                for k, v in dict(native).items()
            }}
        return {
            "valuation_id": snapshot.valuation_id,
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
            "canonical_asset_id": snapshot.canonical_asset_id,
            "deployment_id": snapshot.deployment_id,
            "economic_role": snapshot.economic_role,
            "native_amount": snapshot.native_amount,
            "native_currency": snapshot.native_currency,
            "reporting_asset_id": snapshot.reporting_asset_id,
            "reporting_amount": snapshot.reporting_amount,
            "valuation_basis": snapshot.valuation_basis,
            "price_status": snapshot.price_status,
            "valuation_method": snapshot.valuation_method,
            "provider": snapshot.provider,
            "conversion_refs": list(snapshot.conversion_refs),
            "evidence": evidence,
            "registry_version": snapshot.registry_version,
            "policy_version": snapshot.policy_version,
            "price_observation_ids": list(snapshot.price_observation_ids),
            "supersedes_snapshot_id": supersedes_snapshot_id,
            "status": "current",
            "computed_at": snapshot.computed_at,
            "effective_at": snapshot.effective_at,
            "execution_by_aether": False,
        }

    # ── snapshot / observation reads (tenant-scoped reads) ─────────────────

    async def get_snapshot(
        self, tenant_id: str, valuation_id: str,
    ) -> Optional[dict[str, Any]]:
        row = await self.snapshots.find_one({
            "tenant_id": tenant_id, "valuation_id": valuation_id,
        })
        return _json_safe(row) if row is not None else None

    async def list_snapshots(
        self,
        tenant_id: str,
        *,
        canonical_asset_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if canonical_asset_id:
            filters["canonical_asset_id"] = canonical_asset_id
        if status:
            filters["status"] = status
        rows = await self.snapshots.find_many(
            filters, limit=limit, offset=offset,
            order_by="effective_at", descending=True,
        )
        return [_json_safe(r) for r in rows]

    async def list_observations(
        self,
        *,
        asset_id: Optional[str] = None,
        provider: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {}
        if asset_id:
            filters["asset_id"] = asset_id
        if provider:
            filters["provider"] = provider
        rows = await self.observation_repo.find_many(
            filters or None, limit=limit, offset=offset,
            order_by="observed_at", descending=True,
        )
        return [_json_safe(r) for r in rows]


def _snapshot_idempotency_key(
    tenant_id: str, valuation_id: str, supersedes_snapshot_id: Optional[str],
) -> str:
    basis = "\x00".join([tenant_id, valuation_id, supersedes_snapshot_id or ""])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
