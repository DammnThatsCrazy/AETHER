"""Scheduled agent behavior jobs (supervised worker, default OFF).

Per active deployment agent this records the last *complete* UTC day as a
stored snapshot, compares the two latest stored windows for drift, and, when
the behavior evidence yields Risk360 signals, persists a deterministic
Risk360 assessment for the agent subject. Everything it writes is derived and
rebuildable (ADR-AB-002); it reads canonical facts and never writes them
(ADR-AB-008). One agent failing never stops the pass.

Tenants and agents come from the deployment registry, the same source the
telemetry plane validates against. Agent refs stay source-reported.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.agent_behavior.scheduler")

MAX_AGENTS_PER_PASS = 500


@dataclass
class PassReport:
    window: tuple[str, str]
    agents_seen: int = 0
    snapshots_recorded: int = 0
    drift_detected: int = 0
    assessments_persisted: int = 0
    skipped_no_facts: int = 0
    skipped_truncated_snapshots: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "window": list(self.window)}


def last_complete_day(now: Optional[datetime] = None) -> tuple[str, str]:
    """``[start, end)`` of the most recent complete UTC day, ISO-8601 with ``Z``."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), end.strftime(fmt)


# Where the next pass resumes. A process-local position is enough: a restart
# only restarts the rotation, and every pass stays bounded.
_rotation_after: Optional[tuple[str, str]] = None


def fair_batch(pairs: Iterable[tuple[str, str]], limit: int,
               after: Optional[tuple[str, str]] = None) -> list[tuple[str, str]]:
    """Next bounded batch, resuming after ``after`` and interleaving tenants.

    Tenants are taken round-robin so one tenant cannot fill the batch, and the
    order is rotated to start after the previous pass's last pair, so every
    active agent is visited within ceil(n / limit) passes."""
    by_tenant: dict[str, list[str]] = defaultdict(list)
    for tenant_id, agent_id in sorted(set(pairs)):
        by_tenant[tenant_id].append(agent_id)
    order: list[tuple[str, str]] = []
    queues = [(t, list(agents)) for t, agents in sorted(by_tenant.items())]
    while queues:
        for tenant_id, agents in queues:
            order.append((tenant_id, agents.pop(0)))
        queues = [(t, a) for t, a in queues if a]
    if after in order:
        start = order.index(after) + 1
        order = order[start:] + order[:start]
    return order[:limit]


async def active_agents(limit: int = MAX_AGENTS_PER_PASS) -> list[tuple[str, str]]:
    """Next fair batch of distinct ``(tenant_id, agent_id)`` of active registered
    deployments, advancing the rotation.

    A system-level enumeration (like retention sweeps); every later read is
    tenant-scoped."""
    global _rotation_after
    from actions.agent.deployments import get_deployment_repository

    pairs = {
        (r["tenant_id"], r["agent_id"])
        for r in await get_deployment_repository().list_all()
        if r.get("status") == "active" and r.get("tenant_id") and r.get("agent_id")
    }
    batch = fair_batch(pairs, limit, _rotation_after)
    if batch:
        _rotation_after = batch[-1]
    return batch


async def run_agent(tenant_id: str, agent_ref: str, window: tuple[str, str], report: PassReport) -> None:
    from actions.agent.behavior_read_model import (
        compose_behavior_read_model, load_behavior_inputs, load_window_facts,
    )
    from intelligence.agent_behavior.model import build_behavior_model
    from intelligence.agent_behavior.snapshot_store import (
        BehaviorSnapshotRepository, drift_over_stored_windows, record_window,
    )
    from intelligence.risk360.pipeline import compute_assessment, persist_assessment
    from intelligence.risk360.signals import RiskEvidenceBundle, signals_from_evidence_bundle

    inputs = await load_behavior_inputs(tenant_id, agent_ref)
    if not inputs.facts or not any(f.agent_ref == agent_ref for f in inputs.facts):
        report.skipped_no_facts += 1
        return
    repo = BehaviorSnapshotRepository()
    # The snapshot reads the requested window itself (paged), not the newest
    # facts, so today's traffic cannot crowd yesterday out. A window still too
    # large to read whole is skipped rather than overwrite a stored snapshot.
    window_facts, window_truncated = await load_window_facts(tenant_id, agent_ref, window)
    if window_truncated:
        report.skipped_truncated_snapshots += 1
    else:
        await record_window(repo, tenant_id, agent_ref, window_facts, window)
        report.snapshots_recorded += 1
    drift = await drift_over_stored_windows(repo, tenant_id, agent_ref)
    if drift.get("status") == "drift_detected":
        report.drift_detected += 1

    sections = compose_behavior_read_model(inputs, agent_ref)["sections"]
    authority = sections["authority"]["data"] if sections["authority"]["state"] == "available" else []
    adversarial = (sections["risk"]["data"] or {}).get("adversarial", [])
    bundle = RiskEvidenceBundle(agent_behavior={
        "model": build_behavior_model(inputs.facts, agent_ref),
        "authority_checks": authority, "adversarial": adversarial, "drift": drift,
    })
    signals = signals_from_evidence_bundle(
        bundle, subject_kind="agent", subject_id=agent_ref, tenant_id=tenant_id)
    if not signals:
        return
    result = compute_assessment(
        tenant_id=tenant_id, subject_kind="agent", subject_id=agent_ref, evidence_bundle=bundle)
    await persist_assessment(result, tenant_id=tenant_id, signals=signals)
    report.assessments_persisted += 1


async def run_once(now: Optional[datetime] = None, agents: Optional[list[tuple[str, str]]] = None) -> PassReport:
    window = last_complete_day(now)
    report = PassReport(window=window)
    for tenant_id, agent_ref in (agents if agents is not None else await active_agents()):
        report.agents_seen += 1
        try:
            await run_agent(tenant_id, agent_ref, window, report)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one agent must not stop the pass
            report.errors.append(f"{tenant_id}:{agent_ref}:{type(exc).__name__}")
            metrics.increment("agent_behavior_job_errors_total")
    metrics.increment("agent_behavior_job_snapshots_total", value=report.snapshots_recorded)
    return report


async def run_agent_behavior_loop(interval_seconds: Optional[float] = None) -> None:
    from config.settings import settings

    cfg = settings.external_agent_telemetry
    interval = float(interval_seconds or cfg.behavior_jobs_interval_seconds)
    while True:
        try:
            if cfg.behavior_jobs_enabled:
                report = await run_once()
                logger.info("agent behavior pass: %s", report.to_dict())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a loop must never die on one tick
            logger.warning("agent behavior pass failed: %s", type(exc).__name__)
            metrics.increment("agent_behavior_job_pass_errors_total")
        await asyncio.sleep(interval)


def build_agent_behavior_coro():
    return run_agent_behavior_loop()
