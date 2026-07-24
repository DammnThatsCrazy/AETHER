"""Per-tenant traffic-intelligence configuration (spec §15.4).

Tenants can tune source-link handling, classification aliases, and repair
policy without a deploy. Configuration is stored as one JSONB row per tenant in
``tenant_traffic_config`` and validated against the canonical
``generated_registry`` vocabulary: controlled extension only — a tenant may add
custom *aliases that resolve to* canonical enum values, but can never mint a new
canonical source_class / entry_method.

Everything here is additive. An absent config (or absent field) falls back to
the already-merged v1 behaviour; wiring points (classifier boundary, redirect)
only diverge from default when a tenant has explicitly configured a value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from shared.logger.logger import get_logger
from repositories.repos import get_pool
from services.traffic.generated_registry import (
    SOURCE_CLASSES,
    ENTRY_METHODS,
)

logger = get_logger("aether.traffic.config")

CONFIG_TABLE = "tenant_traffic_config"

# Controlled enums for policy fields (not canonical registry vocab, but fixed
# here so a tenant cannot set an arbitrary policy string).
INTERACTION_TRACKING_POLICIES = frozenset({"full", "standard", "minimal", "off"})
URL_SANITIZATION_POLICIES = frozenset({"strict", "standard", "off"})
DIRECT_TRAFFIC_POLICIES = frozenset({"direct_unknown", "suppress"})

# In-memory fallback (local/test only).
_local_config: dict[str, dict[str, Any]] = {}


def _reset_local_config() -> None:
    _local_config.clear()


class ConfigValidationError(ValueError):
    """Raised when a submitted config violates the canonical vocabulary."""


@dataclass
class TrafficConfig:
    """Validated per-tenant traffic configuration."""

    tenant_id: str
    source_link_domains: list[str] = field(default_factory=list)
    destination_allowlist: list[str] = field(default_factory=list)
    vanity_urls: dict[str, str] = field(default_factory=dict)
    placement_taxonomy: list[str] = field(default_factory=list)
    custom_source_aliases: dict[str, str] = field(default_factory=dict)
    custom_search_domains: dict[str, str] = field(default_factory=dict)
    custom_social_domains: dict[str, str] = field(default_factory=dict)
    interaction_tracking_policy: str = "standard"
    url_sanitization_policy: str = "standard"
    attribution_expiration_days: int = 30
    direct_traffic_policy: str = "direct_unknown"
    historical_repair_enabled: bool = True
    historical_repair_max_days: int = 365

    def to_payload(self) -> dict[str, Any]:
        """JSONB-safe config body (everything except tenant_id)."""
        return {
            "source_link_domains": self.source_link_domains,
            "destination_allowlist": self.destination_allowlist,
            "vanity_urls": self.vanity_urls,
            "placement_taxonomy": self.placement_taxonomy,
            "custom_source_aliases": self.custom_source_aliases,
            "custom_search_domains": self.custom_search_domains,
            "custom_social_domains": self.custom_social_domains,
            "interaction_tracking_policy": self.interaction_tracking_policy,
            "url_sanitization_policy": self.url_sanitization_policy,
            "attribution_expiration_days": self.attribution_expiration_days,
            "direct_traffic_policy": self.direct_traffic_policy,
            "historical_repair_enabled": self.historical_repair_enabled,
            "historical_repair_max_days": self.historical_repair_max_days,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"tenant_id": self.tenant_id, **self.to_payload()}

    def allows_destination(self, url: str) -> bool:
        """True when the destination host is permitted for this tenant.

        Empty allowlist == permissive (v1 default). A configured allowlist is
        an additive constraint matched on host suffix.
        """
        if not self.destination_allowlist:
            return True
        host = (urlsplit(url).hostname or "").lower()
        if not host:
            return False
        for allowed in self.destination_allowlist:
            allowed = allowed.lower().strip()
            if allowed and (host == allowed or host.endswith("." + allowed)):
                return True
        return False


def _norm_str_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigValidationError(f"{field_name} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigValidationError(f"{field_name} entries must be non-empty strings")
        out.append(item.strip())
    return out


def _norm_str_map(value: Any, field_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{field_name} must be an object")
    out: dict[str, str] = {}
    for key, val in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ConfigValidationError(f"{field_name} keys must be non-empty strings")
        if not isinstance(val, str) or not val.strip():
            raise ConfigValidationError(f"{field_name} values must be non-empty strings")
        out[key.strip().lower()] = val.strip()
    return out


def validate_config(tenant_id: str, payload: dict[str, Any]) -> TrafficConfig:
    """Validate a raw config payload against canonical vocabulary.

    Controlled extension: custom_source_aliases values MUST be canonical
    source_class members — a tenant extends the *input* vocabulary but never the
    canonical output enum. Unknown top-level keys are rejected so typos never
    silently no-op.
    """
    if not isinstance(payload, dict):
        raise ConfigValidationError("config must be an object")

    allowed_keys = set(TrafficConfig(tenant_id=tenant_id).to_payload().keys())
    unknown = set(payload) - allowed_keys
    if unknown:
        raise ConfigValidationError(f"unknown config field(s): {sorted(unknown)}")

    cfg = TrafficConfig(tenant_id=tenant_id)
    cfg.source_link_domains = _norm_str_list(
        payload.get("source_link_domains"), "source_link_domains"
    )
    cfg.destination_allowlist = _norm_str_list(
        payload.get("destination_allowlist"), "destination_allowlist"
    )
    cfg.vanity_urls = _norm_str_map(payload.get("vanity_urls"), "vanity_urls")
    cfg.placement_taxonomy = _norm_str_list(
        payload.get("placement_taxonomy"), "placement_taxonomy"
    )

    # Controlled extension: alias value must resolve to a canonical source_class.
    aliases = _norm_str_map(payload.get("custom_source_aliases"), "custom_source_aliases")
    for token, source_class in aliases.items():
        if source_class not in SOURCE_CLASSES:
            raise ConfigValidationError(
                f"custom_source_aliases['{token}'] -> '{source_class}' is not a "
                f"canonical source_class"
            )
    cfg.custom_source_aliases = aliases

    cfg.custom_search_domains = _norm_str_map(
        payload.get("custom_search_domains"), "custom_search_domains"
    )
    cfg.custom_social_domains = _norm_str_map(
        payload.get("custom_social_domains"), "custom_social_domains"
    )

    if "interaction_tracking_policy" in payload:
        pol = payload["interaction_tracking_policy"]
        if pol not in INTERACTION_TRACKING_POLICIES:
            raise ConfigValidationError(
                f"interaction_tracking_policy must be one of "
                f"{sorted(INTERACTION_TRACKING_POLICIES)}"
            )
        cfg.interaction_tracking_policy = pol

    if "url_sanitization_policy" in payload:
        pol = payload["url_sanitization_policy"]
        if pol not in URL_SANITIZATION_POLICIES:
            raise ConfigValidationError(
                f"url_sanitization_policy must be one of {sorted(URL_SANITIZATION_POLICIES)}"
            )
        cfg.url_sanitization_policy = pol

    if "direct_traffic_policy" in payload:
        pol = payload["direct_traffic_policy"]
        if pol not in DIRECT_TRAFFIC_POLICIES:
            raise ConfigValidationError(
                f"direct_traffic_policy must be one of {sorted(DIRECT_TRAFFIC_POLICIES)}"
            )
        cfg.direct_traffic_policy = pol

    if "attribution_expiration_days" in payload:
        cfg.attribution_expiration_days = _validate_positive_int(
            payload["attribution_expiration_days"], "attribution_expiration_days", 1, 3650
        )
    if "historical_repair_max_days" in payload:
        cfg.historical_repair_max_days = _validate_positive_int(
            payload["historical_repair_max_days"], "historical_repair_max_days", 1, 3650
        )
    if "historical_repair_enabled" in payload:
        val = payload["historical_repair_enabled"]
        if not isinstance(val, bool):
            raise ConfigValidationError("historical_repair_enabled must be a boolean")
        cfg.historical_repair_enabled = val

    return cfg


def _validate_positive_int(value: Any, field_name: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigValidationError(f"{field_name} must be an integer")
    if value < lo or value > hi:
        raise ConfigValidationError(f"{field_name} must be between {lo} and {hi}")
    return value


class TenantTrafficConfigRepository:
    """Durable per-tenant traffic config (one JSONB row per tenant)."""

    async def _pool(self):
        return await get_pool()

    async def get(self, tenant_id: str) -> TrafficConfig:
        """Return the tenant config, or defaults when none is stored."""
        pool = await self._pool()
        if pool is None:
            stored = _local_config.get(tenant_id)
            if stored is None:
                return TrafficConfig(tenant_id=tenant_id)
            return validate_config(tenant_id, dict(stored))
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT config FROM {CONFIG_TABLE} WHERE tenant_id = $1", tenant_id
            )
        if row is None:
            return TrafficConfig(tenant_id=tenant_id)
        payload = row["config"]
        if isinstance(payload, str):
            import json

            payload = json.loads(payload)
        return validate_config(tenant_id, dict(payload or {}))

    async def upsert(self, cfg: TrafficConfig) -> TrafficConfig:
        payload = cfg.to_payload()
        now = datetime.now(timezone.utc)
        pool = await self._pool()
        if pool is None:
            _local_config[cfg.tenant_id] = dict(payload)
            return cfg
        import json

        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {CONFIG_TABLE} (tenant_id, config, created_at, updated_at)
                VALUES ($1, $2::jsonb, $3, $3)
                ON CONFLICT (tenant_id)
                DO UPDATE SET config = EXCLUDED.config, updated_at = EXCLUDED.updated_at
                """,
                cfg.tenant_id, json.dumps(payload), now,
            )
        return cfg

    async def delete(self, tenant_id: str) -> bool:
        pool = await self._pool()
        if pool is None:
            return _local_config.pop(tenant_id, None) is not None
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {CONFIG_TABLE} WHERE tenant_id = $1", tenant_id
            )
        return result.endswith("1")


__all__ = [
    "CONFIG_TABLE",
    "TrafficConfig",
    "TenantTrafficConfigRepository",
    "ConfigValidationError",
    "validate_config",
    "INTERACTION_TRACKING_POLICIES",
    "URL_SANITIZATION_POLICIES",
    "DIRECT_TRAFFIC_POLICIES",
]
