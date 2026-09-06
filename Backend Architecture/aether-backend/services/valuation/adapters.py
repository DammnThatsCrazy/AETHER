"""Concrete port adapters for the event-time valuation engine (services/valuation).

Wave-3 wiring (lane C3-VALUATION-PERSIST): the W2 pure engine (engine.py /
ingest.py) depends only on two async Protocols — RegistryPort
(engine.RegistryPort) and ObservationStorePort (ingest.ObservationStorePort).
This module supplies the REAL implementations over the universal asset registry
and the new ``valuation_price_observations`` persistence table:

  - :class:`ValuationRegistryPort` wraps
    ``services.assets.registry.UniversalAssetRegistry`` (the canonical reference
    facade + its tenant-scoped unresolved recording) and adapts its report
    shape onto the engine's :class:`CanonicalNativeValue` seam.
  - :class:`ValuationObservationStore` is an idempotent append + read adapter
    over :class:`ValuationPriceObservationRepo`.

Unresolved references are recorded exactly once: the registry resolver already
records an explicit unresolved row during canonicalize (never guessed), so the
adapter's ``record_unresolved`` is a no-op when the (tenant, raw_reference)
sighting already exists — the engine's post-canonicalize ``record_unresolved``
call must not double-count one sighting.

Async seams are preserved exactly as the engine expects, so a DB-backed
implementation slots in unchanged under AETHER_ENV=local via the typed-repo
in-memory fallback.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from repositories.typed_repo import as_decimal
from services.assets.models import AssetDeployment, CanonicalAsset
from services.assets.registry import UniversalAssetRegistry
from services.valuation.models import CanonicalNativeValue, MarketPriceObservation
from services.valuation.price_providers import parse_iso
from services.valuation.repositories import ValuationPriceObservationRepo

# Sentinel tenant for adapter-level actions that arrive without a tenant
# context (mirrors the registry facade's _PLATFORM_TENANT convention).
_PLATFORM_TENANT = "platform"


def _only(record: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Keep only contract fields from a repo row (rows carry trailing ``data``)."""
    return {k: record[k] for k in fields if k in record}


def _as_native_dict(native: Any) -> dict[str, Any]:
    """Coerce a native payload to a plain dict (route models / mappings)."""
    if isinstance(native, Mapping):
        return dict(native)
    if hasattr(native, "model_dump"):
        return native.model_dump()
    raise TypeError(
        "native payload must be a mapping or a pydantic model, "
        f"got {type(native).__name__}"
    )


class ValuationRegistryPort:
    """RegistryPort over UniversalAssetRegistry.

    ``tenant_id`` is bound at construction because the engine seam
    (``RegistryPort.canonicalize``) does not thread a tenant id — the adapter
    passes it through so unresolved references are recorded under the valuing
    tenant (never the platform sentinel).
    """

    def __init__(
        self,
        registry: Optional[UniversalAssetRegistry] = None,
        *,
        tenant_id: Optional[str] = None,
    ) -> None:
        self.registry = registry or UniversalAssetRegistry()
        self.tenant_id = tenant_id or _PLATFORM_TENANT
        self.registry_version = (
            self.registry.current_registry_version()
            if hasattr(self.registry, "current_registry_version")
            else None
        )

    # ── RegistryPort.canonicalize ──────────────────────────────────────────

    async def canonicalize(
        self, native: Any,
    ) -> Optional[CanonicalNativeValue]:
        native_dict = _as_native_dict(native)
        report = await self.registry.canonicalize(
            native_dict, tenant_id=self.tenant_id,
        )
        version = report.get("registry_version")
        if isinstance(version, str) and version:
            self.registry_version = version
        if not report.get("verified"):
            # The resolver already recorded an explicit unresolved row (never
            # guessed) — return None so the engine records the snapshot as
            # unavailable rather than fabricating identity.
            return None

        canonical_asset_id = report.get("canonical_asset_id")
        amount_raw = native_dict.get("amount", native_dict.get("value"))
        currency = native_dict.get("currency")
        if amount_raw is None or not currency:
            # The asset is VERIFIED but the payload carries no observable
            # amount/currency. Raise rather than return None so this stays
            # distinct from an unknown asset: the engine must NOT record an
            # unresolved-reference row for a KNOWN asset (that would mislabel
            # the ledger), and the caller receives a clear 422. Nothing is
            # guessed.
            raise ValueError(
                f"verified asset {canonical_asset_id!r} but the native payload "
                "carries no amount or currency to value"
            )
        asset = report.get("resolved_asset") or {}
        deployment = report.get("resolved_deployment") or {}
        symbol = native_dict.get("asset_symbol") or report.get("canonical_symbol")
        return CanonicalNativeValue(
            amount=as_decimal(amount_raw),
            currency=str(currency),
            canonical_asset_id=canonical_asset_id,
            deployment_id=report.get("deployment_id"),
            asset_id=canonical_asset_id,
            asset_symbol=symbol,
            asset_name=native_dict.get("asset_name") or asset.get("name"),
            chain=native_dict.get("chain") or deployment.get("chain_id"),
            network=native_dict.get("network") or deployment.get("network"),
            contract_or_mint=(
                native_dict.get("contract_or_mint")
                or deployment.get("contract_or_mint")
            ),
            decimals=(
                native_dict.get("decimals")
                or report.get("canonical_decimals")
            ),
            economic_role=native_dict.get("economic_role") or "unknown",
        )

    # ── RegistryPort reads ─────────────────────────────────────────────────

    async def asset_for(self, asset_id: str) -> Optional[CanonicalAsset]:
        row = await self.registry.get_asset(asset_id)
        if row is None:
            return None
        return CanonicalAsset.model_validate(_only(row, _ASSET_FIELDS))

    async def resolve_deployment(
        self,
        asset_id: str,
        *,
        deployment_id: Optional[str] = None,
        chain: Optional[str] = None,
        contract_or_mint: Optional[str] = None,
    ) -> Optional[AssetDeployment]:
        row = None
        if deployment_id:
            row = await self.registry.get_deployment(deployment_id)
        elif chain and contract_or_mint:
            row = await self.registry.resolve_deployment(chain, contract_or_mint)
        if row is None:
            return None
        if asset_id and row.get("asset_id") != asset_id:
            return None
        return AssetDeployment.model_validate(_only(row, _DEPLOYMENT_FIELDS))

    # ── RegistryPort.record_unresolved (exactly-once) ─────────────────────

    async def record_unresolved(
        self,
        *,
        raw_reference: str,
        tenant_id: Optional[str] = None,
        reason: str = "no_registry_entry",
        observed_at: Optional[str] = None,
    ) -> None:
        """Record an unresolved sighting unless canonicalize already did.

        The real registry resolver records unresolved rows *during*
        canonicalize (unknown stays explicit, never guessed), so the engine's
        post-canonicalize ``record_unresolved`` for the same (tenant,
        raw_reference) is intentionally a no-op to avoid double-counting one
        sighting. When no row exists (an out-of-band unresolved reference), this
        records it.
        """
        tenant = tenant_id or self.tenant_id
        existing = await self.registry.unresolved.find_one({
            "tenant_id": tenant,
            "raw_reference": raw_reference,
        })
        if existing is not None:
            return
        await self.registry.record_unresolved(
            raw_reference=raw_reference,
            reason=reason,
            tenant_id=tenant,
            seen_at=observed_at,
        )


