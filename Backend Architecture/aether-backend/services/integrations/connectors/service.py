"""Connector service — tenant-scoped config + test/sync/webhook ingestion.

Side effects (audit ledger, usage metering, sync-status health) are owned here,
not in adapters, and are all best-effort (never break the request). Secrets are
never persisted in config or returned. Connectors are disabled by default and
gated by feature flags.
"""
from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.logger.logger import get_logger

from services.integrations.connectors.base import (
    ConnectionTestResult,
    ConnectorConfig,
    NormalizedEvent,
    SyncResult,
    now_iso,
)
from services.integrations.connectors.registry import CONNECTORS, get_connector, list_descriptors

logger = get_logger("aether.service.connectors")

# Secret-like keys that must never be persisted into the non-secret config blob.
_SECRET_KEYS = ("secret", "token", "api_key", "apikey", "password", "credential", "private_key")


class ConnectorConfigRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("integration_connector_configs")


_configs = ConnectorConfigRepository()


def _key(tenant_id: str, connector_type: str) -> str:
    return f"{tenant_id}:{connector_type}"


def _strip_secrets(config: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in (config or {}).items()
            if not any(s in k.lower() for s in _SECRET_KEYS)}


async def _meter(tenant_id: str, event_type: str, source_id: str | None, source_type: str) -> None:
    try:
        from services.billing.revops import (
            MeteringService, UsageMeteringEvent, UsageMeteringEventRepository,
        )
        svc = MeteringService(UsageMeteringEventRepository())
        await svc.record_event(UsageMeteringEvent(
            tenant_id=tenant_id, event_type=event_type, source_id=source_id,
            source_type=source_type, occurred_at=now_iso(),
        ))
    except Exception as exc:  # pragma: no cover - metering must never break flow
        logger.warning(f"connector metering failed: {exc}")


async def _audit(tenant_id: str, actor_id: str, actor_type: str, event_type: str,
                 connector_type: str, outcome: str, metadata: dict[str, Any] | None = None) -> None:
    try:
        from services.security.audit_ledger import audit_ledger
        await audit_ledger.record(
            actor_id=actor_id, actor_type=actor_type,  # type: ignore[arg-type]
            event_type=event_type, resource_type="connector", resource_id=connector_type,
            action="configure" if "config" in event_type else "ingest",
            outcome=outcome,  # type: ignore[arg-type]
            tenant_id=tenant_id, metadata=metadata or {},
        )
    except Exception as exc:  # pragma: no cover - audit must never break flow
        logger.warning(f"connector audit failed: {exc}")


