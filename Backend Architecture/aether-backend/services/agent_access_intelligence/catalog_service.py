"""Capability catalog service (PR 2, Phase A).

Maintains the ``capability_catalog`` + ``capability_installations`` inventory as a
materialization upserted from the agent-execution fact stream. The core entry point is
``record_from_fact(row)`` — fed either a live ``silver_agent_execution_facts`` projection
row (snake_case fields present) or a persisted/re-queried row (fields only in ``payload``
camelCase). ``maybe_record(result, event)`` is the out-of-band dispatcher hook
(fire-and-forget, never raises) that mirrors ``SilverGraphProjector.maybe_emit``.

Reads are tenant-scoped; single-record reads are fail-closed (tenant compared → NotFound on
mismatch). Kyber operator reads aggregate across tenants and are exposed only through the
operator-gated routes.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from shared.common.common import NotFoundError
from shared.logger.logger import get_logger

from .models import (
    Capability,
    CapabilityInstallation,
    CapabilityKind,
    capability_id_for,
    clamp_capability_ids,
    clamp_dedup_ids,
    clamp_event_ids,
    installation_id_for,
)
from .repositories import CapabilityCatalogRepository, CapabilityInstallationRepository

logger = get_logger("aether.service.agent_access_intelligence.catalog")

_SILVER_FACT_TABLE = "silver_agent_execution_facts"

# Specificity ranking used when re-observation could upgrade an "unknown" kind to a
# concrete one (or vice-versa — a later, less specific observation never downgrades).
_KIND_SPECIFICITY = {
    CapabilityKind.UNKNOWN.value: 0,
    CapabilityKind.RESOURCE.value: 1,
    CapabilityKind.ACCOUNT.value: 2,
    CapabilityKind.PROVIDER_ACTION.value: 3,
    CapabilityKind.MCP_TOOL.value: 4,
}

# Event-name fragments that indicate an external account/portfolio reach rather than a
# tool call.
_ACCOUNT_EVENT_FRAGMENTS = ("account", "portfolio", "position", "trade", "brokerage", "budget")


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# Query-string keys that must never be persisted verbatim in a server URL. The PR 1
# ingestion scrubber is key-name based and does not sanitize secrets embedded in a URL
# *value*, so this store (which creates durable catalog rows + a tenant/operator read
# surface for server_url) redacts them itself before persisting.
_SENSITIVE_QS_KEYS = frozenset({
    "token", "access_token", "refresh_token", "id_token", "session", "session_token",
    "sessionid", "apikey", "api_key", "key", "secret", "client_secret", "password", "pwd",
    "auth", "authorization", "bearer", "sig", "signature", "credential", "credentials",
})


def _sanitize_server_url(url: Optional[str]) -> Optional[str]:
    """Strip credentials from an observed server URL before it is stored/served.

    Removes any ``user:pass@`` userinfo from the authority and redacts sensitive query
    parameters (token/apikey/secret/…). A value that cannot be parsed as a URL is returned
    unchanged (it is treated as an opaque server name, which carries no userinfo/query)."""
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.scheme and "@" not in parts.netloc:
        # Not a URL (opaque server name) — nothing credential-bearing to strip.
        return url
    netloc = parts.netloc.rsplit("@", 1)[-1] if "@" in parts.netloc else parts.netloc
    query = parts.query
    if query:
        query = urlencode(
            [
                (k, "REDACTED" if k.strip().lower() in _SENSITIVE_QS_KEYS else v)
                for k, v in parse_qsl(query, keep_blank_values=True)
            ]
        )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def _fact_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a fact row to the fields the catalog needs.

    Prefers the projector's snake_case top-level keys, falling back to the ``payload``
    JSONB (event ``properties``, camelCase) — so the same code is correct for a live
    projection row and a persisted silver row (where the writer dropped the snake_case
    keys and only ``payload`` survived)."""
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}

    def pick(snake: str, camel: str) -> Optional[str]:
        return _clean(row.get(snake)) or _clean(payload.get(camel))

    return {
        "tenant_id": _clean(row.get("tenant_id")) or "default",
        "source_event_id": _clean(row.get("source_event_id")) or _clean(row.get("messageId")),
        "event_name": _clean(row.get("event_name"))
        or _clean(row.get("source_event_type"))
        or _clean(row.get("type")),
        "occurred_at": _clean(row.get("occurred_at")) or _clean(row.get("timestamp")),
        "provider": pick("provider", "provider"),
        "tool_name": pick("tool_name", "toolName"),
        "server_name": pick("server_name", "serverName"),
        "server_url": _sanitize_server_url(pick("server_url", "serverUrl")),
        "protocol_version": pick("protocol_version", "protocolVersion"),
        "risk_level": pick("risk_level", "riskLevel"),
        "agent_id": _clean(row.get("agent_id")) or _clean(payload.get("agentId")),
    }


