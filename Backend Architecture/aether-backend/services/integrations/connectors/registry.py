"""Connector registry — single source of truth for available connectors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from services.integrations.connectors.adapters import ALL_CONNECTORS
from services.integrations.connectors.base import BaseConnector, now_iso
from services.integrations.consent_policy import integration_governance_descriptor

CONNECTORS: dict[str, BaseConnector] = {c.connector_type: c() for c in ALL_CONNECTORS}

# Legacy connectors eligible for per-provider decommission (WS7). Only Shopify
# carries a legacy connector in this build — the six new providers ship no
# legacy connector — so the decommissionable set is intentionally minimal and
# enforced as an explicit frozenset (never core-first).
DECOMMISSIONABLE_CONNECTOR_TYPES: frozenset[str] = frozenset({"shopify"})

# Audit ledger: connector_type -> ISO-8601 UTC timestamp of the first (and only)
# successful retirement. A repeat call is a safe idempotent no-op that preserves
# the original timestamp.
#
# RETIREMENT IS PROCESS-LOCAL (F-3): ``_RETIRED_AT`` is an in-memory ledger, so a
# process restart resets it and the decommission no longer applies. Persisting
# the ledger across restarts is a documented follow-on, deliberately OUT OF SCOPE
# for this pass. What IS wired in-process: ``get_connector`` resolves a retired
# type to None and ``list_descriptors``/``descriptor_for`` skip retired types,
# so the marker has real operational effect while the process lives (WS7).
_RETIRED_AT: dict[str, str] = {}


@dataclass(frozen=True)
class RetireResult:
    """Typed outcome of ``retire_connector_type`` — never raises."""

    connector_type: str
    ok: bool
    status: str  # "retired" | "already_retired" | "unknown" | "not_eligible"
    detail: str
    retired_at: str | None = None  # ISO-8601 UTC timestamp, set on retirement


def get_connector(connector_type: str) -> BaseConnector | None:
    connector = CONNECTORS.get(connector_type)
    if connector is None:
        return None
    # WS7 retire consumption (F-3): a retired type resolves as if absent, so
    # decommission has real in-process effect — sync/test/descriptor all fail
    # with the connector-not-found shape while the process lives.
    if is_retired(connector_type):
        return None
    return connector


def is_retired(connector_type: str) -> bool:
    """True when ``connector_type`` has been retired in this process."""
    return connector_type in _RETIRED_AT


def retire_connector_type(
    registry_state: Mapping[str, BaseConnector],
    connector_type: str,
) -> RetireResult:
    """Retire a legacy connector per-provider (WS7); idempotent + auditable.

    - Unknown ``connector_type`` (absent from ``registry_state``) returns a
      typed ``unknown`` result — never a silent no-op, never a raise.
    - A type outside ``DECOMMISSIONABLE_CONNECTOR_TYPES`` returns a typed
      ``not_eligible`` result — the decommission applies to Shopify only and
      never to core or other per-provider connectors.
    - The first successful retirement is recorded in the in-memory
      ``_RETIRED_AT`` ledger; a repeat call is a stable ``already_retired``
      no-op that preserves the original ``retired_at``.
    - No other connector type is ever touched (per-provider, never core-first);
      ``registry_state`` itself is not mutated.
    """
    if connector_type not in registry_state:
        return RetireResult(
            connector_type=connector_type,
            ok=False,
            status="unknown",
            detail=f"unknown connector type: {connector_type}",
        )
    if connector_type not in DECOMMISSIONABLE_CONNECTOR_TYPES:
        return RetireResult(
            connector_type=connector_type,
            ok=False,
            status="not_eligible",
            detail=f"{connector_type} has no legacy connector to decommission",
        )
    retired_at = _RETIRED_AT.get(connector_type)
    if retired_at is not None:
        return RetireResult(
            connector_type=connector_type,
            ok=True,
            status="already_retired",
            detail=f"{connector_type} already retired",
            retired_at=retired_at,
        )
    retired_at = now_iso()
    _RETIRED_AT[connector_type] = retired_at
    return RetireResult(
        connector_type=connector_type,
        ok=True,
        status="retired",
        detail=f"{connector_type} decommissioned",
        retired_at=retired_at,
    )


def descriptor_for(connector_type: str) -> dict | None:
    connector = get_connector(connector_type)
    if connector is None:
        return None
    return {
        **connector.descriptor().model_dump(),
        **integration_governance_descriptor(connector_type),
    }


def list_descriptors() -> list[dict]:
    descriptors: list[dict] = []
    for connector_type in CONNECTORS:
        # WS7 retire consumption (F-3): skip retired types so decommission is
        # reflected in the catalog surface while the process lives.
        if is_retired(connector_type):
            continue
        descriptor = descriptor_for(connector_type)
        if descriptor is not None:
            descriptors.append(descriptor)
    return descriptors
