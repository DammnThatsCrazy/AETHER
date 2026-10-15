"""Break-Glass Operator Access.

Time-boxed, audited, approval-gated emergency access for Olympus operators into a
specific tenant. Every transition (request/approve/deny/revoke/expire) and every
access used under an active grant is audited.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from shared.common.common import BadRequestError, NotFoundError, utc_now
from shared.logger.logger import get_logger

from .audit_ledger import audit_ledger
from .contracts import BreakGlassRequest, now_iso
from .repositories import BreakGlassRepository

logger = get_logger("aether.security.break_glass")

DEFAULT_WINDOW_HOURS = 4
MAX_WINDOW_HOURS = 24


def _parse(ts: Optional[str]):
    if not ts:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


class BreakGlassService:
    def __init__(self, repo: Optional[BreakGlassRepository] = None) -> None:
        self._repo = repo or BreakGlassRepository()

    async def request(
        self, *, tenant_id: str, requested_by: str, reason: str,
        requested_scope: str, window_hours: int = DEFAULT_WINDOW_HOURS,
    ) -> BreakGlassRequest:
        if not reason or not reason.strip():
            raise BadRequestError("break-glass requires a non-empty reason")
        window_hours = max(1, min(window_hours, MAX_WINDOW_HOURS))
        req = BreakGlassRequest(
            tenant_id=tenant_id, requested_by=requested_by, reason=reason.strip(),
            requested_scope=requested_scope, status='requested',
            # expires_at is set on approval; the window is recorded alongside.
        )
        data = req.model_dump()
        data["window_hours"] = window_hours
        await self._repo.insert(req.request_id, data)
        await audit_ledger.record(
            actor_id=requested_by, actor_type='olympus_operator',
            event_type="break_glass.request", resource_type="break_glass_request",
            action="request", outcome='allowed', tenant_id=tenant_id,
            resource_id=req.request_id,
            metadata={"reason": reason.strip(), "requested_scope": requested_scope, "window_hours": window_hours},
        )
        return req

    async def _load(self, request_id: str) -> dict:
        row = await self._repo.find_by_id(request_id)
        if row is None:
            raise NotFoundError(f"break-glass request {request_id!r} not found")
        return row

    async def approve(self, *, request_id: str, approved_by: str) -> BreakGlassRequest:
        row = await self._load(request_id)
        if row.get("status") != 'requested':
            raise BadRequestError(f"cannot approve request in status {row.get('status')!r}")
        # Break-glass must be second-actor approved: the requester cannot grant
        # their own emergency access, or has_active_grant() would let an operator
        # self-authorize tenant access end to end.
        if approved_by == row.get("requested_by"):
            await audit_ledger.record(
                actor_id=approved_by, actor_type='olympus_operator',
                event_type="break_glass.self_approval_blocked",
                resource_type="break_glass_request", action="approve",
                outcome='blocked', tenant_id=row.get("tenant_id"), resource_id=request_id,
            )
            raise BadRequestError("break-glass approval requires a different operator than the requester")
        window_hours = int(row.get("window_hours", DEFAULT_WINDOW_HOURS))
        now = utc_now()
        row.update({
            "status": 'approved', "approved_by": approved_by,
            "starts_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=window_hours)).isoformat(),
            "updated_at": now_iso(),
        })
        await self._repo.update(request_id, row)
        await audit_ledger.record(
            actor_id=approved_by, actor_type='olympus_operator',
            event_type="break_glass.approve", resource_type="break_glass_request",
            action="approve", outcome='allowed', tenant_id=row.get("tenant_id"),
            resource_id=request_id, metadata={"expires_at": row["expires_at"]},
        )
        return BreakGlassRequest(**{k: row.get(k) for k in BreakGlassRequest.model_fields})

    async def deny(self, *, request_id: str, approved_by: str, reason: str = "") -> BreakGlassRequest:
        row = await self._load(request_id)
        if row.get("status") != 'requested':
            raise BadRequestError(f"cannot deny request in status {row.get('status')!r}")
        row.update({"status": 'denied', "approved_by": approved_by, "updated_at": now_iso()})
        await self._repo.update(request_id, row)
        await audit_ledger.record(
            actor_id=approved_by, actor_type='olympus_operator',
            event_type="break_glass.deny", resource_type="break_glass_request",
            action="deny", outcome='blocked', tenant_id=row.get("tenant_id"),
            resource_id=request_id, metadata={"reason": reason},
        )
        return BreakGlassRequest(**{k: row.get(k) for k in BreakGlassRequest.model_fields})

    async def revoke(self, *, request_id: str, revoked_by: str) -> BreakGlassRequest:
        row = await self._load(request_id)
        if row.get("status") not in ('approved', 'requested'):
            raise BadRequestError(f"cannot revoke request in status {row.get('status')!r}")
        row.update({"status": 'revoked', "updated_at": now_iso()})
        await self._repo.update(request_id, row)
        await audit_ledger.record(
            actor_id=revoked_by, actor_type='olympus_operator',
            event_type="break_glass.revoke", resource_type="break_glass_request",
            action="revoke", outcome='allowed', tenant_id=row.get("tenant_id"),
            resource_id=request_id,
        )
        return BreakGlassRequest(**{k: row.get(k) for k in BreakGlassRequest.model_fields})

    async def _maybe_expire(self, row: dict) -> dict:
        if row.get("status") == 'approved':
            exp = _parse(row.get("expires_at"))
            if exp is not None and utc_now() >= exp:
                row.update({"status": 'expired', "updated_at": now_iso()})
                await self._repo.update(row["request_id"], row)
                await audit_ledger.record(
                    actor_id="system", actor_type='system',
                    event_type="break_glass.expire", resource_type="break_glass_request",
                    action="expire", outcome='allowed', tenant_id=row.get("tenant_id"),
                    resource_id=row["request_id"],
                )
        return row

    async def has_active_grant(self, tenant_id: str, operator_id: str) -> bool:
        rows = await self._repo.list_for_tenant(tenant_id, limit=200)
        for row in rows:
            if row.get("requested_by") != operator_id:
                continue
            row = await self._maybe_expire(row)
            if row.get("status") == 'approved':
                await audit_ledger.record(
                    actor_id=operator_id, actor_type='olympus_operator',
                    event_type="break_glass.access_used", resource_type="break_glass_grant",
                    action="access", outcome='allowed', tenant_id=tenant_id,
                    resource_id=row.get("request_id"),
                )
                return True
        return False

    async def list_requests(self, tenant_id: Optional[str] = None, limit: int = 200) -> list[dict]:
        rows = (
            await self._repo.list_for_tenant(tenant_id, limit=limit)
            if tenant_id else await self._repo.list_all(limit=limit)
        )
        return [await self._maybe_expire(r) for r in rows]


break_glass_service = BreakGlassService()
