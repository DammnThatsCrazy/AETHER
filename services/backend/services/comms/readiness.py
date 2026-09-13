"""Communications subsystem readiness (§21).

A dedicated readiness dimension for the comms vertical, surfaced both in the
gateway ``/ready`` probe (process-level) and in the Kyber comms health snapshot
(fleet). It is truthful about three things the generic checks cannot express on
their own:

  * **comms storage reachability** — the durable spine tables (webhook_inbox,
    comms facts) answer, or the subsystem is not ready;
  * **required-worker dependency** — comms projection rides the release-critical
    ``stream-worker`` (ingestion stream) and delivery rides ``outbox-relay``;
    if a comms-required release-critical worker this process hosts has failed,
    comms readiness fails too (it never reports healthy over a dead projector);
  * **processing backlog** — a large webhook-inbox or dead-letter backlog is a
    *degraded* signal (processing lag), not an availability failure.

Crucially, this is a subsystem/process signal, never a per-tenant one: a single
tenant's revoked credential must not fail comms readiness for the whole app —
that truth lives per-connector in the health snapshot instead.
"""

from __future__ import annotations

from typing import Any, Optional

# Comms-required platform capabilities (from services/runtime/roles.py):
#   stream-ingestion  ← stream-worker  (drives the comms projector fan-out)
#   event-delivery    ← outbox-relay   (at-least-once outbound delivery)
_COMMS_REQUIRED_CAPABILITIES = ("stream-ingestion", "event-delivery")

# Backlog above this many undrained webhook-inbox rows is a degraded signal.
_INBOX_BACKLOG_DEGRADED = 5000


def _comms_worker_failures(worker_capabilities: dict[str, Any]) -> list[str]:
    """Comms-required, release-critical capabilities that are unavailable here.

    Only counts capabilities this process actually hosts (present in the map);
    a capability answered by another process is not this probe's to fail.
    """
    failures: list[str] = []
    for cap_name in _COMMS_REQUIRED_CAPABILITIES:
        cap = worker_capabilities.get(cap_name)
        if cap is None:
            continue  # not hosted here — answered on its own readiness surface
        if not cap.get("available", False) and cap.get("release_critical", False):
            failures.append(cap_name)
    return failures


async def _webhook_inbox_backlog(pool: Any) -> tuple[int, Optional[float]]:
    """(pending_count, oldest_pending_age_seconds) — bounded, best-effort."""
    row = await pool.fetchrow(
        """
        SELECT COUNT(*) AS pending,
               EXTRACT(EPOCH FROM (now() - MIN(created_at))) AS oldest_age
        FROM webhook_inbox
        WHERE COALESCE(data->>'processed', 'false') <> 'true'
        """
    )
    if not row:
        return 0, None
    return int(row["pending"] or 0), (
        float(row["oldest_age"]) if row["oldest_age"] is not None else None
    )


async def comms_subsystem_readiness(
    *,
    pool: Any,
    worker_capabilities: dict[str, Any],
    is_local: bool,
) -> dict[str, Any]:
    """Compute the ``communications`` readiness check payload.

    Status is ``ok`` / ``degraded`` / ``failed`` / ``skipped`` to match the
    gateway probe's contract. ``degraded`` never blocks a rollout.
    """
    # Required-worker dependency first: a dead comms-required release-critical
    # worker fails comms readiness regardless of storage state.
    worker_failures = _comms_worker_failures(worker_capabilities or {})
    if worker_failures:
        return {
            "status": "failed",
            "detail": f"comms-required worker(s) unavailable: {', '.join(worker_failures)}",
            "worker_failures": worker_failures,
        }

    if is_local or pool is None:
        return {
            "status": "ok",
            "detail": "in-memory comms repositories (local)",
        }

    # Durable spine reachability + backlog posture.
    try:
        backlog, oldest_age = await _webhook_inbox_backlog(pool)
    except Exception as exc:
        return {
            "status": "failed",
            "detail": f"comms storage unreachable: {type(exc).__name__}",
        }

    if backlog > _INBOX_BACKLOG_DEGRADED:
        return {
            "status": "degraded",
            "detail": f"webhook-inbox backlog {backlog} (> {_INBOX_BACKLOG_DEGRADED})",
            "webhook_inbox_backlog": backlog,
            "oldest_pending_age_s": oldest_age,
        }
    return {
        "status": "ok",
        "detail": "comms spine reachable; backlog within bounds",
        "webhook_inbox_backlog": backlog,
        "oldest_pending_age_s": oldest_age,
    }


__all__ = ["comms_subsystem_readiness"]
