"""Price observation ingest — the single append path into the observation store.

Every MarketPriceObservation enters through :func:`observe_price`:

- numeric ``price`` input is coerced to Decimal through the model's
  float-rejecting validator (binary floats are never legal canonical amounts);
- ``received_at`` is stamped here (UTC ISO) when the observation does not carry
  one;
- ``observation_id`` defaults to a deterministic id derived from the
  observation's natural key;
- the append is idempotent: a re-observation whose natural key
  (``provider``/``observed_at``/``source_record_id`` when set — otherwise the
  full source identity) is already recorded is skipped and the existing record
  returned.

This module also owns the :class:`ObservationStorePort` Protocol (observation
persistence seam). A later wave implements it over the
``valuation_price_observations`` table with an ``ON CONFLICT DO NOTHING``
unique index on the natural key. It also exposes
:func:`classify_economic_role` — the economic-role classifier shared by the
ingest path and the engine.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Protocol, Union

from services.valuation.models import (
    ECONOMIC_ROLES,
    EconomicRole,
    MarketPriceObservation,
)
from services.valuation.price_providers import (
    deterministic_observation_id,
    utc_now_iso,
)

# ── ObservationStorePort ────────────────────────────────────────────────────
# The engine reads and the ingest path writes through this one seam. A later
# wave wires the real repository over ``valuation_price_observations``.


class ObservationStorePort(Protocol):
    """Persistence seam for append-only MarketPriceObservations.

    A later wave implements this over the ``valuation_price_observations``
    table. Implementations are async and never need a tenant id — observations
    are global market facts (only ValuationSnapshots are tenant-scoped).
    """

    async def observations_for(
        self,
        asset_id: str,
        deployment_id: Optional[str],
        provider: str,
        effective_at: str,
        freshness_window_seconds: Optional[int] = None,
    ) -> List[MarketPriceObservation]:
        """Most-recent-first observations for ``(asset_id, deployment_id,
        provider)`` with ``observed_at <= effective_at``.

        ``freshness_window_seconds`` is a lookback hint the store MAY use to
        bound its scan, but the store MUST still return the single most recent
        observation even when it predates the window (so the engine can
        classify staleness / missing itself rather than assuming a gap means
        missing). Rows are returned ordered by ``observed_at`` descending.
        """
        ...

    async def record_observation(
        self, observation: MarketPriceObservation,
    ) -> bool:
        """Append one immutable observation.

        MUST be idempotent on the observation's natural key (asset_id,
        deployment_id, provider, quote_asset_id, observed_at, source,
        source_record_id) — a replay is a no-op. Returns True when a new row
        was inserted, False on a duplicate.
        """
        ...


# ── Natural-key helpers ─────────────────────────────────────────────────────


def observation_natural_key(
    observation: MarketPriceObservation,
) -> tuple:
    """The dedup identity for an observation.

    When a ``source_record_id`` is present it is authoritative provenance, so
    ``(provider, source_record_id, observed_at)`` alone identifies the fact.
    Otherwise the full source identity is used so two genuinely different
    sources observed in the same instant are never collapsed.
    """
    if observation.source_record_id:
        return (observation.provider, observation.source_record_id, observation.observed_at)
    return (
        observation.provider,
        observation.asset_id,
        observation.deployment_id,
        observation.quote_asset_id,
        observation.observed_at,
        observation.source,
    )


def _same_natural_key(a: MarketPriceObservation, b: MarketPriceObservation) -> bool:
    return observation_natural_key(a) == observation_natural_key(b)


# ── Normalize + stamp ───────────────────────────────────────────────────────


def normalize_observation(
    observation: Union[MarketPriceObservation, Mapping[str, Any]],
    *,
    received_at: Optional[str] = None,
) -> MarketPriceObservation:
    """Coerce an observation-shaped input into a validated
    ``MarketPriceObservation``.

    A float ``price`` raises (coercion goes through
    ``repositories.typed_repo.as_decimal``). ``received_at`` is stamped (UTC)
    when absent; ``observation_id`` defaults to a deterministic id.
    """
    if isinstance(observation, MarketPriceObservation):
        data = observation.model_dump()
    elif isinstance(observation, Mapping):
        data = dict(observation)
    else:
        raise TypeError(
            "observation must be a MarketPriceObservation or a mapping of its fields"
        )

    if not data.get("observed_at"):
        raise ValueError("observed_at is required")

    if data.get("received_at") is None:
        data["received_at"] = received_at or utc_now_iso()
    if not data.get("observation_id"):
        data["observation_id"] = deterministic_observation_id(
            asset_id=data.get("asset_id") or "",
            deployment_id=data.get("deployment_id"),
            provider=data.get("provider") or "",
            quote_asset_id=data.get("quote_asset_id") or "",
            observed_at=data.get("observed_at") or "",
            source=data.get("source") or "",
            source_record_id=data.get("source_record_id"),
        )
    return MarketPriceObservation(**data)


# ── Single append path ──────────────────────────────────────────────────────


async def observe_price(
    store: ObservationStorePort,
    observation: Union[MarketPriceObservation, Mapping[str, Any]],
    *,
    received_at: Optional[str] = None,
) -> MarketPriceObservation:
    """Record one price observation (idempotent single append path).

    Returns the authoritative stored record — the newly appended observation,
    or the pre-existing record when the natural key was already recorded
    (replay-safe no-op).
    """
    obs = normalize_observation(observation, received_at=received_at)

    # Belt-and-braces duplicate guard on top of the store's idempotent
    # record_observation: scanning the store's own candidate set keeps
    # observe_price replay-safe even before the persistence wave lands.
    existing = await store.observations_for(
        obs.asset_id, obs.deployment_id, obs.provider, obs.observed_at, None,
    )
    for row in existing:
        if _same_natural_key(row, obs):
            return row

    await store.record_observation(obs)
    return obs


# ── Economic-role classification ────────────────────────────────────────────


def classify_economic_role(payload_hint: Any) -> EconomicRole:
    """Classify an economic role from a payload hint (mirrors the TS
    ``classifyEconomicRole`` in packages/shared/financial-assets.ts).

    Accepts a bare string, or an object/mapping carrying ``economic_role`` |
    ``role`` | ``type`` | ``purpose`` | ``hint``. Hints are normalized
    (lowercased, spaces/hyphens -> underscores) and mapped onto
    ``ECONOMIC_ROLES``; anything unmatched returns ``unknown`` — never a guess.
    """
    hint = _hint_from(payload_hint)
    if hint is None:
        return "unknown"
    normalized = _normalize_hint(hint)
    if normalized in ECONOMIC_ROLES:
        return normalized  # type: ignore[return-value]
    return "unknown"


def _hint_from(payload_hint: Any) -> Optional[str]:
    if isinstance(payload_hint, str):
        return payload_hint
    if isinstance(payload_hint, Mapping):
        for key in ("economic_role", "role", "type", "purpose", "hint"):
            value = payload_hint.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None
    # Duck-typed objects (pydantic models) may expose an economic_role hint.
    for attr in ("economic_role", "role", "type", "purpose", "hint"):
        value = getattr(payload_hint, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _normalize_hint(hint: str) -> str:
    lowered = hint.strip().lower()
    for ch in (" ", "-"):
        lowered = lowered.replace(ch, "_")
    while "__" in lowered:
        lowered = lowered.replace("__", "_")
    return lowered
