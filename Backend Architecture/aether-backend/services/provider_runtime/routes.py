"""Universal Provider Runtime — API routers.

* ``router`` (``/v1/provider-connections``) — tenant-scoped provider connection
  lifecycle: providers, connections, credentials, test, accounts, sync, health,
  raw records.
* ``admin_router`` (``/v1/admin/kyber/provider-connections``) — operator-gated,
  aggregate-only Kyber views (overview / health / certify / tenant drill-down).
* ``webhook_public_router`` (``/v1/provider-webhooks``) — UNAUTHENTICATED by API
  key (listed in ``PUBLIC_PATH_PREFIXES``); security is enforced inside the
  handler via provider signature verification.

Every tenant route mirrors the auth dependency pattern from
``services/integrations/connectors/routes.py``. Errors surface ONLY
``ProviderRuntimeError.safe_message`` (Team D) — never ``details`` or raw
exception text — with a proper HTTP status.

Routers are importable WITHOUT the feature flag (the flag only controls mounting
in main.py). Orchestrators/gateways are constructor-injected singletons resolved
lazily so tests can inject fakes by patching the accessors below.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from shared.common.common import (
    AetherError,
    APIResponse,
    BadRequestError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    utc_now,
)
from shared.integration_contracts.lifecycle import ConnectionState
from shared.logger.logger import get_logger

logger = get_logger("aether.provider_runtime.routes")


def _now_iso() -> str:
    """Current UTC time in ISO-8601 form (caller-supplied timestamps)."""
    return utc_now().isoformat()


router = APIRouter(prefix="/v1/provider-connections", tags=["Provider Runtime — Connections"])
admin_router = APIRouter(
    prefix="/v1/admin/kyber/provider-connections", tags=["Admin — Kyber Provider Runtime"]
)
# Public webhook router — no API key auth; signature-verified in the gateway.
webhook_public_router = APIRouter(
    prefix="/v1/provider-webhooks", tags=["Provider Runtime — Webhooks"]
)

_MAX_LIST_LIMIT = 200


# ── Dependency seam (module singletons; tests inject fakes) ────────────────

_REGISTRY: Any = None
_ORCHESTRATOR: Any = None
_COORDINATOR: Any = None
_GATEWAY: Any = None
_HEALTH_ENGINE: Any = None


def _get_registry() -> Any:
    """The provider registry singleton (Team C: ``provider_registry``)."""
    global _REGISTRY
    if _REGISTRY is None:
        from services.provider_runtime import registry as _registry_module

        _REGISTRY = getattr(
            _registry_module, "provider_registry",
            getattr(_registry_module, "registry", None),
        )
        if _REGISTRY is None:
            raise ImportError(
                "services.provider_runtime.registry exposes neither "
                "'provider_registry' nor 'registry'"
            )
    return _REGISTRY


def _get_orchestrator() -> Any:
    """The connection orchestrator singleton (Team D: ``ConnectionOrchestrator``)."""
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        from services.provider_runtime.connection import ConnectionOrchestrator

        _ORCHESTRATOR = ConnectionOrchestrator()
    return _ORCHESTRATOR


def _get_coordinator() -> Any:
    """The acquisition coordinator singleton (Team D: ``AcquisitionCoordinator``)."""
    global _COORDINATOR
    if _COORDINATOR is None:
        from services.provider_runtime.acquisition import AcquisitionCoordinator

        _COORDINATOR = AcquisitionCoordinator()
    return _COORDINATOR


def _get_gateway() -> Any:
    """The webhook gateway singleton (Team E: ``WebhookGateway``)."""
    global _GATEWAY
    if _GATEWAY is None:
        from services.provider_runtime.webhook import WebhookGateway

        _GATEWAY = WebhookGateway()
    return _GATEWAY


def _get_health_engine() -> Any:
    """The health engine singleton (Team E: ``HealthEngine``)."""
    global _HEALTH_ENGINE
    if _HEALTH_ENGINE is None:
        from services.provider_runtime.health import HealthEngine

        _HEALTH_ENGINE = HealthEngine()
    return _HEALTH_ENGINE


# ── Auth / tenant / operator dependencies ───────────────────────────────────


def _tenant_id(request: Request, permission: str = "read") -> str:
    request.state.tenant.require_permission(permission)
    tid = getattr(request.state.tenant, "tenant_id", None)
    if not tid:
        raise ForbiddenError("Tenant context is required")
    return tid


def _require_operator(request: Request):
    from services.security.request_context import require_kyber_operator

    return require_kyber_operator(request)


# ── Error translation (safe_message only; never details / raw text) ─────────


def _raise_runtime_error(exc: Exception) -> None:
    """Translate a provider-runtime error to a tenant-safe HTTP error.

    Only ``safe_message`` ever reaches the response. Unrecognized errors become
    a 500 with a generic message (never ``str(exc)``).
    """
    from services.provider_runtime import errors as perrors

    # An already-typed AetherError from a seam keeps its own status (404/400...).
    if isinstance(exc, AetherError):
        raise exc  # noqa: B904

    safe = getattr(exc, "safe_message", None)
    message = safe if isinstance(safe, str) and safe.strip() else "provider runtime error"

    if isinstance(exc, perrors.ProviderNotInstalled):
        raise NotFoundError(message)  # noqa: B904
    if isinstance(exc, (perrors.AuthorizationFailed, perrors.CredentialMissing)):
        raise UnauthorizedError(message)  # noqa: B904
    if isinstance(exc, (perrors.PermissionMissing, perrors.WebhookVerificationFailed)):
        raise ForbiddenError(message)  # noqa: B904
    if isinstance(exc, perrors.ProviderRateLimited):
        raise AetherError(ErrorCode.RATE_LIMITED, message)  # noqa: B904
    if isinstance(exc, perrors.ConnectionStateViolation):
        raise AetherError(ErrorCode.CONFLICT, message)  # noqa: B904
    if isinstance(exc, perrors.ProviderRuntimeError):
        raise BadRequestError(message)  # noqa: B904
    logger.warning("provider runtime route: unexpected error type=%s", type(exc).__name__)
    raise AetherError(ErrorCode.INTERNAL, message)  # noqa: B904


async def _await_or_error(awaitable: Any) -> Any:
    """Await a seam coroutine, translating runtime errors to HTTP errors.

    ``_raise_runtime_error`` always raises, so the ``await`` completes only on
    success. A ``ProviderNotInstalled`` becomes 404, an illegal transition 409,
    a rate limit 429, etc. — never an unhandled 500.
    """
    try:
        return await awaitable
    except Exception as exc:
        _raise_runtime_error(exc)


# ── Serialization helpers ───────────────────────────────────────────────────


def _as_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return value


def _manifest_to_dict(value: Any) -> Any:
    return _as_dict(value)


def _entry_identity(entry: Any) -> str:
    """Extract an identity key from a registry ``list()`` entry, shape-agnostic."""
    if isinstance(entry, dict):
        return str(entry.get("identity_key") or entry.get("identity") or entry.get("key") or "")
    if isinstance(entry, tuple) and entry:
        return str(entry[0])
    return str(getattr(entry, "identity_key", "") or getattr(entry, "identity", "") or "")


def _registry_source(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("source") or "")
    if isinstance(entry, tuple) and len(entry) >= 2:
        return str(entry[1] if isinstance(entry[1], str) else "")
    return str(getattr(entry, "source", "") or "")


async def _load_connection(orchestrator: Any, connection_id: str, tenant_id: str) -> Any:
    """Load a connection and enforce tenant ownership (cross-tenant ids are 404)."""
    connection = await orchestrator.connections.find(connection_id)
    if connection is None or connection.tenant_id != tenant_id:
        raise NotFoundError("connection")
    return connection


def _config_field_errors(plugin: Any, config: dict[str, Any]) -> list[str]:
    """Validate config against the plugin manifest's declared field spec.

    Validation runs only when the plugin is installed AND declares config
    fields; otherwise the config is accepted unvalidated (there is no manifest
    surface to validate against).
    """
    if plugin is None:
        return []
    manifest = plugin.manifest()
    fields = list(getattr(getattr(manifest, "configuration", None), "fields", None) or [])
    if not fields:
        return []
    declared = {str(getattr(f, "name", "") or ""): f for f in fields}
    errors: list[str] = []
    for name, spec in declared.items():
        if getattr(spec, "required", False) and name not in config:
            errors.append(f"config field {name!r} is required")
    for key in config:
        if key not in declared:
            errors.append(f"unknown config field {key!r}")
    return errors


# ── Request bodies ──────────────────────────────────────────────────────────


class ConnectionCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_identity: str
    display_name: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectionUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Optional[str] = None
    config: Optional[dict[str, Any]] = None


class AccountSelectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str


class SyncTriggerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    since: Optional[str] = None


class CertifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_key: str


# ── Providers (merged manifest surface) ─────────────────────────────────────


def _merged_manifests(reg: Any) -> list[Any]:
    """Merged manifest surface (catalog + installed), source-attributed.

    Prefers ``ManifestService.merged_manifests()`` (Team C); falls back to
    ``reg.manifests()`` (a ``{key: manifest}`` map or a flat iterable), then to
    per-plugin ``manifest()`` when the registry only exposes the item surface.
    ``source`` is attached from ``reg.sources()`` when available.
    """
    merged: dict[str, Any] = {}
    try:
        from services.provider_runtime.manifest_service import ManifestService

        # ManifestService(reg) — not the module singleton — so an injected
        # registry (tests) is honored, not the global one.
        merged = dict(ManifestService(reg).merged_manifests())
    except Exception as exc:
        logger.warning(
            "provider merged_manifests() unavailable (%s); falling back", exc
        )

    if not merged:
        manifests_fn = getattr(reg, "manifests", None)
        if callable(manifests_fn):
            try:
                raw = manifests_fn()
                if isinstance(raw, dict):
                    merged = dict(raw)
                else:
                    merged = {
                        _entry_identity(entry): entry for entry in raw
                    }
            except Exception as exc:
                logger.warning(
                    "provider registry manifests() failed (%s); falling back", exc
                )

    if not merged:
        for entry in reg.list():
            identity = _entry_identity(entry)
            plugin = reg.get(identity) if identity else None
            if plugin is not None and hasattr(plugin, "manifest"):
                merged[identity] = plugin.manifest()

    sources: dict[str, str] = {}
    sources_fn = getattr(reg, "sources", None)
    if callable(sources_fn):
        try:
            sources = dict(sources_fn())
        except Exception:
            sources = {}

    items: list[Any] = []
    for key, manifest in merged.items():
        payload = _manifest_to_dict(manifest)
        if isinstance(payload, dict):
            payload = dict(payload)
            source = sources.get(str(key), "") if sources else ""
            if source:
                payload.setdefault("source", source)
        items.append(payload)
    return items


@router.get("/providers")
async def list_providers(request: Request):
    _tenant_id(request)
    manifests = _merged_manifests(_get_registry())
    return APIResponse(data={"providers": manifests, "count": len(manifests)}).to_dict()


@router.get("/providers/{identity_key}")
async def get_provider_manifest(identity_key: str, request: Request):
    _tenant_id(request)
    plugin = _get_registry().get(identity_key)
    if plugin is None:
        raise NotFoundError("provider")
    return APIResponse(data=_manifest_to_dict(plugin.manifest())).to_dict()


# ── Connection lifecycle ────────────────────────────────────────────────────


@router.post("")
async def create_connection(body: ConnectionCreateBody, request: Request):
    tenant_id = _tenant_id(request, "write")
    # Fail fast: a connection for a provider that is not installed is unusable.
    if _get_registry().get(body.provider_identity) is None:
        raise NotFoundError("provider")
    connection = await _await_or_error(
        _get_orchestrator().create_connection(
            tenant_id=tenant_id,
            provider_identity=body.provider_identity,
            display_name=body.display_name,
            config=body.config,
        )
    )
    return APIResponse(data=_as_dict(connection)).to_dict()


@router.get("/{connection_id}")
async def get_connection(connection_id: str, request: Request):
    tenant_id = _tenant_id(request)
    connection = await _load_connection(_get_orchestrator(), connection_id, tenant_id)
    return APIResponse(data=_as_dict(connection)).to_dict()


@router.patch("/{connection_id}")
async def update_connection(connection_id: str, body: ConnectionUpdateBody, request: Request):
    tenant_id = _tenant_id(request, "write")
    orchestrator = _get_orchestrator()
    connection = await _load_connection(orchestrator, connection_id, tenant_id)
    if body.display_name is not None:
        connection.display_name = body.display_name
    if body.config is not None:
        merged = {**(connection.config or {}), **body.config}
        plugin = _get_registry().get(connection.provider_identity)
        errors = _config_field_errors(plugin, merged)
        if errors:
            raise BadRequestError("; ".join(errors))
        connection.config = merged
    connection.updated_at = _now_iso()
    stored = await _await_or_error(orchestrator.connections.upsert(connection))
    return APIResponse(data=_as_dict(stored)).to_dict()


@router.delete("/{connection_id}")
async def delete_connection(connection_id: str, request: Request):
    tenant_id = _tenant_id(request, "admin")
    orchestrator = _get_orchestrator()
    connection = await _load_connection(orchestrator, connection_id, tenant_id)
    try:
        connection = orchestrator.transition(connection, ConnectionState.DISABLED)
    except Exception as exc:
        _raise_runtime_error(exc)
    await _await_or_error(orchestrator.connections.upsert(connection))
    return APIResponse(
        data={"connection_id": connection_id, "state": ConnectionState.DISABLED.value}
    ).to_dict()


@router.post("/{connection_id}/credentials")
async def store_credential(connection_id: str, body: dict[str, Any], request: Request):
    tenant_id = _tenant_id(request, "write")
    orchestrator = _get_orchestrator()
    connection = await _load_connection(orchestrator, connection_id, tenant_id)
    from shared.credentials.types import as_structured

    try:
        credential = as_structured(body)
    except Exception:
        raise BadRequestError("credential payload is not a valid structured credential")
    stored = await _await_or_error(orchestrator.store_credential(connection, credential))
    # Never echo secrets: ProviderConnection carries only the credential_ref.
    return APIResponse(data=_as_dict(stored)).to_dict()


@router.post("/{connection_id}/test")
async def test_connection(connection_id: str, request: Request):
    tenant_id = _tenant_id(request, "write")
    orchestrator = _get_orchestrator()
    connection = await _load_connection(orchestrator, connection_id, tenant_id)
    plugin = _get_registry().get(connection.provider_identity)
    result = await _await_or_error(orchestrator.test_connection(connection, plugin=plugin))
    return APIResponse(data=_as_dict(result)).to_dict()


# ── Accounts (discovery + selection) ────────────────────────────────────────


@router.get("/{connection_id}/accounts")
async def list_accounts(connection_id: str, request: Request):
    tenant_id = _tenant_id(request)
    orchestrator = _get_orchestrator()
    connection = await _load_connection(orchestrator, connection_id, tenant_id)
    plugin = _get_registry().get(connection.provider_identity)
    result = await _await_or_error(
        _get_coordinator().discover_accounts(connection, plugin=plugin)
    )
    return APIResponse(
        data={
            "items": [account.model_dump() for account in (result.data or [])],
            "adapter": _as_dict(result),
        }
    ).to_dict()


@router.post("/{connection_id}/accounts/select")
async def select_account(connection_id: str, body: AccountSelectBody, request: Request):
    tenant_id = _tenant_id(request, "write")
    orchestrator = _get_orchestrator()
    connection = await _load_connection(orchestrator, connection_id, tenant_id)
    plugin = _get_registry().get(connection.provider_identity)
    connection = await _await_or_error(
        _get_coordinator().select_account(
            connection, account_id=body.account_id, plugin=plugin
        )
    )
    await _await_or_error(orchestrator.connections.upsert(connection))
    return APIResponse(data=_as_dict(connection)).to_dict()


# ── Sync ────────────────────────────────────────────────────────────────────


@router.post("/{connection_id}/sync")
async def trigger_sync(connection_id: str, body: SyncTriggerBody, request: Request):
    tenant_id = _tenant_id(request, "write")
    orchestrator = _get_orchestrator()
    connection = await _load_connection(orchestrator, connection_id, tenant_id)
    result = await _await_or_error(orchestrator.run_sync(connection, since=body.since))
    return APIResponse(data=_as_dict(result)).to_dict()


@router.get("/{connection_id}/sync-runs")
async def list_sync_runs(connection_id: str, request: Request, limit: int = 50):
    tenant_id = _tenant_id(request)
    orchestrator = _get_orchestrator()
    connection = await _load_connection(orchestrator, connection_id, tenant_id)
    from services.comms.sync_runs import SyncRunService

    runs = await _await_or_error(
        SyncRunService().list_for_connector(
            tenant_id, connection_id, limit=max(1, min(limit, _MAX_LIST_LIMIT))
        )
    )
    return APIResponse(data={"items": runs, "count": len(runs)}).to_dict()


# ── Health ──────────────────────────────────────────────────────────────────


@router.get("/{connection_id}/health")
async def connection_health(connection_id: str, request: Request):
    tenant_id = _tenant_id(request)
    orchestrator = _get_orchestrator()
    connection = await _load_connection(orchestrator, connection_id, tenant_id)
    report = await _await_or_error(_get_health_engine().report(connection))
    return APIResponse(data=_as_dict(report)).to_dict()


@router.get("/{connection_id}/raw-records")
async def raw_records(connection_id: str, request: Request, limit: int = 50):
    tenant_id = _tenant_id(request)
    orchestrator = _get_orchestrator()
    connection = await _load_connection(orchestrator, connection_id, tenant_id)
    from repositories.lake import BronzeRepository

    bronze = BronzeRepository("provider_records")
    filters = {"tenant_id": tenant_id, "source": connection.provider_identity}
    rows = await _await_or_error(
        bronze.find_many(
            filters=filters,
            limit=max(1, min(limit, _MAX_LIST_LIMIT)),
        )
    )
    total = await _await_or_error(bronze.count(filters=filters))
    # Raw records are stored at provider/tenant granularity in Bronze (the
    # connection is not part of the Bronze key), so this is the honest
    # provider-scoped read for the connection — the same table the
    # RawProviderRecordStore writes to.
    return APIResponse(
        data={
            "items": rows,
            "count": len(rows),
            "total": total,
            "truncated": total > len(rows),
            "note": "raw records are stored at provider/tenant granularity",
        }
    ).to_dict()


# ── Kyber operator (aggregate-only) ─────────────────────────────────────────


@admin_router.get("/overview")
async def provider_connections_overview(request: Request):
    """Per-provider connection counts by lifecycle state (aggregate-only)."""
    _require_operator(request)
    orchestrator = _get_orchestrator()
    rows = await _await_or_error(orchestrator.connections.find_many(filters={}, limit=5000))
    by_provider: dict[str, dict[str, int]] = {}
    total = 0
    for row in rows:
        identity = str(row.get("provider_identity") or "unknown")
        raw_state = row.get("state") or "unknown"
        # Repo rows may carry the enum member or its string value.
        state = raw_state.value if hasattr(raw_state, "value") else str(raw_state)
        bucket = by_provider.setdefault(identity, {})
        bucket[state] = bucket.get(state, 0) + 1
        total += 1
    return APIResponse(
        data={
            "providers": by_provider,
            "total": total,
            "truncated": total >= 5000,
            "cap": 5000,
        }
    ).to_dict()


@admin_router.get("/health")
async def provider_runtime_health(request: Request):
    """Registry summary: providers loaded, legacy vs native plugin counts."""
    _require_operator(request)
    reg = _get_registry()
    entries = reg.list()
    sources_fn = getattr(reg, "sources", None)
    if callable(sources_fn):
        try:
            source_values = list(dict(sources_fn()).values())
        except Exception:
            source_values = []
    else:
        source_values = []
    if not source_values:
        source_values = [_registry_source(entry) for entry in entries]
    legacy = sum(1 for source in source_values if source == "legacy")
    native = sum(1 for source in source_values if source and source != "legacy")
    return APIResponse(
        data={
            "providers_loaded": len(entries),
            "legacy_count": legacy,
            "native_count": native,
            "environment": "local",
        }
    ).to_dict()


@admin_router.post("/certify")
async def certify_provider_route(body: CertifyBody, request: Request):
    """Run the certification harness against an installed provider plugin."""
    _require_operator(request)
    plugin = _get_registry().get(body.identity_key)
    if plugin is None:
        raise NotFoundError("provider")
    from services.provider_runtime.certification import certify_provider

    report = certify_provider(plugin)
    return APIResponse(data=_as_dict(report)).to_dict()


@admin_router.get("/tenants/{tenant_id}")
async def provider_runtime_tenant_view(tenant_id: str, request: Request):
    """Connections + health for one tenant (Kyber operator drill-down)."""
    _require_operator(request)
    orchestrator = _get_orchestrator()
    connections = await _await_or_error(
        orchestrator.connections.list_for_tenant(tenant_id, limit=500)
    )
    items: list[dict[str, Any]] = []
    health_engine = _get_health_engine()
    for connection in connections:
        item: dict[str, Any] = {"connection": _as_dict(connection)}
        try:
            item["health"] = _as_dict(await health_engine.report(connection))
        except Exception as exc:
            safe = getattr(exc, "safe_message", None)
            item["health"] = None
            item["health_error"] = safe if isinstance(safe, str) and safe.strip() else "health unavailable"
        items.append(item)
    return APIResponse(data={"tenant_id": tenant_id, "items": items}).to_dict()


# ── Public provider webhook ingestion ───────────────────────────────────────
# UNAUTHENTICATED by API key (listed in PUBLIC_PATH_PREFIXES). Security is
# enforced inside the gateway via provider-native signature verification.


@webhook_public_router.post("/{identity_key}")
async def provider_webhook_ingest(identity_key: str, request: Request):
    """Public provider webhook delivery.

    Security: this route is UNAUTHENTICATED by API key (listed in
    ``PUBLIC_PATH_PREFIXES``). Authorization is enforced inside the gateway by
    cryptographic proof that the caller holds the connection's webhook secret:
    a signature scheme requires a verifying signature, and ``endpoint_secret``
    requires a caller-presented per-connection endpoint token. A delivery that
    cannot be proven is DENIED with an auditable denial record and a closed
    4xx — never silently accepted.

    ``X-Aether-Tenant-ID`` is only a routing hint to locate the connection to
    verify against; it is NOT an authorization signal. A delivery is only
    persisted after the connection's secret proves the caller owns it, so the
    header cannot be forged to inject into another tenant.

    Headers:
      X-Aether-Tenant-ID: <tenant_id>            (routing hint, required)
      X-Signature / X-Aether-Signature: <sig>    (signature schemes)
      X-Aether-Webhook-Endpoint-Token: <token>   (endpoint_secret schemes)
    """
    tenant_id = request.headers.get("X-Aether-Tenant-ID", "").strip()
    if not tenant_id:
        raise BadRequestError("X-Aether-Tenant-ID header is required")
    signature = request.headers.get("X-Signature", "").strip() or request.headers.get(
        "X-Aether-Signature", ""
    ).strip()
    raw_body = await request.body()
    try:
        result = await _get_gateway().ingest(
            identity_key,
            raw_body=raw_body,
            headers=dict(request.headers),
            signature=signature,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        _raise_runtime_error(exc)
    # A verification/payload denial surfaces as a closed 4xx, never a 200.
    if not result.get("accepted", False):
        reason = str(result.get("reason") or "webhook_rejected")
        raise ForbiddenError(f"webhook rejected: {reason}")  # noqa: B904
    return APIResponse(data=_as_dict(result)).to_dict()