def _server_key(f: dict[str, Any]) -> Optional[str]:
    return f.get("server_name") or f.get("server_url")


def _derive_kind(f: dict[str, Any]) -> CapabilityKind:
    tool = f.get("tool_name")
    server = _server_key(f)
    event = (f.get("event_name") or "").lower()
    if tool and server:
        return CapabilityKind.MCP_TOOL
    if tool:
        return CapabilityKind.PROVIDER_ACTION
    if any(fragment in event for fragment in _ACCOUNT_EVENT_FRAGMENTS):
        return CapabilityKind.ACCOUNT
    if server:
        return CapabilityKind.RESOURCE
    return CapabilityKind.UNKNOWN


def _should_record(f: dict[str, Any], kind: CapabilityKind) -> bool:
    """Only inventory rows that identify an external capability. Generic agent-lifecycle
    events (e.g. ``agent_task_started``) with no provider/server/tool are not capabilities."""
    if f.get("tool_name") or f.get("server_name") or f.get("server_url"):
        return True
    return kind == CapabilityKind.ACCOUNT and bool(f.get("provider"))


def _prefer_kind(prior: Optional[str], new: CapabilityKind) -> CapabilityKind:
    if not prior:
        return new
    if _KIND_SPECIFICITY.get(new.value, 0) >= _KIND_SPECIFICITY.get(prior, 0):
        return new
    try:
        return CapabilityKind(prior)
    except ValueError:
        return new