# CanonicalAsset / AssetDeployment contract fields (exclude repo trailing data).
_ASSET_FIELDS = (
    "id", "kind", "symbol", "name", "issuer", "display_decimals", "status",
)
_DEPLOYMENT_FIELDS = (
    "deployment_id", "asset_id", "chain_id", "contract_or_mint", "decimals",
    "canonical_vs_bridged", "deployment_status", "token_standard",
    "first_seen_at", "last_seen_at", "deprecated_at",
)


class ValuationObservationStore:
    """ObservationStorePort over the ``valuation_price_observations`` repo.

    Idempotent record_observation: a replay of an identical fact collides on the
    deterministic observation_id content-hash PK and is a no-op (returns False).
    observations_for returns the candidate rows the engine asked for with
    ``observed_at <= effective_at``, ordered most-recent-first.
    """

    def __init__(
        self,
        repo: Optional[ValuationPriceObservationRepo] = None,
    ) -> None:
        self.repo = repo or ValuationPriceObservationRepo()

    async def observations_for(
        self,
        asset_id: str,
        deployment_id: Optional[str],
        provider: str,
        effective_at: str,
        freshness_window_seconds: Optional[int] = None,
    ) -> List[MarketPriceObservation]:
        effective_dt = parse_iso(effective_at)
        rows = await self.repo.lookup_candidates(
            asset_id, provider, deployment_id=deployment_id,
        )
        matched: List[MarketPriceObservation] = []
        for row in rows:
            if deployment_id is None and row.get("deployment_id"):
                # An asset-level lookup must not see deployment-scoped facts.
                continue
            observed = row.get("observed_at")
            if not observed:
                continue
            try:
                if parse_iso(observed) > effective_dt:
                    continue
            except ValueError:
                continue
            matched.append(self._to_model(row))
        return matched

    async def record_observation(
        self, observation: MarketPriceObservation,
    ) -> bool:
        record = observation.model_dump(exclude_none=True)
        # data JSONB catch-all is not part of the observation contract.
        record.pop("data", None)
        return await self.repo.insert(record)

    @staticmethod
    def _to_model(row: Mapping[str, Any]) -> MarketPriceObservation:
        clean = {k: row[k] for k in _OBSERVATION_FIELDS if k in row}
        return MarketPriceObservation.model_validate(clean)


_OBSERVATION_FIELDS = (
    "observation_id", "asset_id", "deployment_id", "provider",
    "quote_asset_id", "price", "observed_at", "source", "source_record_id",
    "freshness_window_seconds", "received_at",
)
