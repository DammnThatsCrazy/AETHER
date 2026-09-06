"""Event-time valuation engine — pure, no persistence, ports injected.

``value_at`` turns an observed *native* value into a tenant-scoped
:class:`ValuationSnapshot` priced in a reporting asset (default ``fiat:USD``).

The engine NEVER touches a database, a registry table or an observation table:
both are injected through two Protocols — :class:`RegistryPort` (asset
identity + unresolved recording) and ``services.valuation.ingest.ObservationStorePort``
(append-only price observations). A later wave wires the real registry and the
``valuation_price_observations`` repository onto these ports.

Valuation rules (event-time path):
- USD fiat identity short-circuits to ``fiat_identity`` (no observation needed).
- fiat-to-fiat uses an FX observation (direct quote, or inverse quote when a
  provider only quotes the inverse pair, e.g. ``fiat:USD`` -> ``fiat:GBP``).
- crypto/token/stablecoin are priced by market observations quoted in the
  reporting asset.
- stablecoin amounts priced in USD are peg-aware via the *real*
  ``classify_peg`` from the stablecoin domain — never assumed $1 even when the
  peg is healthy; a deviation is reflected in the amount and the method
  (``stablecoin_peg_verified`` when on peg, ``stablecoin_peg`` otherwise).
- provider conflict is surfaced as ``provider_conflict`` (never a silent pick),
  staleness as ``stale_rate``, an anomalous top feed as ``outlier``, absence as
  ``missing_rate`` with ``reporting_amount=None`` — reporting amount null is
  UNAVAILABLE and is never coerced to ``0``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Mapping, Optional, Protocol, Union

from services.assets.models import ASSET_KINDS, CanonicalAsset, AssetDeployment
from services.stablecoin.valuation import classify_peg
from services.valuation.ingest import ObservationStorePort, classify_economic_role
from services.valuation.models import (
    VALUATION_BASIS,
    CanonicalNativeValue,
    TenantValuePolicy,
    ValuationSnapshot,
)
from services.valuation.price_providers import (
    DEFAULT_FRESHNESS_WINDOW_SECONDS,
    DEFAULT_PROVIDER_CHAIN,
    PROVIDER_VALUATION_METHODS,
    USD_ASSET_ID,
    parse_iso,
    provider_chain_for,
    to_iso,
)

# ── Tuning constants ────────────────────────────────────────────────────────

# Two independent live providers disagreeing by more than 1% -> provider_conflict.
CONFLICT_THRESHOLD_BPS = Decimal("100")
# A live candidate deviating from the live consensus median by > 5% is an outlier.
OUTLIER_DEVIATION_BPS = Decimal("500")


# ── RegistryPort ────────────────────────────────────────────────────────────
# The wiring lane implements this over services.assets.registry.
# UniversalAssetRegistry (same-wave, concurrent). Generic over the models —
# never over that class.


class RegistryPort(Protocol):
    """Port into the universal asset registry.

    Implemented in a later wave by the same-wave
    ``services.assets.registry.UniversalAssetRegistry``. The engine only
    relies on ``canonicalize`` and ``record_unresolved``; ``asset_for`` and
    ``resolve_deployment`` are part of the seam for the wiring wave. Methods are
    async so a DB-backed implementation slots in unchanged.
    """

    async def canonicalize(
        self, native: Any,
    ) -> Optional[CanonicalNativeValue]:
        """Resolve a native payload to a canonical asset + optional deployment.

        Returns ``None`` when the reference cannot be resolved (the caller must
        then ``record_unresolved`` — unknown stays explicit, never guessed).
        """
        ...

    async def asset_for(self, asset_id: str) -> Optional[CanonicalAsset]:
        """Return the canonical asset row for a namespaced id, or None."""
        ...

    async def resolve_deployment(
        self,
        asset_id: str,
        *,
        deployment_id: Optional[str] = None,
        chain: Optional[str] = None,
        contract_or_mint: Optional[str] = None,
    ) -> Optional[AssetDeployment]:
        """Resolve a deployment of ``asset_id`` (by id, or chain+contract), or
        None when no deployment matches."""
        ...

    async def record_unresolved(
        self,
        *,
        raw_reference: str,
        tenant_id: Optional[str] = None,
        reason: str = "no_registry_entry",
        observed_at: Optional[str] = None,
    ) -> None:
        """Record that a raw reference could not be resolved (UnresolvedReason).
        Called whenever canonicalize returns None."""
        ...


# ── Native payload helpers ──────────────────────────────────────────────────


def _field(native: Any, name: str) -> Any:
    """Read a field from a mapping or a model (duck-typed payload access)."""
    if isinstance(native, Mapping):
        return native.get(name)
    return getattr(native, name, None)


def _read_amount_currency(native: Any) -> tuple[Any, str]:
    amount = _field(native, "amount")
    if amount is None:
        amount = _field(native, "value")
    if amount is None:
        raise ValueError("native payload must carry an amount/value")
    currency = _field(native, "currency")
    if currency is None:
        for key in ("asset_symbol", "symbol", "asset_id", "canonical_asset_id"):
            currency = _field(native, key)
            if currency:
                break
    if not currency:
        raise ValueError("native payload must carry a currency/asset reference")
    return amount, str(currency)


def _reference_for(native: Any) -> str:
    """Best-effort raw-reference string for an unresolved sighting."""
    for key in ("canonical_asset_id", "asset_id", "currency", "asset_symbol", "symbol"):
        value = _field(native, key)
        if value:
            return str(value)
    if isinstance(native, Mapping):
        return str(native)
    return str(native)


def _kind_from_asset_id(asset_id: Optional[str]) -> Optional[str]:
    if not asset_id:
        return None
    namespace = asset_id.split(":", 1)[0]
    return namespace if namespace in ASSET_KINDS else None


def _resolve_tenant(
    tenant_id: Optional[str], tenant_policy: Optional[TenantValuePolicy],
) -> Optional[str]:
    if tenant_id:
        return str(tenant_id)
    if tenant_policy is not None and tenant_policy.tenant_id:
        return tenant_policy.tenant_id
    return None


# ── Price-candidate resolution ──────────────────────────────────────────────


@dataclass
class _Candidate:
    provider: str
    observation: Any  # MarketPriceObservation
    factor: Decimal  # reporting units per 1 native unit
    direct: bool


@dataclass
class _Resolution:
    status: str  # PriceStatus member
    method: str  # ValuationMethodExtended member
    provider: Optional[str]
    factor: Optional[Decimal]
    observation_ids: List[str] = field(default_factory=list)


def _latest_matching_quote(
    rows: List[Any], *, quote_asset_id: str, effective_at: datetime,
) -> Optional[Any]:
    """Newest observation (observed_at <= effective_at) quoting the target."""
    best = None
    best_dt: Optional[datetime] = None
    for observation in rows:
        if observation.quote_asset_id != quote_asset_id:
            continue
        try:
            observed_dt = parse_iso(observation.observed_at)
        except ValueError:
            continue
        if observed_dt > effective_at:
            continue
        if best_dt is None or observed_dt > best_dt:
            best = observation
            best_dt = observed_dt
    return best


async def _gather_direct(
    observations: ObservationStorePort,
    chain: tuple[str, ...],
    asset_id: str,
    deployment_id: Optional[str],
    reporting_asset_id: str,
    effective_iso: str,
    effective_at: datetime,
    lookback_seconds: int,
) -> List[_Candidate]:
    """One direct candidate per chain provider: price of asset in reporting."""
    candidates: List[_Candidate] = []
    for provider in chain:
        rows = await observations.observations_for(
            asset_id, deployment_id, provider, effective_iso, lookback_seconds,
        )
        obs = _latest_matching_quote(
            rows, quote_asset_id=reporting_asset_id, effective_at=effective_at,
        )
        if obs is not None:
            candidates.append(
                _Candidate(provider=provider, observation=obs,
                           factor=obs.price, direct=True)
            )
    return candidates


async def _gather_inverse(
    observations: ObservationStorePort,
    chain: tuple[str, ...],
    asset_id: str,
    reporting_asset_id: str,
    effective_iso: str,
    effective_at: datetime,
    lookback_seconds: int,
) -> List[_Candidate]:
    """Fiat-fiat inverse quotes: reporting quoted in the native asset (e.g. an
    FX provider that only quotes ``fiat:USD`` -> ``fiat:GBP``). factor = 1/rate."""
    candidates: List[_Candidate] = []
    for provider in chain:
        rows = await observations.observations_for(
            reporting_asset_id, None, provider, effective_iso, lookback_seconds,
        )
        obs = _latest_matching_quote(
            rows, quote_asset_id=asset_id, effective_at=effective_at,
        )
        if obs is not None and obs.price != 0:
            candidates.append(
                _Candidate(
                    provider=provider,
                    observation=obs,
                    factor=Decimal(1) / obs.price,
                    direct=False,
                )
            )
    return candidates


def _freshness_window(observation: Any, tenant_window: Optional[int]) -> int:
    """Live-ness bound for an observation. The most-strict bound wins: a tenant
    stale_threshold below an observation's declared window tightens it, and a
    per-observation window below a tenant default is honored too."""
    windows: list[int] = []
    if observation.freshness_window_seconds is not None:
        windows.append(observation.freshness_window_seconds)
    if tenant_window is not None:
        windows.append(tenant_window)
    if not windows:
        return DEFAULT_FRESHNESS_WINDOW_SECONDS
    return min(windows)


def _is_live(
    observation: Any, effective_at: datetime, tenant_window: Optional[int],
) -> bool:
    observed = parse_iso(observation.observed_at)
    age_seconds = (effective_at - observed).total_seconds()
    return age_seconds <= _freshness_window(observation, tenant_window)


def _relative_bps(a: Decimal, b: Decimal) -> Decimal:
    denominator = abs(a) if a else abs(b)
    if denominator == 0:
        return Decimal(0)
    return (abs(a - b) / denominator) * Decimal("10000")


def _median(prices: List[Decimal]) -> Decimal:
    ordered = sorted(prices)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _method_for(candidate: _Candidate, kind: Optional[str], reporting: str) -> str:
    """Valuation method for a chosen candidate (peg-aware for USD stablecoins)."""
    if (
        kind == "stablecoin"
        and reporting == USD_ASSET_ID
        and candidate.direct
        and candidate.factor is not None
    ):
        deviation_bps = (candidate.factor - Decimal(1)) * Decimal("10000")
        peg_status = classify_peg(deviation_bps)
        # Never assumes $1: the observed price (factor) is used verbatim and the
        # classify_peg result only drives the method / verification label.
        return "stablecoin_peg_verified" if peg_status == "on_peg" else "stablecoin_peg"
    return PROVIDER_VALUATION_METHODS.get(candidate.provider, "market_price")


def _status_for_provider(provider: str) -> str:
    return "fallback" if provider == "fallback" else "normal"


def _conflict_resolution(
    live_sorted: List[_Candidate],
    kind: Optional[str],
    reporting: str,
    *,
    status: str,
    fallback_allowed: bool,
) -> _Resolution:
    """An amount-less resolution (provider_conflict / outlier), optionally
    degraded to a policy-approved fallback source."""
    if fallback_allowed:
        for candidate in live_sorted:
            if candidate.provider == "fallback":
                return _Resolution(
                    status="fallback",
                    method=_method_for(candidate, kind, reporting),
                    provider=candidate.provider,
                    factor=candidate.factor,
                    observation_ids=[candidate.observation.observation_id],
                )
    ids = [c.observation.observation_id for c in live_sorted if c.observation.observation_id]
    return _Resolution(status=status, method="unavailable", provider=None,
                       factor=None, observation_ids=ids)


def _resolve_candidates(
    candidates: List[_Candidate],
    *,
    chain: tuple[str, ...],
    kind: Optional[str],
    reporting: str,
    effective_at: datetime,
    tenant_window: Optional[int],
    fallback_allowed: bool,
) -> _Resolution:
    """Choose the authoritative price + status from candidate observations."""
    if not candidates:
        return _Resolution(status="missing_rate", method="unavailable",
                           provider=None, factor=None)

    priority = {name: idx for idx, name in enumerate(chain)}
    candidates.sort(key=lambda c: priority.get(c.provider, len(chain)))

    live = [c for c in candidates if _is_live(c.observation, effective_at, tenant_window)]
    if not live:
        best = candidates[0]
        return _Resolution(
            status="stale_rate",
            method=_method_for(best, kind, reporting),
            provider=best.provider,
            factor=best.factor,
            observation_ids=[best.observation.observation_id],
        )
    if len(live) == 1:
        best = live[0]
        return _Resolution(
            status=_status_for_provider(best.provider),
            method=_method_for(best, kind, reporting),
            provider=best.provider,
            factor=best.factor,
            observation_ids=[best.observation.observation_id],
        )

    # Multiple live, independent sources: surface conflict / outlier rather than
    # silently picking the top-priority feed.
    median = _median([c.factor for c in live])
    def _is_outlier(c: _Candidate) -> bool:
        if median == 0:
            return False
        return (abs(c.factor - median) / abs(median)) * Decimal("10000") > OUTLIER_DEVIATION_BPS

    if _is_outlier(live[0]):
        # The feed the policy would normally trust is anomalous — do not pick it.
        return _conflict_resolution(
            live, kind, reporting, status="outlier",
            fallback_allowed=fallback_allowed,
        )

    non_outliers = [c for c in live if not _is_outlier(c)]
    if not non_outliers:
        # Two live feeds mutually diverge beyond the outlier band with no sane
        # consensus — that is a conflict.
        return _conflict_resolution(
            live, kind, reporting, status="provider_conflict",
            fallback_allowed=fallback_allowed,
        )

    if len(non_outliers) >= 2:
        a, b = non_outliers[0], non_outliers[1]
        if a.provider != b.provider and _relative_bps(a.factor, b.factor) > CONFLICT_THRESHOLD_BPS:
            return _conflict_resolution(
                live, kind, reporting, status="provider_conflict",
                fallback_allowed=fallback_allowed,
            )

    chosen = non_outliers[0]
    return _Resolution(
        status=_status_for_provider(chosen.provider),
        method=_method_for(chosen, kind, reporting),
        provider=chosen.provider,
        factor=chosen.factor,
        observation_ids=[chosen.observation.observation_id],
    )


# ── Snapshot assembly ───────────────────────────────────────────────────────


def _deterministic_valuation_id(basis: list[str]) -> str:
    joined = "|".join(basis)
    return "val_" + hashlib.sha256(joined.encode()).hexdigest()[:32]


def _computed_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry_version(registry: Any) -> Optional[str]:
    value = getattr(registry, "registry_version", None)
    if isinstance(value, str) and value:
        return value
    return None


def _build_snapshot(
    *,
    tenant: str,
    role: str,
    native_amount: Decimal,
    native_currency: str,
    canonical_asset_id: Optional[str],
    deployment_id: Optional[str],
    reporting_asset_id: str,
    valuation_basis: str,
    effective_iso: str,
    resolution: _Resolution,
    registry: Any,
    policy_version: Optional[str],
) -> ValuationSnapshot:
    reporting_amount = (
        (native_amount * resolution.factor)
        if resolution.factor is not None else None
    )
    return ValuationSnapshot(
        valuation_id=_deterministic_valuation_id([
            tenant, canonical_asset_id or "", deployment_id or "",
            format(native_amount, "f"), native_currency,
            reporting_asset_id, valuation_basis, effective_iso, role,
            resolution.status, resolution.method, resolution.provider or "",
            "none" if reporting_amount is None else format(reporting_amount, "f"),
            *sorted(resolution.observation_ids),
        ]),
        tenant_id=tenant,
        canonical_asset_id=canonical_asset_id,
        deployment_id=deployment_id,
        economic_role=role,
        native_amount=native_amount,
        native_currency=native_currency,
        reporting_asset_id=reporting_asset_id,
        reporting_amount=reporting_amount,
        valuation_basis=valuation_basis,
        price_status=resolution.status,
        valuation_method=resolution.method,
        provider=resolution.provider,
        registry_version=_registry_version(registry),
        policy_version=policy_version,
        price_observation_ids=resolution.observation_ids,
        computed_at=_computed_now_iso(),
        effective_at=effective_iso,
    )


# ── Public entry point ──────────────────────────────────────────────────────


async def value_at(
    native: Any,
    *,
    effective_at: Union[str, datetime],
    reporting_asset_id: str = USD_ASSET_ID,
    deployment_id: Optional[str] = None,
    valuation_basis: str = "transaction_time",
    registry: RegistryPort,
    observations: ObservationStorePort,
    tenant_policy: Optional[TenantValuePolicy] = None,
    economic_role: Any = "unknown",
    tenant_id: Optional[str] = None,
) -> ValuationSnapshot:
    """Value a native payload into ``reporting_asset_id`` at ``effective_at``.

    Pure engine — registry + observation store are injected ports. See the
    module docstring for the valuation rules. ``tenant_id`` is required when
    ``tenant_policy`` is not supplied (ValuationSnapshot is tenant-scoped).

    Raises:
        ValueError: no tenant, an unknown valuation_basis, an unknown
            provider_chain_policy, or a disallowed reporting asset id.
    """
    if valuation_basis not in VALUATION_BASIS:
        raise ValueError(
            f"unknown valuation_basis {valuation_basis!r}; expected one of "
            + ", ".join(sorted(VALUATION_BASIS))
        )
    effective_iso = to_iso(effective_at)
    effective_at_dt = parse_iso(effective_iso)

    tenant = _resolve_tenant(tenant_id, tenant_policy)
    if tenant is None:
        raise ValueError(
            "tenant_id is required to value into a tenant-scoped ValuationSnapshot"
        )

    policy_version: Optional[str] = None
    tenant_window: Optional[int] = None
    fallback_allowed = False
    if tenant_policy is not None:
        if reporting_asset_id not in tenant_policy.allowed_reporting_asset_ids:
            raise ValueError(
                f"reporting asset {reporting_asset_id!r} is not allowed by tenant "
                f"policy {tenant_policy.tenant_id!r} (allowed: "
                + ", ".join(tenant_policy.allowed_reporting_asset_ids) + ")"
            )
        chain = provider_chain_for(tenant_policy.provider_chain_policy)
        tenant_window = tenant_policy.stale_threshold_seconds
        fallback_allowed = tenant_policy.fallback_allowed
        policy_version = tenant_policy.policy_version
    else:
        chain = DEFAULT_PROVIDER_CHAIN

    # Economic role: the caller's explicit role wins; otherwise fall back to the
    # canonical value's role, then to a native-payload hint, then "unknown".
    role = classify_economic_role(economic_role)

    canonical = await registry.canonicalize(native)
    if canonical is None:
        raw_reference = _reference_for(native)
        reason = "no_registry_entry" if raw_reference else "malformed_reference"
        await registry.record_unresolved(
            raw_reference=raw_reference,
            tenant_id=tenant,
            reason=reason,
            observed_at=effective_iso,
        )
        native_amount, native_currency = _read_amount_currency(native)
        if role == "unknown":
            role = classify_economic_role(native)
        unresolved = _Resolution(
            status="missing_rate", method="unavailable", provider=None, factor=None,
        )
        return _build_snapshot(
            tenant=tenant,
            role=role,
            native_amount=_coerce_amount(native_amount),
            native_currency=native_currency or raw_reference or "unknown",
            canonical_asset_id=None,
            deployment_id=None,
            reporting_asset_id=reporting_asset_id,
            valuation_basis=valuation_basis,
            effective_iso=effective_iso,
            resolution=unresolved,
            registry=registry,
            policy_version=policy_version,
        )

    if role == "unknown":
        role = classify_economic_role(canonical.economic_role)
    if role == "unknown":
        role = classify_economic_role(native)

    asset_id = canonical.canonical_asset_id
    native_amount = canonical.amount
    native_currency = canonical.currency or asset_id
    kind = _kind_from_asset_id(asset_id)
    deploy = deployment_id if deployment_id else canonical.deployment_id
    if kind == "fiat":
        deploy = None  # fiats have no deployment rows

    # Same-asset fiat identity (default: fiat:USD native reported in fiat:USD).
    if asset_id == reporting_asset_id and kind == "fiat":
        identity = _Resolution(
            status="normal", method="fiat_identity", provider=None, factor=Decimal(1),
        )
        return _build_snapshot(
            tenant=tenant,
            role=role,
            native_amount=native_amount,
            native_currency=native_currency,
            canonical_asset_id=asset_id,
            deployment_id=None,
            reporting_asset_id=reporting_asset_id,
            valuation_basis=valuation_basis,
            effective_iso=effective_iso,
            resolution=identity,
            registry=registry,
            policy_version=policy_version,
        )

    lookback_seconds = tenant_window or DEFAULT_FRESHNESS_WINDOW_SECONDS

    candidates = await _gather_direct(
        observations, chain, asset_id, deploy, reporting_asset_id,
        effective_iso, effective_at_dt, lookback_seconds,
    )
    if not candidates and deploy is not None:
        # Deployment-scoped quote missing -> fall back to the asset-level market.
        candidates = await _gather_direct(
            observations, chain, asset_id, None, reporting_asset_id,
            effective_iso, effective_at_dt, lookback_seconds,
        )

    reporting_kind = _kind_from_asset_id(reporting_asset_id)
    if not candidates and kind == "fiat" and reporting_kind == "fiat":
        # FX providers often quote only USD -> reporting fiat; invert that rate.
        candidates = await _gather_inverse(
            observations, chain, asset_id, reporting_asset_id,
            effective_iso, effective_at_dt, lookback_seconds,
        )

    resolution = _resolve_candidates(
        candidates,
        chain=chain,
        kind=kind,
        reporting=reporting_asset_id,
        effective_at=effective_at_dt,
        tenant_window=tenant_window,
        fallback_allowed=fallback_allowed,
    )

    return _build_snapshot(
        tenant=tenant,
        role=role,
        native_amount=native_amount,
        native_currency=native_currency,
        canonical_asset_id=asset_id,
        deployment_id=deploy,
        reporting_asset_id=reporting_asset_id,
        valuation_basis=valuation_basis,
        effective_iso=effective_iso,
        resolution=resolution,
        registry=registry,
        policy_version=policy_version,
    )


def _coerce_amount(value: Any) -> Decimal:
    """Coerce an unresolved-path native amount to Decimal (float rejected by
    the snapshot validator anyway — this is only an early sanity check)."""
    from repositories.typed_repo import as_decimal

    return as_decimal(value)
