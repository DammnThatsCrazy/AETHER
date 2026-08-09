"""Expiry/overlap sweep worker for the durable credential authority.

The rotation-overlap window (``rotation_overlap_expires_at`` on a ``previous``
version) is swept lazily today inside ``get_verification_secrets``; this worker
makes the sweep *proactive* and *observable*. On each pass it:

  1. tombstones ``previous`` versions whose overlap window has expired
     (erasing the ciphertext, keeping the audit stub);
  2. records lifecycle-demotion hooks for every credential that became
     tombstoned or revoked — calling the readiness-demotion seam
     (:class:`services.capabilities.readiness_repo.CapabilityReadinessService`)
     when it is seeded/available so the credential's readiness token moves to
     ``CREDENTIAL_INVALID``, otherwise falling back to emitting the transition
     metric so operators still see the lifecycle change.

The loop is a supervised worker: each pass is exception-isolated (one bad pass
can never kill the loop), logs a per-pass report, and emits a heartbeat metric
so liveness is observable. It is NOT registered here — Agent 1B registers
:func:`build_credential_expiry_sweeper` in the runtime worker specs.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

from services.providers.credentials.authority import credential_authority
from services.providers.credentials.repository import CredentialVersionRepo
from services.providers.credentials.schema import CredentialState

logger = get_logger("aether.providers.credential_sweeper")

# Capability namespace for readiness-demotion hooks. The integration pass owns
# the seam's seed step; the sweeper only ever demotes a seeded capability.
_CAPABILITY_PREFIX = "credential:"

# Default sweep interval when settings are unavailable (local/offline).
_DEFAULT_INTERVAL_S = 300


def _overlap_expired(row: dict) -> bool:
    """True when a ``previous`` version's overlap window has lapsed."""
    expires = row.get("rotation_overlap_expires_at")
    if not expires:
        return False
    try:
        from datetime import datetime

        return datetime.fromisoformat(expires) <= utc_now()
    except (ValueError, TypeError):
        return False


def _default_interval() -> int:
    try:
        from config.settings import settings

        value = getattr(settings.provider_gateway, "credential_rotation_overlap_hours", 24)
        # A sweep at least twice per overlap window keeps the window honest.
        return max(30, int(int(value) * 3600 / 2))
    except Exception:  # noqa: BLE001 — settings absence falls back to the default
        return _DEFAULT_INTERVAL_S


async def _all_version_rows(repo: CredentialVersionRepo) -> list[dict]:
    """Page through every credential version row (offset-stable: we never delete
    rows, only change state, so offset paging cannot skip or duplicate)."""
    rows: list[dict] = []
    offset = 0
    page_size = 500
    while True:
        page = await repo.find_many(limit=page_size, offset=offset)
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


async def _emit_demotion(tenant_id: str, provider: str, slot_name: str, reason: str) -> bool:
    """Lifecycle-demotion hook: readiness seam when available, metric otherwise.

    Always emits the transition metric so the lifecycle change is observable
    even when the readiness seam is unseeded/unavailable.
    """
    metrics.increment(
        "credential_sweep_demotion_total",
        labels={"provider": provider, "slot": slot_name},
    )
    try:
        from services.capabilities.readiness_repo import capability_readiness_service
        from shared.certification.readiness import CredentialReadiness

        await capability_readiness_service.demote(
            tenant_id,
            f"{_CAPABILITY_PREFIX}{provider}:{slot_name}",
            target=CredentialReadiness.CREDENTIAL_INVALID,
            reason=reason,
            actor="credential_sweeper",
        )
        return True
    except Exception:  # noqa: BLE001 — seam unseeded/unavailable: metric fallback already done
        return False


async def sweep_once(
    *,
    repo: Optional[CredentialVersionRepo] = None,
    authority: Any = None,
    demote: bool = True,
) -> dict:
    """Run one credential sweep pass and return its report.

    ``authority`` is the decrypt-cache owner used to invalidate swept rows
    (defaults to the module singleton). ``demote=False`` disables the readiness
    seam for callers that only want the tombstone pass.
    """
    repo = repo or CredentialVersionRepo()
    authority = authority if authority is not None else credential_authority

    report: dict = {
        "scanned": 0,
        "tombstoned_overlap": 0,
        "demoted_readiness": 0,
        "demotion_metrics_only": 0,
    }
    for row in await _all_version_rows(repo):
        report["scanned"] += 1
        state = row.get("state")

        if state == CredentialState.PREVIOUS and _overlap_expired(row):
            await repo.update(
                row["id"],
                {
                    "state": CredentialState.TOMBSTONED,
                    "encrypted_value": "",
                    "encrypted_data_key": "",
                },
            )
            authority._invalidate(row)
            report["tombstoned_overlap"] += 1
            if demote:
                ok = await _emit_demotion(
                    row.get("tenant_id", ""),
                    row.get("provider", ""),
                    row.get("slot_name", ""),
                    reason="rotation overlap window expired",
                )
                report["demoted_readiness" if ok else "demotion_metrics_only"] += 1
        elif state == CredentialState.REVOKED:
            if demote:
                ok = await _emit_demotion(
                    row.get("tenant_id", ""),
                    row.get("provider", ""),
                    row.get("slot_name", ""),
                    reason="credential revoked",
                )
                report["demoted_readiness" if ok else "demotion_metrics_only"] += 1
    return report


async def run_credential_sweep_loop(interval_seconds: Optional[int] = None) -> None:
    """Supervised credential sweep loop (exception-isolated, heartbeat)."""
    interval = int(
        interval_seconds if interval_seconds is not None else _default_interval()
    )
    logger.info("credential authority sweep worker started interval=%ss", interval)
    while True:
        try:
            report = await sweep_once()
            metrics.increment("credential_sweep_runs_total")
            metrics.gauge(
                "credential_sweep_last_run_unix", utc_now().timestamp()
            )
            if report["tombstoned_overlap"] or report["demoted_readiness"]:
                logger.info("credential sweep pass: %s", report)
            elif report["scanned"]:
                logger.debug("credential sweep pass (no-op): %s", report)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a bad pass must never kill the loop
            metrics.increment("credential_sweep_error_total")
            logger.error("credential sweep pass failed: %s", exc, exc_info=True)
        await asyncio.sleep(interval)


def build_credential_expiry_sweeper() -> Any:
    """Zero-arg coroutine factory for the runtime WorkerSpec (Agent 1B wires it).

    Returns a FRESH coroutine per call so the supervisor can (re)start it.
    """
    return run_credential_sweep_loop()


__all__ = [
    "build_credential_expiry_sweeper",
    "run_credential_sweep_loop",
    "sweep_once",
]
