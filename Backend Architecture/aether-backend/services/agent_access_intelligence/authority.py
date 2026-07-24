"""Capability authority — who is allowed to invoke which observed capability (PR 2, Phase B1).

A capability authorization **is a delegation**. The platform already has five grant
concepts (delegations, x402 approvals, consent grants, permission grants, break-glass);
adding a sixth would fork revocation, expiry, tenant scoping, graph convergence and DSR
erasure. So this module stores authorizations in the existing ``delegations`` table via
``CapabilityAuthorizationRepository(DelegationRepository)``, which only adds
capability-typed **top-level** (therefore ``find_many``-filterable) fields and stamps
``authorization_kind: "capability"``.

Scope encoding (the only two shapes this module ever writes)::

    one capability          actions=["invoke"]  resources=["capability:{capability_id}"]
    every capability on a   actions=["invoke"]  resources=["capability-server:{server_ref}"]
    single server

``server_ref`` is a digest of ``(tenant_id, server_key)``, never the raw server name or
URL: a ``:`` or ``*`` inside an observed server URL must not be able to widen scope
through ``DelegationEngine._resource_matches``' ``prefix:*`` glob.

Fail-closed invariants enforced on every write (each has a test):

1. ``scope.resources`` is never empty — ``DelegationEngine`` treats an empty resource
   list as *match everything*, which would silently authorize every action for the
   grantee, including through ``POST /v1/delegations/validate``.
2. ``*`` is rejected in both actions and resources.
3. ``actions`` is exactly ``["invoke"]``.
4. Reads/revokes compare ``tenant_id`` and raise ``NotFoundError`` on mismatch, so an
   authorization id cannot confirm the existence of another tenant's row.
5. Granting for a ``capability_id`` that is not in the tenant's catalog is **allowed**
   but recorded as ``capability_observed: false``. It is never silently upgraded to
   ``true`` — authorizing something you have not observed is a legitimate (pre-)grant,
   and pretending it was observed would fabricate inventory evidence.

There is no approval queue here: the permission-gated ``POST`` is itself the authorizing
act. Multi-party approval, where a tenant requires it, routes through the existing
``services/x402/approvals.py`` flow. Authorization *state* (``active``/``revoked``/
``expired``) is always **derived** from the row, never stored as a field that could
disagree with ``revoked_at``/``ends_at``.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Optional

from shared.common.common import BadRequestError, NotFoundError, utc_now
from shared.logger.logger import get_logger
from repositories.repos import DelegationRepository
from services.agent_access_intelligence.repositories import CapabilityCatalogRepository
from services.delegation.engine import DelegationEngine

logger = get_logger("aether.agent_access_intelligence.authority")

AUTHORIZATION_KIND = "capability"
INVOKE_ACTION = "invoke"
CAPABILITY_RESOURCE_PREFIX = "capability:"
SERVER_RESOURCE_PREFIX = "capability-server:"

# Identifiers that end up inside a delegation resource string. Deliberately excludes
# ``*`` and ``:`` so a caller-supplied id can never become a glob pattern or inject a
# second resource segment. Server keys are NOT constrained by this — they are hashed.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def server_ref_for(tenant_id: str, server_key: str) -> str:
    """Stable, bounded, glob-safe reference for an observed capability server.

    A digest rather than the raw name/URL: observed server keys are attacker-influenced
    free text and are interpolated into a delegation resource string that is later
    matched with a ``prefix:*`` glob."""
    raw = f"{tenant_id}|{server_key}"
    return "srv_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def capability_resource(capability_id: str) -> str:
    return f"{CAPABILITY_RESOURCE_PREFIX}{capability_id}"


def server_resource(server_ref: str) -> str:
    return f"{SERVER_RESOURCE_PREFIX}{server_ref}"


def validate_capability_scope(scope: dict[str, Any]) -> None:
    """Enforce the fail-closed scope invariants. Raises ``BadRequestError``.

    Called on every write path — including any future caller that builds a scope
    itself — so the invariants hold at the storage boundary, not just at the API."""
    actions = scope.get("actions") or []
    resources = scope.get("resources") or []
    if list(actions) != [INVOKE_ACTION]:
        raise BadRequestError(
            f"capability authorization scope.actions must be exactly ['{INVOKE_ACTION}']"
        )
    if not resources:
        # An empty resource list matches EVERY resource in DelegationEngine.
        raise BadRequestError("capability authorization scope.resources must not be empty")
    for resource in resources:
        if not isinstance(resource, str) or not resource.strip():
            raise BadRequestError("capability authorization scope.resources entries must be non-empty strings")
        if "*" in resource:
            raise BadRequestError("wildcard resources are not allowed in a capability authorization")
        if not (
            resource.startswith(CAPABILITY_RESOURCE_PREFIX)
            or resource.startswith(SERVER_RESOURCE_PREFIX)
        ):
            raise BadRequestError(
                "capability authorization resources must be "
                f"'{CAPABILITY_RESOURCE_PREFIX}<id>' or '{SERVER_RESOURCE_PREFIX}<ref>'"
            )


def authorization_state(record: dict[str, Any], *, now_iso: Optional[str] = None) -> str:
    """Derive ``active`` / ``revoked`` / ``expired`` from the stored row.

    Never persisted: a stored status field can disagree with ``revoked_at``/``ends_at``
    after a clock tick, and the disagreement would be invisible."""
    now = now_iso or utc_now().isoformat()
    if record.get("revoked_at"):
        return "revoked"
    ends_at = record.get("ends_at")
    if ends_at and str(ends_at) <= now:
        return "expired"
    starts_at = record.get("starts_at") or ""
    if starts_at > now:
        return "pending"
    return "active"


class CapabilityAuthorizationRepository(DelegationRepository):
    """``delegations`` rows that carry capability-typed top-level fields.

    Subclasses (rather than wraps) ``DelegationRepository`` so revocation semantics,
    the 60s Redis active-set cache + its invalidation, and the ``DelegationProjector``
    graph convergence are literally the same code path as every other delegation."""

    async def grant_capability(
        self,
        *,
        authorization_id: str,
        tenant_id: str,
        granted_by_entity_id: str,
        agent_id: str,
        scope: dict[str, Any],
        capability_id: Optional[str] = None,
        server_ref: Optional[str] = None,
        server_key_hint: Optional[str] = None,
        capability_observed: bool = False,
        starts_at: Optional[str] = None,
        ends_at: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict:
        validate_capability_scope(scope)
        record = await self.grant(
            delegation_id=authorization_id,
            tenant_id=tenant_id,
            grantor_entity_id=granted_by_entity_id,
            grantee_entity_id=agent_id,
            scope=scope,
            starts_at=starts_at,
            ends_at=ends_at,
            metadata=metadata,
        )
        # Additive, top-level (JSONB ``data->>'key'``) so `find_many` can filter on them.
        # Written as a follow-up merge rather than a hand-rolled insert so the base
        # delegation field set stays owned by DelegationRepository.grant.
        updated = await self.update(authorization_id, {
            **record,
            "authorization_kind": AUTHORIZATION_KIND,
            "agent_id": agent_id,
            "capability_id": capability_id,
            "server_ref": server_ref,
            "server_key_hint": server_key_hint,
            "capability_observed": bool(capability_observed),
        })
        # `grant` invalidated the cache before these fields existed; a concurrent
        # `active_for` between the two writes would have repopulated it with the
        # partial row. Invalidate again so the cached active set is never partial.
        await self._invalidate_cache(agent_id, tenant_id)
        return updated

    async def list_authorizations(
        self,
        tenant_id: str,
        *,
        agent_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        server_ref: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        filters: dict[str, Any] = {
            "tenant_id": tenant_id,
            "authorization_kind": AUTHORIZATION_KIND,
        }
        if agent_id:
            filters["agent_id"] = agent_id
        if capability_id:
            filters["capability_id"] = capability_id
        if server_ref:
            filters["server_ref"] = server_ref
        return await self.find_many(filters=filters, limit=limit, offset=offset)


class CapabilityAuthorityService:
    """Grant / read / revoke capability authorizations, and resolve whether an agent
    currently holds one.

    Resolution deliberately returns *facts* (is the capability in inventory, is there
    an active authorization) and leaves the verdict to ``PolicyEngine`` — the platform
    has exactly one policy engine and this module does not become a second one."""

    def __init__(
        self,
        repo: Optional[CapabilityAuthorizationRepository] = None,
        catalog: Optional[CapabilityCatalogRepository] = None,
    ) -> None:
        self._repo = repo or CapabilityAuthorizationRepository()
        self._catalog = catalog or CapabilityCatalogRepository()
        self._engine = DelegationEngine(self._repo)

    # ── writes ────────────────────────────────────────────────────────────────

    async def grant(
        self,
        *,
        tenant_id: str,
        granted_by_entity_id: str,
        agent_id: str,
        capability_id: Optional[str] = None,
        server_key: Optional[str] = None,
        ends_at: Optional[str] = None,
        starts_at: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        authorization_id: Optional[str] = None,
    ) -> dict:
        if not agent_id or not agent_id.strip():
            raise BadRequestError("agent_id is required")
        if bool(capability_id) == bool(server_key):
            raise BadRequestError(
                "provide exactly one of capability_id (one capability) or "
                "server_key (every capability on one server)"
            )

        server_ref: Optional[str] = None
        capability_observed = False
        if capability_id:
            if not _SAFE_ID_RE.match(capability_id):
                raise BadRequestError("capability_id contains unsupported characters")
            resources = [capability_resource(capability_id)]
            # Honest inventory linkage: a capability absent from the catalog may still
            # be authorized (pre-authorization is legitimate), but it is recorded as
            # unobserved rather than being invented into the inventory.
            record = await self._catalog.find_by_id(capability_id)
            capability_observed = bool(record) and str(record.get("tenant_id")) == str(tenant_id)
        else:
            assert server_key is not None  # guarded by the exactly-one check above
            if not server_key.strip():
                raise BadRequestError("server_key must not be blank")
            server_ref = server_ref_for(tenant_id, server_key)
            resources = [server_resource(server_ref)]

        scope = {"actions": [INVOKE_ACTION], "resources": resources}
        validate_capability_scope(scope)

        record = await self._repo.grant_capability(
            authorization_id=authorization_id or str(uuid.uuid4()),
            tenant_id=tenant_id,
            granted_by_entity_id=granted_by_entity_id,
            agent_id=agent_id,
            scope=scope,
            capability_id=capability_id,
            server_ref=server_ref,
            server_key_hint=server_key,
            capability_observed=capability_observed,
            starts_at=starts_at,
            ends_at=ends_at,
            metadata=metadata,
        )
        return self._public(record)

    async def revoke(
        self, *, tenant_id: str, authorization_id: str, revoked_by_entity_id: str
    ) -> dict:
        await self.get(tenant_id=tenant_id, authorization_id=authorization_id)
        updated = await self._repo.revoke(authorization_id, revoked_by_entity_id=revoked_by_entity_id)
        if updated is None:  # pragma: no cover — `get` already proved it exists
            raise NotFoundError("capability_authorization")
        return self._public(updated)

    # ── reads ─────────────────────────────────────────────────────────────────

    async def get(self, *, tenant_id: str, authorization_id: str) -> dict:
        record = await self._repo.find_by_id(authorization_id)
        if (
            not record
            or str(record.get("tenant_id")) != str(tenant_id)
            or record.get("authorization_kind") != AUTHORIZATION_KIND
        ):
            # Fail closed and identically for "absent", "other tenant" and "an ordinary
            # delegation" so the id cannot be used as an existence oracle.
            raise NotFoundError("capability_authorization")
        return self._public(record)

    async def list(
        self,
        *,
        tenant_id: str,
        agent_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        rows = await self._repo.list_authorizations(
            tenant_id,
            agent_id=agent_id,
            capability_id=capability_id,
            limit=limit,
            offset=offset,
        )
        public = [self._public(r) for r in rows]
        if state:
            public = [r for r in public if r["state"] == state]
        return public

    async def resolve(
        self, *, tenant_id: str, agent_id: Optional[str], capability_id: str
    ) -> dict[str, Any]:
        """Facts a policy decision needs, with no verdict of its own.

        Returns ``capability_observed``, ``latest_risk_level``, ``authorized``,
        ``authorization_id`` and ``matched_scope``."""
        capability = await self._catalog.find_by_id(capability_id)
        if capability and str(capability.get("tenant_id")) != str(tenant_id):
            capability = None
        facts: dict[str, Any] = {
            "capability_id": capability_id,
            "capability_observed": capability is not None,
            "latest_risk_level": (capability or {}).get("latest_risk_level"),
            "authorized": False,
            "authorization_id": None,
            "matched_scope": None,
            "authorization_reason": "no_agent_id" if not agent_id else "no_active_capability_authorization",
        }
        if not agent_id:
            return facts

        # Specific capability first, then server-wide. Both reads hit the same
        # 60s-cached `active_for(agent_id, tenant_id)` set.
        candidates = [capability_resource(capability_id)]
        server_key = (capability or {}).get("server_name") or (capability or {}).get("server_url")
        if server_key:
            candidates.append(server_resource(server_ref_for(tenant_id, server_key)))

        for resource in candidates:
            decision = await self._engine.evaluate(
                grantee_entity_id=agent_id,
                action=INVOKE_ACTION,
                resource=resource,
                tenant_id=tenant_id,
            )
            if not decision.allowed:
                continue
            # `DelegationEngine` is shared with ordinary delegations; confirm the row
            # that matched is actually a capability authorization and is still active,
            # so a hand-written delegation cannot satisfy a capability check.
            row = await self._repo.find_by_id(decision.delegation_id or "")
            if not row or row.get("authorization_kind") != AUTHORIZATION_KIND:
                continue
            if authorization_state(row) != "active":
                continue
            facts.update({
                "authorized": True,
                "authorization_id": decision.delegation_id,
                "matched_scope": decision.matched_scope,
                "authorization_reason": "active_capability_authorization",
            })
            break
        return facts

    # ── serialization ─────────────────────────────────────────────────────────

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        """API-facing view: private fields stripped, ``state`` derived (never stored)."""
        out = {k: v for k, v in record.items() if not k.startswith("_")}
        out["authorization_id"] = record.get("delegation_id") or record.get("id")
        out["state"] = authorization_state(record)
        return out


capability_authority_service = CapabilityAuthorityService()
