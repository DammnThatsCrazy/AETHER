"""
Aether Service — External Agent Deployment Registry

Durable, tenant-scoped registry for tenant-owned agents deployed on external
distribution surfaces (External Agent Telemetry Plane V1).

Mirrors the shared TS contract in packages/shared/agent-deployment.ts:
platforms, environments, consent modes, lifecycle statuses, health counters,
and the audit record shape. Aether observes telemetry from these deployments;
it does not publish, host, execute, or operate a marketplace.

Lifecycle state machine (enforced by AgentDeploymentRepository):
    active   → paused | revoked | error | archived
    paused   → active (reactivate) | revoked | archived
    error    → active (reactivate) | revoked | archived
    revoked  → archived
    archived → (terminal)

Every lifecycle change writes an AgentDeploymentAuditRecord and increments a
metric. Secrets are never stored: metadata is sanitized recursively against
secret key patterns before persistence.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from services.ingestion.generated_registry import EVENT_CONSENT_PURPOSE, EVENT_FAMILY
from shared.common.common import BadRequestError, ConflictError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.service.agent.deployments")

SCHEMA_VERSION = "agent.deployment.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Enums (mirror packages/shared/agent-deployment.ts) ────────────────────────

class ExternalPlatform(str, Enum):
    WEB_WIDGET = "web_widget"
    MOBILE_APP = "mobile_app"
    DISCORD_BOT = "discord_bot"
    TELEGRAM_BOT = "telegram_bot"
    SLACK_APP = "slack_app"
    SHOPIFY_APP = "shopify_app"
    SALESFORCE_APP = "salesforce_app"
    # Tenant/customer-owned or third-party marketplace surface — Aether does
    # not operate a marketplace.
    CUSTOM_MARKETPLACE = "custom_marketplace"
    WALLET_APP = "wallet_app"
    BROWSER_EXTENSION = "browser_extension"
    MCP_SERVER = "mcp_server"
    BACKEND_WORKER = "backend_worker"
    API_AGENT = "api_agent"
    UNKNOWN = "unknown"


class AgentDeploymentEnvironment(str, Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    SANDBOX = "sandbox"
    DEVELOPMENT = "development"


class AgentDeploymentConsentMode(str, Enum):
    TENANT_MANAGED = "tenant_managed"
    PLATFORM_MANAGED = "platform_managed"
    AETHER_MANAGED = "aether_managed"


class AgentDeploymentStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    REVOKED = "revoked"
    ERROR = "error"
    ARCHIVED = "archived"


# ── Registry-derived validation sets ──────────────────────────────────────────

# The canonical event family names (21) from the generated event registry.
VALID_EVENT_FAMILIES: frozenset[str] = frozenset(EVENT_FAMILY.values())

# The consent purposes the generated registry maps events onto.
VALID_CONSENT_PURPOSES: frozenset[str] = frozenset(EVENT_CONSENT_PURPOSE.values())

# Secret-bearing key patterns — matched case-insensitively against metadata
# keys, recursively. Matching keys are stripped before persistence so secrets
# never reach stores, logs, or responses.
_SECRET_KEY_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"api[_\s-]?key", r"apikey", r"secret", r"token",
        r"authorization", r"password", r"private[_\s-]?key", r"credential",
    ]
]

_MAX_CAPABILITY_SCOPES = 64
_MAX_CAPABILITY_SCOPE_LENGTH = 200

# Valid lifecycle transitions: current status → allowed target statuses.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    AgentDeploymentStatus.ACTIVE.value: frozenset({"paused", "revoked", "error", "archived"}),
    AgentDeploymentStatus.PAUSED.value: frozenset({"active", "revoked", "archived"}),
    AgentDeploymentStatus.ERROR.value: frozenset({"active", "revoked", "archived"}),
    AgentDeploymentStatus.REVOKED.value: frozenset({"archived"}),
    AgentDeploymentStatus.ARCHIVED.value: frozenset(),
}

# Audit action recorded for each transition target status.
_ACTION_BY_TARGET_STATUS: dict[str, str] = {
    "paused": "paused",
    "active": "reactivated",
    "revoked": "revoked",
    "archived": "archived",
    "error": "errored",
}

_VALID_EVENT_OUTCOMES = frozenset({"accepted", "rejected", "consent_blocked", "error"})

_OUTCOME_COUNTER_FIELD = {
    "accepted": "accepted_count_24h",
    "rejected": "rejected_count_24h",
    "consent_blocked": "consent_blocked_count_24h",
    "error": "error_count_24h",
}


def sanitize_metadata(value: Any) -> tuple[Any, bool]:
    """Recursively strip dict keys matching secret patterns.

    Returns (sanitized_value, had_secret_keys). Matching keys are removed
    entirely (not redacted) so secret material never persists anywhere.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        had_secret = False
        for k, v in value.items():
            if any(p.search(str(k)) for p in _SECRET_KEY_PATTERNS):
                had_secret = True
                continue
            sanitized, child_secret = sanitize_metadata(v)
            out[k] = sanitized
            if child_secret:
                had_secret = True
        return out, had_secret
    if isinstance(value, list):
        out_list: list[Any] = []
        had_secret = False
        for item in value:
            sanitized, child_secret = sanitize_metadata(item)
            out_list.append(sanitized)
            if child_secret:
                had_secret = True
        return out_list, had_secret
    return value, False


