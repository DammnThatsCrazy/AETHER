"""Reconciliation between Kyber principals and Google Workspace.

Kyber does not own employment. Google Workspace does. When someone leaves,
the authoritative act is disabling their Google account — this module's job is
to notice that and make Kyber agree, so an offboarding that happened in the
directory does not linger as live Kyber authority.

The honest limitation, stated here and in the source-of-truth document: the
Admin SDK integration is *optional*. When it is not configured, reconciliation
is a no-op that records why and deliberately does **not** stamp
``last_directory_sync_at``. A principal is never marked fresh by a
reconciliation that did not happen. In that mode manual suspension through
``POST /v1/kyber/workforce/principals/{operator_id}/suspend`` is the
authoritative immediate control, and it is the only one.

Freshness feeds authorization. :meth:`DirectorySyncService.directory_freshness`
returns ``(fresh, reason)`` so the access dependency can deny a privileged
operator whose directory state is stale rather than trusting a role binding
that may have outlived the employment behind it.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Coroutine, Optional

import httpx

from services.kyber.access.contracts import WorkforcePrincipal
from services.security.audit_ledger import audit_ledger
from shared.logger.logger import get_logger, metrics

from .principals import AUDIT_ACTOR_TYPE, parse_timestamp, principal_service

logger = get_logger("aether.kyber.identity.directory_sync")

DEFAULT_MAX_AGE_HOURS = 24
DEFAULT_INTERVAL_SECONDS = 3600
DIRECTORY_USERS_ENDPOINT = "https://admin.googleapis.com/admin/directory/v1/users"

#: Holding any of these makes a principal "privileged" for freshness purposes.
#: They are the capabilities whose misuse cannot be undone by revoking a
#: session after the fact.
PRIVILEGED_CAPABILITY_IDS: frozenset[str] = frozenset(
    {
        "kyber.workforce.manage",
        "kyber.role.manage",
        "kyber.device.approve",
        "kyber.tenant.raw.read",
        "kyber.command.pause",
        "kyber.command.rollback",
        "kyber.command.kill_switch",
    }
)

__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "DEFAULT_MAX_AGE_HOURS",
    "DirectorySyncResult",
    "DirectorySyncService",
    "DirectorySyncWorker",
    "PRIVILEGED_CAPABILITY_IDS",
    "build_directory_sync_coro",
    "directory_sync_service",
]

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class DirectorySyncResult:
    """What one reconciliation attempt did, and why."""

    operator_id: str
    action: str
    reason: Optional[str] = None
    changed: bool = False

    @property
    def ok(self) -> bool:
        return self.action not in ("error", "not_configured")


class DirectorySyncService:
    """Reconciles workforce principals against Google Workspace."""

    # ── Configuration ─────────────────────────────────────────────────────────

    @staticmethod
    def is_configured() -> bool:
        """True only when the Admin SDK integration can actually be called."""
        return _env_flag("KYBER_DIRECTORY_SYNC_ENABLED", default=False) and bool(
            (os.getenv("KYBER_GOOGLE_ADMIN_ACCESS_TOKEN") or "").strip()
        )

    @staticmethod
    def strict_freshness_required() -> bool:
        """When on, privileged access is denied unless the directory is fresh.

        Off by default so a deployment without the Admin SDK still functions;
        on, it converts "we could not check" into a denial.
        """
        return _env_flag("KYBER_DIRECTORY_SYNC_REQUIRED", default=False)

    @staticmethod
    def max_age_hours() -> int:
        return max(1, _env_int("KYBER_DIRECTORY_MAX_AGE_HOURS", DEFAULT_MAX_AGE_HOURS))

    @staticmethod
    def interval_seconds() -> int:
        return max(60, _env_int("KYBER_DIRECTORY_SYNC_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS))

    @staticmethod
    def _access_token() -> str:
        return (os.getenv("KYBER_GOOGLE_ADMIN_ACCESS_TOKEN") or "").strip()

    # ── Freshness ─────────────────────────────────────────────────────────────

    async def is_stale(
        self, principal: WorkforcePrincipal, *, max_age_hours: int
    ) -> bool:
        """True when the principal has never been reconciled or is overdue."""
        last = parse_timestamp(principal.last_directory_sync_at)
        if last is None:
            return True
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, max_age_hours))
        return last < cutoff

    async def directory_freshness(
        self, operator_id: str
    ) -> tuple[bool, Optional[str]]:
        """``(fresh, reason)`` for the access dependency to act on.

        A non-privileged principal is always considered fresh: the directory
        adds nothing to an observer's read-only authority that suspension does
        not already cover. A privileged principal is denied when the directory
        is stale, and — under ``KYBER_DIRECTORY_SYNC_REQUIRED`` — also when the
        directory could not be consulted at all.
        """
        principal = await principal_service.get_by_operator_id(operator_id)
        if principal is None:
            return False, "principal_unknown"
        if not principal.is_active:
            return False, "principal_inactive"

        capabilities = await principal_service.effective_capabilities(operator_id)
        if not (capabilities & PRIVILEGED_CAPABILITY_IDS):
            return True, None

        if not self.is_configured():
            if self.strict_freshness_required():
                return False, "directory_sync_unconfigured"
            return True, "directory_sync_unconfigured"

        if await self.is_stale(principal, max_age_hours=self.max_age_hours()):
            metrics.increment("kyber_directory_stale_total")
            return False, "directory_stale"
        return True, None

    # ── Reconciliation ────────────────────────────────────────────────────────

    async def reconcile_principal(self, operator_id: str) -> DirectorySyncResult:
        """Reconcile one principal against the directory.

        Never stamps freshness unless a real directory answer was obtained.
        """
        principal = await principal_service.get_by_operator_id(operator_id)
        if principal is None:
            return DirectorySyncResult(operator_id, "not_found", "principal_unknown")
        if principal.employment_status == "offboarded":
            return DirectorySyncResult(operator_id, "skipped", "already_offboarded")

        if not self.is_configured():
            logger.info(
                "kyber directory sync skipped: Admin SDK not configured "
                f"operator_id={operator_id}"
            )
            metrics.increment(
                "kyber_directory_sync_skipped_total", labels={"reason": "not_configured"}
            )
            return DirectorySyncResult(operator_id, "not_configured", "admin_sdk_not_configured")

        try:
            user = await self._fetch_directory_user(principal.email)
        except Exception as exc:  # noqa: BLE001 - one failed user must not stop the sweep
            logger.warning(f"kyber directory lookup failed operator_id={operator_id}: {exc}")
            metrics.increment("kyber_directory_sync_error_total")
            return DirectorySyncResult(operator_id, "error", "lookup_failed")

        if user is None:
            await self._enforce_absence(principal, reason="directory_user_absent")
            return DirectorySyncResult(
                operator_id, "offboarded", "directory_user_absent", changed=True
            )

        suspended = bool(user.get("suspended")) or bool(user.get("archived"))
        if suspended:
            if principal.employment_status != "suspended":
                await principal_service.suspend(
                    operator_id,
                    actor_id="kyber_directory_sync",
                    reason="google workspace account suspended",
                )
                await principal_service.mark_directory_synced(operator_id)
                metrics.increment("kyber_directory_sync_suspended_total")
                return DirectorySyncResult(
                    operator_id, "suspended", "directory_user_suspended", changed=True
                )
            await principal_service.mark_directory_synced(operator_id)
            return DirectorySyncResult(operator_id, "reconciled", "already_suspended")

        patch: dict[str, Any] = {}
        directory_name = (user.get("name") or {}).get("fullName")
        if directory_name and directory_name != principal.display_name:
            patch["display_name"] = directory_name
        directory_subject = str(user.get("id") or "").strip()
        if directory_subject and not principal.google_subject:
            patch["google_subject"] = directory_subject
        if patch:
            await principal_service.principals.update(operator_id, patch)

        await principal_service.mark_directory_synced(operator_id)
        metrics.increment("kyber_directory_sync_reconciled_total")
        await self._audit(operator_id, action="reconcile", reason="directory_ok")
        return DirectorySyncResult(operator_id, "reconciled", None, changed=bool(patch))

    async def reconcile_all(self) -> dict[str, int | bool]:
        """Reconcile every non-offboarded principal. Returns counts."""
        counts: dict[str, int | bool] = {
            "checked": 0,
            "reconciled": 0,
            "suspended": 0,
            "offboarded": 0,
            "skipped": 0,
            "errors": 0,
            "configured": self.is_configured(),
        }
        principals = await principal_service.list_principals(limit=1000)
        for principal in principals:
            if principal.employment_status == "offboarded":
                continue
            counts["checked"] = int(counts["checked"]) + 1
            result = await self.reconcile_principal(principal.operator_id)
            key = {
                "reconciled": "reconciled",
                "suspended": "suspended",
                "offboarded": "offboarded",
                "error": "errors",
            }.get(result.action, "skipped")
            counts[key] = int(counts[key]) + 1
        logger.info(f"kyber directory reconcile_all {counts}")
        return counts

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _fetch_directory_user(self, email: str) -> Optional[dict[str, Any]]:
        """Look one user up through the Admin SDK Directory API.

        Returns ``None`` for a 404 (the user is gone) and raises for every
        other failure, so "absent" and "could not ask" stay distinguishable.
        """
        token = self._access_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{DIRECTORY_USERS_ENDPOINT}/{email}", headers=headers
            )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, dict) else None

    async def _enforce_absence(self, principal: WorkforcePrincipal, *, reason: str) -> None:
        """A principal with no directory user is fully offboarded, not suspended."""
        from .lifecycle import offboard_principal  # local import: lifecycle fans out

        await offboard_principal(
            principal.operator_id,
            actor_id="kyber_directory_sync",
            reason=f"directory reconciliation: {reason}",
        )
        await principal_service.mark_directory_synced(principal.operator_id)
        metrics.increment("kyber_directory_sync_offboarded_total")
        await self._audit(principal.operator_id, action="offboard", reason=reason)

    async def _audit(self, operator_id: str, *, action: str, reason: Optional[str]) -> None:
        await audit_ledger.record(
            actor_id="kyber_directory_sync",
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.directory.reconciled",
            resource_type="workforce_principal",
            action=action,
            outcome="allowed",
            resource_id=operator_id,
            metadata={"reason": reason},
        )


directory_sync_service = DirectorySyncService()


# ── Supervised worker ─────────────────────────────────────────────────────────

class DirectorySyncWorker:
    """Long-running reconciliation loop for the ``maintenance`` runtime role."""

    def __init__(self, service: Optional[DirectorySyncService] = None) -> None:
        self.service = service or directory_sync_service
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        logger.info("kyber directory sync worker started")
        while self._running:
            try:
                await self.service.reconcile_all()
            except asyncio.CancelledError:  # pragma: no cover - shutdown path
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                logger.error(f"kyber directory sync sweep failed: {exc}")
                metrics.increment("kyber_directory_sync_error_total")
            await asyncio.sleep(self.service.interval_seconds())

    def stop(self) -> None:  # pragma: no cover - shutdown path
        self._running = False


def build_directory_sync_coro() -> Coroutine:
    """Zero-arg factory: a fresh long-running directory reconciliation coroutine.

    Same shape as ``services.jobs.worker.build_job_worker_coro`` so the runtime
    supervisor can register it under the existing ``maintenance`` role without
    a special case.
    """
    return DirectorySyncWorker().run_forever()
