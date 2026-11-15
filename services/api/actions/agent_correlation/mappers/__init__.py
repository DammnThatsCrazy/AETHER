"""Vendor mapper registry.

A provider is a module with ``KINDS = {kind: (role or roles, mapper)}``. Adding
a vendor is adding a module here; the engine, join rules, projection, and
routes never name a vendor. The registry enforces that a mapper emits only the
roles it declared, so a mapper cannot quietly claim more trust than registered.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Mapping

from actions.agent_correlation.mappers import aether_mcp, cloudflare, openai_agents, ramp, shopify, stripe
from actions.agent_correlation.mappers._common import (
    AccountBinding,
    MapperContext,
    MappingError,
)
from shared.integration_contracts.correlation import CorrelationObservation
from shared.integration_contracts.source_roles import SOURCE_ROLES

Mapper = Callable[[MapperContext, Mapping[str, Any]], list[CorrelationObservation]]


@dataclass(frozen=True)
class RegisteredKind:
    provider: str
    kind: str
    roles: frozenset[str]
    mapper: Mapper


def _register(provider: str, module: ModuleType) -> dict[str, RegisteredKind]:
    kinds: dict[str, RegisteredKind] = {}
    for kind, (declared, fn) in module.KINDS.items():
        roles = frozenset(getattr(module, "ROLES", None) or ({declared} if isinstance(declared, str) else declared))
        if not roles <= set(SOURCE_ROLES):
            raise ValueError(f"{provider}.{kind} declares an unknown source role")
        kinds[kind] = RegisteredKind(provider=provider, kind=kind, roles=roles, mapper=fn)
    return kinds


PROVIDERS: Mapping[str, Mapping[str, RegisteredKind]] = {
    "shopify": _register("shopify", shopify),
    "stripe": _register("stripe", stripe),
    "ramp": _register("ramp", ramp),
    "cloudflare": _register("cloudflare", cloudflare),
    "openai": _register("openai", openai_agents),
    "aether_mcp": _register("aether_mcp", aether_mcp),
}


def registered(provider: str, kind: str) -> RegisteredKind:
    try:
        return PROVIDERS[provider][kind]
    except KeyError as exc:
        raise MappingError(f"no mapper for {provider}/{kind}") from exc


def map_record(provider: str, kind: str, ctx: MapperContext, record: Mapping[str, Any]) -> list[CorrelationObservation]:
    entry = registered(provider, kind)
    if not isinstance(record, Mapping):
        raise MappingError("record must be an object")
    observations = entry.mapper(ctx, record)
    for obs in observations:
        if obs.source_role not in entry.roles:
            raise MappingError(f"{provider}/{kind} emitted undeclared role {obs.source_role!r}")
        if obs.tenant_id != ctx.tenant_id:
            raise MappingError("mapper emitted an observation for another tenant")
    return observations


def catalog() -> list[dict[str, Any]]:
    return [
        {"provider": p, "kind": k, "roles": sorted(entry.roles)}
        for p, kinds in sorted(PROVIDERS.items())
        for k, entry in sorted(kinds.items())
    ]


__all__ = [
    "AccountBinding",
    "MapperContext",
    "MappingError",
    "PROVIDERS",
    "RegisteredKind",
    "catalog",
    "map_record",
    "registered",
]