# ── Models ─────────────────────────────────────────────────────────────────────

class AgentDeployment(BaseModel):
    """Tenant-scoped external agent deployment registry record.

    Snake_case mirror of the AgentDeployment TS interface. The 24h health
    counters are simple monotonic counters reset when the UTC date rolls over
    (tracked via ``counters_reset_at``) — deliberately simple V1 semantics.
    """

    id: str = Field(default_factory=_new_id)
    tenant_id: str = Field(..., min_length=1, max_length=256)
    agent_id: str = Field(..., min_length=1, max_length=256)
    display_name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2000)
    external_platform: ExternalPlatform
    external_platform_account_id: Optional[str] = Field(default=None, max_length=256)
    external_agent_id: Optional[str] = Field(default=None, max_length=256)
    external_app_id: Optional[str] = Field(default=None, max_length=256)
    external_channel_id: Optional[str] = Field(default=None, max_length=256)
    external_workspace_id: Optional[str] = Field(default=None, max_length=256)
    environment: AgentDeploymentEnvironment = AgentDeploymentEnvironment.PRODUCTION
    status: AgentDeploymentStatus = AgentDeploymentStatus.ACTIVE
    consent_mode: AgentDeploymentConsentMode = AgentDeploymentConsentMode.TENANT_MANAGED
    # Canonical event families this deployment may emit. Empty = no family
    # restriction declared (validated against the generated registry).
    allowed_event_families: list[str] = Field(default_factory=list)
    # Consent purposes that must be satisfied for events from this deployment.
    required_consent_purposes: list[str] = Field(default_factory=list)
    # Declared capability scopes (observation-only; never execution grants).
    capability_scopes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    last_event_at: Optional[str] = None
    # Rolling 24h telemetry health counters (UTC date-rollover reset).
    health_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    event_count_24h: int = 0
    accepted_count_24h: int = 0
    rejected_count_24h: int = 0
    error_count_24h: int = 0
    consent_blocked_count_24h: int = 0
    graph_projection_lag_ms: Optional[int] = None
    counters_reset_at: Optional[str] = None
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)
    revoked_at: Optional[str] = None
    archived_at: Optional[str] = None

    @field_validator("allowed_event_families")
    @classmethod
    def _validate_event_families(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - VALID_EVENT_FAMILIES)
        if unknown:
            raise ValueError(f"Unknown event families: {unknown}")
        return v

    @field_validator("required_consent_purposes")
    @classmethod
    def _validate_consent_purposes(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - VALID_CONSENT_PURPOSES)
        if unknown:
            raise ValueError(f"Unknown consent purposes: {unknown}")
        return v

    @field_validator("capability_scopes")
    @classmethod
    def _validate_capability_scopes(cls, v: list[str]) -> list[str]:
        if len(v) > _MAX_CAPABILITY_SCOPES:
            raise ValueError(f"At most {_MAX_CAPABILITY_SCOPES} capability scopes allowed")
        for scope in v:
            if not scope or len(scope) > _MAX_CAPABILITY_SCOPE_LENGTH:
                raise ValueError(
                    f"Capability scopes must be 1-{_MAX_CAPABILITY_SCOPE_LENGTH} characters"
                )
        return v

    @model_validator(mode="after")
    def _sanitize_metadata(self) -> "AgentDeployment":
        sanitized, had_secret = sanitize_metadata(self.metadata)
        if had_secret:
            metrics.increment("agent_deployment_metadata_secret_stripped_total")
            logger.warning(
                "Secret-pattern metadata keys stripped from deployment %s (tenant=%s)",
                self.id, self.tenant_id,
            )
            self.metadata = sanitized
        return self