def _max_ts(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if a and b:
        return a if a >= b else b
    return a or b


class CapabilityCatalogService:
    def __init__(
        self,
        catalog_repo: Optional[CapabilityCatalogRepository] = None,
        installation_repo: Optional[CapabilityInstallationRepository] = None,
    ) -> None:
        self._catalog = catalog_repo or CapabilityCatalogRepository()
        self._installations = installation_repo or CapabilityInstallationRepository()

    # ------------------------------------------------------------------
    # Ingestion (materialization)
    # ------------------------------------------------------------------

    async def record_from_fact(self, row: dict[str, Any]) -> dict[str, Any]:
        """Upsert the capability + installation implied by one agent-execution fact row.

        Row identity is exactly-once (deterministic ``capability_id``/``installation_id``), so a
        replay never creates a duplicate row. ``observation_count`` is deduplicated over a
        BOUNDED recent window of source-event ids (``_MAX_DEDUP_EVENT_IDS``): a redelivery within
        that window does not double-count; a redelivery older than the window may be counted
        again. It is a bounded-window observation count, not an exactly-once counter. Returns a
        small result dict for observability/tests."""
        f = _fact_fields(row)
        kind = _derive_kind(f)
        if not _should_record(f, kind):
            return {"recorded": False, "reason": "no_capability_signal"}

        cap_id = await self._upsert_capability(f, kind)
        inst_id = await self._upsert_installation(f, cap_id)
        return {
            "recorded": True,
            "capability_id": cap_id,
            "installation_id": inst_id,
            "capability_kind": kind.value,
        }

    async def maybe_record(self, result: Any, event: Any) -> None:  # noqa: ARG002 — parity with maybe_emit
        """Out-of-band dispatcher hook. Never raises (fire-and-forget)."""
        try:
            if getattr(result, "table", None) != _SILVER_FACT_TABLE:
                return
            for row in getattr(result, "rows", None) or []:
                if isinstance(row, dict):
                    await self.record_from_fact(row)
        except Exception as exc:  # pragma: no cover — must never break Silver
            logger.warning("capability_catalog maybe_record failed: %s", exc)

    async def _upsert_capability(self, f: dict[str, Any], kind: CapabilityKind) -> str:
        tenant_id = f["tenant_id"]
        cap_id = capability_id_for(tenant_id, f.get("provider"), _server_key(f), f.get("tool_name"))
        existing = await self._catalog.find_by_id(cap_id)
        sid = f.get("source_event_id")
        # Dedup over a bounded window kept SEPARATE from the small display sample, so the
        # 25-item provenance list never shrinks the replay-dedup guarantee.
        prior_dedup = list((existing or {}).get("_dedup_source_event_ids") or [])
        prior_samples = list((existing or {}).get("sample_source_event_ids") or [])
        is_replay = bool(sid and sid in prior_dedup)
        prior_count = int((existing or {}).get("observation_count") or 0)

        dedup_ids = prior_dedup
        samples = prior_samples
        if sid and not is_replay:
            dedup_ids = clamp_dedup_ids([sid] + [s for s in prior_dedup if s != sid])
            samples = clamp_event_ids([sid] + [s for s in prior_samples if s != sid])

        record = Capability(
            capability_id=cap_id,
            tenant_id=tenant_id,
            capability_kind=_prefer_kind((existing or {}).get("capability_kind"), kind),
            provider=f.get("provider") or (existing or {}).get("provider"),
            server_name=f.get("server_name") or (existing or {}).get("server_name"),
            server_url=f.get("server_url") or (existing or {}).get("server_url"),
            tool_name=f.get("tool_name") or (existing or {}).get("tool_name"),
            protocol_version=f.get("protocol_version") or (existing or {}).get("protocol_version"),
            latest_risk_level=f.get("risk_level") or (existing or {}).get("latest_risk_level"),
            first_seen_at=(existing or {}).get("first_seen_at") or f.get("occurred_at"),
            last_seen_at=_max_ts((existing or {}).get("last_seen_at"), f.get("occurred_at")),
            observation_count=prior_count if is_replay else prior_count + 1,
            sample_source_event_ids=samples,
        )
        payload = record.model_dump(mode="json")
        # Private bounded replay-dedup window (stripped from public API output by _public).
        payload["_dedup_source_event_ids"] = dedup_ids
        await self._catalog.insert(cap_id, payload)
        return cap_id

    async def _upsert_installation(self, f: dict[str, Any], cap_id: str) -> Optional[str]:
        server_key = _server_key(f)
        agent_id = f.get("agent_id")
        if not (agent_id and server_key):
            return None
        tenant_id = f["tenant_id"]
        inst_id = installation_id_for(tenant_id, agent_id, server_key)
        existing = await self._installations.find_by_id(inst_id)
        sid = f.get("source_event_id")
        prior_dedup = list((existing or {}).get("_dedup_source_event_ids") or [])
        is_replay = bool(sid and sid in prior_dedup)
        prior_count = int((existing or {}).get("observation_count") or 0)
        if sid and not is_replay:
            prior_dedup = clamp_dedup_ids([sid] + [s for s in prior_dedup if s != sid])

        prior_caps = list((existing or {}).get("capability_ids") or [])
        cap_ids = clamp_capability_ids([cap_id] + [c for c in prior_caps if c != cap_id])

        record = CapabilityInstallation(
            installation_id=inst_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            provider=f.get("provider") or (existing or {}).get("provider"),
            server_name=f.get("server_name") or (existing or {}).get("server_name"),
            server_url=f.get("server_url") or (existing or {}).get("server_url"),
            protocol_version=f.get("protocol_version") or (existing or {}).get("protocol_version"),
            first_seen_at=(existing or {}).get("first_seen_at") or f.get("occurred_at"),
            last_seen_at=_max_ts((existing or {}).get("last_seen_at"), f.get("occurred_at")),
            observation_count=prior_count if is_replay else prior_count + 1,
            capability_ids=cap_ids,
        )
        payload = record.model_dump(mode="json")
        # Private bounded replay-dedup window (stripped from public API output by _public).
        payload["_dedup_source_event_ids"] = prior_dedup
        await self._installations.insert(inst_id, payload)
        return inst_id

    # ------------------------------------------------------------------
    # Tenant reads (fail-closed)
    # ------------------------------------------------------------------

    async def list_capabilities(
        self,
        tenant_id: str,
        *,
        provider: Optional[str] = None,
        server_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        rows = await self._catalog.list_capabilities(
            tenant_id,
            provider=provider,
            server_name=server_name,
            tool_name=tool_name,
            limit=limit,
            offset=offset,
        )
        return [self._public(r) for r in rows]

    async def get_capability(self, tenant_id: str, capability_id: str) -> dict:
        rec = await self._catalog.find_by_id(capability_id)
        if not rec or str(rec.get("tenant_id")) != str(tenant_id):
            raise NotFoundError("capability")
        return self._public(rec)

    async def list_installations(
        self,
        tenant_id: str,
        *,
        agent_id: Optional[str] = None,
        provider: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        rows = await self._installations.list_installations(
            tenant_id, agent_id=agent_id, provider=provider, limit=limit, offset=offset
        )
        return [self._public(r) for r in rows]

    async def get_installation(self, tenant_id: str, installation_id: str) -> dict:
        rec = await self._installations.find_by_id(installation_id)
        if not rec or str(rec.get("tenant_id")) != str(tenant_id):
            raise NotFoundError("capability_installation")
        return self._public(rec)

    async def catalog_overview(self, tenant_id: str) -> dict:
        capability_count = await self._catalog.count({"tenant_id": tenant_id})
        installation_count = await self._installations.count({"tenant_id": tenant_id})
        caps = await self._catalog.list_for_tenant(tenant_id, limit=1000)
        by_kind = Counter(c.get("capability_kind") for c in caps)
        by_provider = Counter(c.get("provider") for c in caps if c.get("provider"))
        return {
            "tenant_id": tenant_id,
            "capability_count": capability_count,
            "installation_count": installation_count,
            "by_kind": dict(by_kind),
            "by_provider": dict(by_provider),
            # The breakdown is computed over a bounded sample; disclose when it is partial
            # rather than presenting a silently-truncated distribution as complete.
            "sampled": len(caps) < capability_count,
        }

    # ------------------------------------------------------------------
    # Kyber operator reads (cross-tenant aggregate; operator-gated at the route)
    # ------------------------------------------------------------------

    async def catalog_health(self) -> dict:
        total_capabilities = await self._catalog.count()
        total_installations = await self._installations.count()
        caps = await self._catalog.list_all(limit=2000)
        by_tenant = Counter(c.get("tenant_id") for c in caps)
        by_kind = Counter(c.get("capability_kind") for c in caps)
        return {
            "total_capabilities": total_capabilities,
            "total_installations": total_installations,
            "tenant_count": len(by_tenant),
            "by_kind": dict(by_kind),
            "top_tenants": by_tenant.most_common(20),
            "sampled": len(caps) < total_capabilities,
        }

    async def catalog_unattributed(self, limit: int = 200) -> dict:
        """Honest Phase-A precursor to shadow detection (§9.8 is full Phase C): capabilities
        observed with no provider identity and an unknown kind — i.e. reachable but
        unattributed. Not a claim of endpoint discovery."""
        caps = await self._catalog.list_all(limit=max(limit, 1))
        unattributed = [
            c
            for c in caps
            if not c.get("provider") and (c.get("capability_kind") == CapabilityKind.UNKNOWN.value)
        ]
        return {
            "count": len(unattributed),
            "items": [self._public(c) for c in unattributed[:limit]],
        }

    @staticmethod
    def _public(rec: dict) -> dict:
        """Strip private/internal fields (leading underscore) from an API-facing record."""
        return {k: v for k, v in rec.items() if not k.startswith("_")}


capability_catalog_service = CapabilityCatalogService()