class ConnectorService:
    def __init__(self) -> None:
        self.repo = _configs
        self._providers: Any = None

    def _providers_repo(self):
        if self._providers is None:
            from repositories.repos import ProvidersRepository
            self._providers = ProvidersRepository()
        return self._providers

    async def _resolve_secret(self, config: ConnectorConfig) -> Optional[str]:
        """Look up the stored credential value from the vault via secret_ref."""
        if not config.secret_ref:
            return None
        try:
            record = await self._providers_repo().find_by_id(config.secret_ref)
            if record:
                return record.get("credential_value")
        except Exception as exc:
            logger.warning(f"Secret resolution failed for {config.connector_type}: {exc}")
        return None

    async def list_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        """Descriptors merged with this tenant's config/status (no secrets)."""
        rows = {r["connector_type"]: r for r in await self.repo.find_many(
            filters={"tenant_id": tenant_id}, limit=1000)}
        out: list[dict[str, Any]] = []
        for desc in list_descriptors():
            cfg = rows.get(desc["connector_type"])
            out.append({
                **desc,
                "enabled": bool(cfg["enabled"]) if cfg else False,
                "secret_configured": bool(cfg["secret_configured"]) if cfg else False,
                "sync_status": cfg["sync_status"] if cfg else "never_synced",
                "last_synced_at": cfg.get("last_synced_at") if cfg else None,
                "name": cfg.get("name") if cfg else desc["label"],
            })
        return out

    async def get(self, tenant_id: str, connector_type: str) -> dict[str, Any] | None:
        return await self.repo.find_by_id(_key(tenant_id, connector_type))

    async def configure(self, tenant_id: str, connector_type: str, *, name: str = "",
                         config: dict[str, Any] | None = None, enabled: bool | None = None,
                         secret_configured: bool | None = None, actor_id: str = "system") -> dict[str, Any]:
        connector = get_connector(connector_type)
        if connector is None:
            raise ValueError(f"unknown connector {connector_type}")
        key = _key(tenant_id, connector_type)
        existing = await self.repo.find_by_id(key)
        record = ConnectorConfig(**existing) if existing else ConnectorConfig(
            tenant_id=tenant_id, connector_type=connector_type)  # type: ignore[arg-type]
        if name:
            record.name = name
        if config is not None:
            record.config = _strip_secrets(config)  # never persist secrets
        if enabled is not None:
            record.enabled = enabled
        if secret_configured is not None:
            record.secret_configured = secret_configured
        record.updated_at = now_iso()
        connector.validate_config(record)
        stored = await self.repo.insert(key, record.model_dump())
        await self._audit_config(tenant_id, actor_id, connector_type, record.enabled)
        return stored

    async def _audit_config(self, tenant_id: str, actor_id: str, connector_type: str, enabled: bool) -> None:
        await _audit(tenant_id, actor_id, "tenant_user", "connector_config_changed",
                     connector_type, "allowed", {"enabled": enabled})

    async def test(self, tenant_id: str, connector_type: str) -> ConnectionTestResult:
        connector = get_connector(connector_type)
        if connector is None:
            raise ValueError(f"unknown connector {connector_type}")
        cfg = await self.repo.find_by_id(_key(tenant_id, connector_type))
        config = ConnectorConfig(**cfg) if cfg else ConnectorConfig(
            tenant_id=tenant_id, connector_type=connector_type)  # type: ignore[arg-type]
        secret = await self._resolve_secret(config)
        return await connector.test_connection(config, secret=secret)

    async def sync(self, tenant_id: str, connector_type: str, *, actor_id: str = "system",
                   since: Optional[str] = None) -> SyncResult:
        connector = get_connector(connector_type)
        if connector is None:
            raise ValueError(f"unknown connector {connector_type}")
        key = _key(tenant_id, connector_type)
        cfg = await self.repo.find_by_id(key)
        config = ConnectorConfig(**cfg) if cfg else ConnectorConfig(
            tenant_id=tenant_id, connector_type=connector_type)  # type: ignore[arg-type]
        if not config.enabled:
            return SyncResult(connector_type=connector_type, status="disabled", detail="connector disabled")  # type: ignore[arg-type]
        secret = await self._resolve_secret(config)
        events = await connector.pull(config, since=since, secret=secret)
        status = "healthy"
        # Persist sync status (this is the connector's reliability/health signal).
        config.last_synced_at = now_iso()
        config.sync_status = status
        config.updated_at = now_iso()
        await self.repo.insert(key, config.model_dump())
        await _meter(tenant_id, "connector_sync", connector_type, "connector")
        await _audit(tenant_id, actor_id, "system", "connector_sync", connector_type, "allowed",
                     {"events": len(events)})
        return SyncResult(connector_type=connector_type, status=status,  # type: ignore[arg-type]
                          events_ingested=len(events), events=events,
                          detail="mocked sync (no external API in local mode)")

    async def ingest_webhook(self, connector_type: str, tenant_id: str, *, raw_body: bytes,
                             signature: Optional[str] = None, timestamp: Optional[str] = None,
                             secret: Optional[str] = None) -> dict[str, Any]:
        connector = get_connector(connector_type)
        if connector is None:
            raise ValueError(f"unknown connector {connector_type}")
        cfg = await self.repo.find_by_id(_key(tenant_id, connector_type))
        config = ConnectorConfig(**cfg) if cfg else None
        if config is None or not config.enabled:
            return {"accepted": False, "reason": "connector disabled", "events_ingested": 0}
        verified = False
        if secret:
            from services.security.integration_security import verify_signature
            if not (signature and timestamp and verify_signature(secret, raw_body, timestamp, signature)):
                await _audit(tenant_id, "system", "system", "connector_webhook_ingested",
                             connector_type, "blocked", {"reason": "invalid signature"})
                return {"accepted": False, "reason": "invalid signature", "events_ingested": 0}
            verified = True
        import json
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"accepted": False, "reason": "invalid payload", "events_ingested": 0}
        events = connector.parse_webhook(payload if isinstance(payload, dict) else {"items": payload})
        await _meter(tenant_id, "webhook_ingested", connector_type, "connector")
        await _audit(tenant_id, "system", "system", "connector_webhook_ingested", connector_type,
                     "allowed", {"events": len(events), "verified": verified})
        return {"accepted": True, "verified": verified, "events_ingested": len(events),
                "events": [e.model_dump() for e in events]}

    async def overview(self) -> dict[str, Any]:
        """Aggregate-only connector status across all tenants (Kyber)."""
        rows = await self.repo.find_many(limit=10000)
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        by_type_detail: dict[str, dict[str, Any]] = {}
        for r in rows:
            ctype = r["connector_type"]
            if ctype not in by_type_detail:
                by_type_detail[ctype] = {
                    "enabled_count": 0,
                    "error_count": 0,
                    "last_synced_at": None,
                }
            detail = by_type_detail[ctype]
            if r.get("sync_status") in ("failed", "degraded"):
                detail["error_count"] += 1
            lsa = r.get("last_synced_at")
            if lsa and (detail["last_synced_at"] is None or lsa > detail["last_synced_at"]):
                detail["last_synced_at"] = lsa
            if r.get("enabled"):
                by_status[r.get("sync_status", "never_synced")] = by_status.get(r.get("sync_status", "never_synced"), 0) + 1
                by_type[ctype] = by_type.get(ctype, 0) + 1
                detail["enabled_count"] += 1
        return {
            "available_connectors": len(CONNECTORS),
            "configured_count": len(rows),
            "enabled_count": sum(1 for r in rows if r.get("enabled")),
            "enabled_by_status": by_status,
            "enabled_by_type": by_type,
            "by_type_detail": by_type_detail,
        }


connector_service = ConnectorService()