class AgentDeploymentAuditRecord(BaseModel):
    """Audit record for deployment lifecycle changes."""

    id: str = Field(default_factory=_new_id)
    tenant_id: str
    deployment_id: str
    action: str  # created | updated | paused | reactivated | revoked | archived | errored
    actor: str = ""
    request_id: Optional[str] = None
    detail: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str = Field(default_factory=_utc_now)


def _validation_message(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
        for err in exc.errors()
    )


# ── Repository ────────────────────────────────────────────────────────────────

class AgentDeploymentRepository:
    """Durable, tenant-scoped repository over the shared store abstraction.

    Store keys are always tenant-prefixed (``{tenant_id}:{deployment_id}``) so
    cross-tenant reads cannot resolve another tenant's records.
    """

    def __init__(self) -> None:
        self._store = get_store("agent_deployments")
        self._audit_store = get_store("agent_deployment_audit")

    @staticmethod
    def _key(tenant_id: str, deployment_id: str) -> str:
        return f"{tenant_id}:{deployment_id}"

    # ── CRUD ──────────────────────────────────────────────────────────────

    async def create(
        self,
        tenant_id: str,
        data: dict[str, Any],
        actor: str = "",
        request_id: str = "",
    ) -> dict:
        """Validate and persist a new deployment; writes a 'created' audit record."""
        payload = dict(data)
        # Server-owned fields — never trusted from the caller.
        for owned in ("id", "tenant_id", "status", "created_at", "updated_at",
                      "revoked_at", "archived_at", "event_count_24h", "accepted_count_24h",
                      "rejected_count_24h", "error_count_24h", "consent_blocked_count_24h",
                      "counters_reset_at", "first_seen_at", "last_seen_at", "last_event_at",
                      "health_score", "graph_projection_lag_ms"):
            payload.pop(owned, None)
        try:
            deployment = AgentDeployment(tenant_id=tenant_id, **payload)
        except ValidationError as exc:
            raise BadRequestError(_validation_message(exc))
        except TypeError:
            raise BadRequestError("Unknown deployment fields in request")

        record = deployment.model_dump(mode="json")
        await self._store.set(self._key(tenant_id, deployment.id), record)
        await self._write_audit(
            tenant_id, deployment.id, "created", actor, request_id,
            detail={"external_platform": record["external_platform"],
                    "environment": record["environment"]},
        )
        metrics.increment("agent_deployments_created_total")
        logger.info("Agent deployment created: %s (tenant=%s)", deployment.id, tenant_id)
        return record

    async def get_record(self, tenant_id: str, deployment_id: str) -> Optional[dict]:
        """Non-raising fetch. Tenant-prefixed key ⇒ no cross-tenant resolution."""
        if not deployment_id:
            return None
        return await self._store.get(self._key(tenant_id, deployment_id))

    async def get(self, tenant_id: str, deployment_id: str) -> dict:
        """Fetch or raise NotFoundError (cross-tenant access is a not-found)."""
        record = await self.get_record(tenant_id, deployment_id)
        if record is None:
            raise NotFoundError("Agent deployment")
        return record

    async def list(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> list[dict]:
        """Tenant-scoped listing with optional status/platform/agent filters."""
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        if platform:
            filters["external_platform"] = platform
        if agent_id:
            filters["agent_id"] = agent_id
        records = await self._store.find(**filters)
        return sorted(records, key=lambda r: r.get("updated_at", ""), reverse=True)

    async def list_all(self) -> list[dict]:
        """Cross-tenant listing — Kyber operator fleet views only."""
        records = await self._store.find()
        return sorted(records, key=lambda r: r.get("updated_at", ""), reverse=True)

    # Mutable via PATCH — everything else is server-owned or lifecycle-owned.
    MUTABLE_FIELDS: frozenset[str] = frozenset({
        "display_name", "description", "metadata", "allowed_event_families",
        "required_consent_purposes", "capability_scopes", "consent_mode",
    })

    async def update(
        self,
        tenant_id: str,
        deployment_id: str,
        changes: dict[str, Any],
        actor: str = "",
        request_id: str = "",
    ) -> dict:
        """Apply whitelisted field changes; writes an 'updated' audit record."""
        unknown = sorted(set(changes) - self.MUTABLE_FIELDS)
        if unknown:
            raise BadRequestError(f"Fields not updatable: {unknown}")
        record = await self.get(tenant_id, deployment_id)
        if record.get("status") == AgentDeploymentStatus.ARCHIVED.value:
            raise ConflictError("Archived deployments are immutable")

        merged = {**record, **changes}
        try:
            deployment = AgentDeployment(**merged)
        except ValidationError as exc:
            raise BadRequestError(_validation_message(exc))
        deployment.updated_at = _utc_now()

        updated = deployment.model_dump(mode="json")
        await self._store.set(self._key(tenant_id, deployment_id), updated)
        await self._write_audit(
            tenant_id, deployment_id, "updated", actor, request_id,
            # Field names only — values may be tenant-private.
            detail={"fields": sorted(changes)},
        )
        metrics.increment("agent_deployments_updated_total")
        return updated

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def transition(
        self,
        tenant_id: str,
        deployment_id: str,
        target_status: str,
        actor: str = "",
        request_id: str = "",
        reason: str = "",
    ) -> dict:
        """Validated lifecycle transition; invalid transitions raise ConflictError."""
        if target_status not in _ACTION_BY_TARGET_STATUS:
            raise BadRequestError(f"Unknown deployment status: {target_status}")
        record = await self.get(tenant_id, deployment_id)
        current = record.get("status", "")
        if target_status not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise ConflictError(
                f"Invalid deployment transition: {current} -> {target_status}"
            )

        now = _utc_now()
        record["status"] = target_status
        record["updated_at"] = now
        if target_status == AgentDeploymentStatus.REVOKED.value:
            record["revoked_at"] = now
        elif target_status == AgentDeploymentStatus.ARCHIVED.value:
            record["archived_at"] = now

        await self._store.set(self._key(tenant_id, deployment_id), record)
        action = _ACTION_BY_TARGET_STATUS[target_status]
        detail: dict[str, Any] = {"from_status": current, "to_status": target_status}
        if reason:
            detail["reason"] = reason
        await self._write_audit(tenant_id, deployment_id, action, actor, request_id, detail)
        metrics.increment(
            "agent_deployment_lifecycle_transitions_total", labels={"action": action}
        )
        logger.info(
            "Agent deployment %s: %s -> %s (tenant=%s)",
            deployment_id, current, target_status, tenant_id,
        )
        return record

    # ── Audit ─────────────────────────────────────────────────────────────

    async def _write_audit(
        self,
        tenant_id: str,
        deployment_id: str,
        action: str,
        actor: str,
        request_id: str,
        detail: Optional[dict[str, Any]] = None,
    ) -> dict:
        audit = AgentDeploymentAuditRecord(
            tenant_id=tenant_id,
            deployment_id=deployment_id,
            action=action,
            actor=actor,
            request_id=request_id or None,
            detail=detail or {},
        )
        record = audit.model_dump(mode="json")
        await self._audit_store.set(self._key(tenant_id, audit.id), record)
        metrics.increment("agent_deployment_audit_records_total", labels={"action": action})
        return record

    async def audit_trail(
        self, tenant_id: str, deployment_id: str, limit: int = 100
    ) -> list[dict]:
        records = await self._audit_store.find(
            tenant_id=tenant_id, deployment_id=deployment_id
        )
        records.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
        return records[:limit]

    # ── Health counters ───────────────────────────────────────────────────

    async def record_event_outcome(
        self, tenant_id: str, deployment_id: str, outcome: str
    ) -> None:
        """Increment the 24h counter for an ingestion outcome.

        Counters are simple monotonic counters reset when the UTC date rolls
        over (``counters_reset_at``). Missing deployments are a no-op so
        ingestion never fails on health bookkeeping.
        """
        if outcome not in _VALID_EVENT_OUTCOMES:
            raise BadRequestError(f"Unknown event outcome: {outcome}")
        record = await self.get_record(tenant_id, deployment_id)
        if record is None:
            return

        today = _utc_today()
        if record.get("counters_reset_at") != today:
            for field_name in ("event_count_24h", *_OUTCOME_COUNTER_FIELD.values()):
                record[field_name] = 0
            record["counters_reset_at"] = today

        record["event_count_24h"] = int(record.get("event_count_24h", 0)) + 1
        counter = _OUTCOME_COUNTER_FIELD[outcome]
        record[counter] = int(record.get(counter, 0)) + 1

        now = _utc_now()
        record["last_event_at"] = now
        record["last_seen_at"] = now
        if not record.get("first_seen_at"):
            record["first_seen_at"] = now
        record["updated_at"] = now

        await self._store.set(self._key(tenant_id, deployment_id), record)
        metrics.increment(
            "agent_deployment_event_outcomes_total", labels={"outcome": outcome}
        )


# ── Module-level helpers (used by ingestion) ──────────────────────────────────

_repository: Optional[AgentDeploymentRepository] = None


def get_deployment_repository() -> AgentDeploymentRepository:
    global _repository
    if _repository is None:
        _repository = AgentDeploymentRepository()
    return _repository


async def validate_deployment_context(
    tenant_id: str, context: dict, event_family: str = ""
) -> tuple[bool, str]:
    """Validate an event's agent deployment context for the authenticated tenant.

    The deployment must exist for the tenant, be 'active', and (when the
    deployment declares allowed_event_families) the event's family must be
    allowed. Returns (ok, reason_code).
    """
    context = context or {}
    deployment_id = context.get("deploymentId") or context.get("deployment_id") or ""
    if not deployment_id:
        return False, "missing_deployment_id"
    record = await get_deployment_repository().get_record(tenant_id, str(deployment_id))
    if record is None:
        return False, "deployment_not_found"
    if record.get("status") != AgentDeploymentStatus.ACTIVE.value:
        return False, "deployment_not_active"
    allowed_families = record.get("allowed_event_families") or []
    if allowed_families and event_family and event_family not in allowed_families:
        return False, "event_family_not_allowed"
    return True, "ok"


async def record_event_outcome(tenant_id: str, deployment_id: str, outcome: str) -> None:
    """Module-level convenience over the repository singleton."""
    await get_deployment_repository().record_event_outcome(tenant_id, deployment_id, outcome)
