"""Payment-rail readiness demotion path — failed webhook / silence / credential
→ canonical readiness off-ramp.

Promotion on this plane is evidence-gated and manual: a capability must be
replay-validated, sandbox-validated, etc. by an operator before it climbs the
readiness ladder. But NOTHING automatically demotes a provider that regresses —
a rotated signing secret that rejects every webhook, a credential the provider
starts rejecting, or a provider that goes silent would sit at its promoted
state indefinitely while the plane degrades underneath it. This module closes
that gap with an automatic, monotonic DEMOTION path feeding the canonical
readiness model (:class:`~services.capabilities.readiness_repo.
CapabilityReadinessService.demote`).

Signals → target token:
- ``poll_health == "auth_error"`` (provider rejects the polling key) →
  ``CREDENTIAL_INVALID`` (the most severe off-ramp);
- repeated webhook signature-verification failures within the window →
  ``DEGRADED``;
- a webhook-capable provider that OBSERVED webhooks before and then went silent
  past the window → ``DEGRADED`` (provider silence);
- a pull provider whose poll health is a real degradation (rate_limited /
  server_error / timeout / network_error / bad_response / client_error) →
  ``DEGRADED``.

Honesty rules (mirror the alert evaluator's "unknown is never 0"):
- A provider that NEVER observed a webhook is UNKNOWN (no data), NOT degraded —
  a fresh tenant must not be demoted for having no traffic yet.
- A missing/unseeded capability snapshot is NOT demoted (there is no promoted
  state to regress from); the promotion path owns seeding.

:func:`apply_demotion_if_warranted` is monotonic and idempotent: it only calls
``CapabilityReadinessService.demote`` when the target ranks BELOW the current
snapshot, and it swallows ``ConflictError`` (already at/below target → no-op) so
repeated cycles never thrash or error. The actual demote write is gated behind
``settings.payment_rails.readiness_demotion_enabled`` (default OFF; the
integration pass enables it) and every application is audited on the
payment-rails audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.certification.readiness import CredentialReadiness, readiness_rank
from shared.temporal.instant import ensure_aware_utc

from services.integrations.providers.payment_rails.base import POLL_HEALTH_OK
from services.integrations.providers.payment_rails.lifecycle import (
    PAYMENT_RAILS_CAPABILITY,
)
from services.integrations.providers.payment_rails.receipts import (
    ReceiptState,
)

#: Poll-health tokens that are a REAL degradation (as opposed to absent data or
#: the not_configured off state). ``auth_error`` is handled separately as the
#: credential-invalid signal.
_DEGRADED_POLL_HEALTH = frozenset({
    "rate_limited", "client_error", "server_error", "timeout", "network_error",
    "bad_response",
})

#: Off-ramp tokens a demotion may target (never an on-ramp token).
_DEMOTION_TARGETS = frozenset({
    CredentialReadiness.DEGRADED,
    CredentialReadiness.CREDENTIAL_INVALID,
})


@dataclass(frozen=True)
class DemotionThresholds:
    """Env-aware thresholds for demotion signals (seconds / counts)."""

    verification_failure_window_seconds: float
    verification_failure_warn: float
    provider_silence_seconds: float

    @classmethod
    def from_settings(cls, settings: Any = None) -> "DemotionThresholds":
        if settings is None:
            from config.settings import settings as _settings

            settings = _settings
        pr = settings.payment_rails
        return cls(
            verification_failure_window_seconds=float(
                pr.alert_webhook_verification_failure_window_seconds
            ),
            verification_failure_warn=float(pr.alert_webhook_verification_failure_warn),
            provider_silence_seconds=float(pr.alert_no_webhook_seconds),
        )


@dataclass(frozen=True)
class DemotionVerdict:
    """A per-(tenant, provider) demotion classification.

    ``target`` is the canonical readiness token the provider should be demoted
    to, or ``None`` when no demotion signal is present. ``signals`` lists the
    contributing durable signals (safe tokens only — never secrets or payloads).
    ``firing`` is True iff a demotion is warranted.
    """

    provider: str
    target: Optional[CredentialReadiness]
    reason: str
    signals: list[str] = field(default_factory=list)

    @property
    def firing(self) -> bool:
        return self.target is not None


def _no_signal(provider: str, reason: str = "no demotion signal") -> DemotionVerdict:
    return DemotionVerdict(provider=provider, target=None, reason=reason)


def classify_demotion(
    *,
    provider: str,
    verification_failures: int,
    verification_warn: float,
    webhook_observed: bool,
    webhook_age_seconds: Optional[float],
    silence_seconds: float,
    poll_health: Optional[str],
) -> DemotionVerdict:
    """Pure classifier: durable signals → demotion target (no IO).

    Order of severity: CREDENTIAL_INVALID (provider rejects the key) >
    DEGRADED (verification failures / silence / poll degradation). A
    never-observed webhook provider with a healthy/absent poll state is
    UNKNOWN, not degraded — no data must never masquerade as a demotion signal.
    """
    # 1. Credential invalid — the most severe off-ramp.
    if poll_health == "auth_error":
        return DemotionVerdict(
            provider=provider,
            target=CredentialReadiness.CREDENTIAL_INVALID,
            reason="provider rejects the polling credential (auth_error)",
            signals=["credential_invalid"],
        )
    # 2. Repeated webhook signature-verification failures.
    if verification_failures >= max(1, verification_warn):
        return DemotionVerdict(
            provider=provider,
            target=CredentialReadiness.DEGRADED,
            reason=(
                f"{verification_failures} webhook verification failures "
                f"(>= {verification_warn:g})"
            ),
            signals=["webhook_verification_failures"],
        )
    # 3. Provider silence — only a provider that OBSERVED signals before can be
    #    "silent"; a provider with zero history is unknown, not degraded.
    if webhook_observed and webhook_age_seconds is not None and (
        webhook_age_seconds > silence_seconds
    ):
        return DemotionVerdict(
            provider=provider,
            target=CredentialReadiness.DEGRADED,
            reason=(
                f"provider silent for {webhook_age_seconds:g}s "
                f"(> {silence_seconds:g}s window)"
            ),
            signals=["provider_silence"],
        )
    # 4. Pull-provider poll degradation (real classification, not absent data).
    if poll_health is not None and poll_health not in (None, POLL_HEALTH_OK, "webhook_only",
                                                       "not_configured"):
        if poll_health in _DEGRADED_POLL_HEALTH:
            return DemotionVerdict(
                provider=provider,
                target=CredentialReadiness.DEGRADED,
                reason=f"poll health degraded ({poll_health})",
                signals=["poll_degraded"],
            )
    return _no_signal(provider)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return ensure_aware_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (ValueError, TypeError):
        return None


def _age_seconds(ts: Optional[str], now: datetime) -> Optional[float]:
    parsed = _parse_iso(ts)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _verification_failures(
    receipts: list[dict[str, Any]], now: datetime, window_seconds: float
) -> int:
    count = 0
    for r in receipts:
        if r.get("current_stage") not in (ReceiptState.REJECTED, ReceiptState.QUARANTINED):
            continue
        age = _age_seconds(r.get("last_attempted_at") or r.get("received_at"), now)
        if age is not None and age <= window_seconds:
            count += 1
    return count


async def evaluate_demotion(
    service: Any,
    tenant_id: str,
    provider: str,
    *,
    now: Optional[datetime] = None,
    thresholds: Optional[DemotionThresholds] = None,
) -> DemotionVerdict:
    """Read the tenant's durable payment-rail state and classify a demotion.

    Read-only; never writes. ``service`` / ``now`` / ``thresholds`` are
    injectable so the wiring is testable against a seeded in-memory service.
    """
    if thresholds is None:
        thresholds = DemotionThresholds.from_settings()
    now = now or datetime.now(timezone.utc)

    receipts = await service.repos.receipts.list_for_tenant(tenant_id, provider=provider, limit=1000)
    webhook_receipts = [r for r in receipts if r.get("source") == "webhook"]
    ages = [
        age for r in webhook_receipts
        for age in (_age_seconds(r.get("received_at"), now),)
        if age is not None
    ]
    webhook_observed = bool(webhook_receipts)
    webhook_age = min(ages) if ages else None

    failures = _verification_failures(
        receipts, now, thresholds.verification_failure_window_seconds
    )

    account = await service.repos.accounts.get(tenant_id, provider) or {}
    poll_health = account.get("provider_poll_health")

    return classify_demotion(
        provider=provider,
        verification_failures=failures,
        verification_warn=thresholds.verification_failure_warn,
        webhook_observed=webhook_observed,
        webhook_age_seconds=webhook_age,
        silence_seconds=thresholds.provider_silence_seconds,
        poll_health=poll_health,
    )


def demotion_enabled() -> bool:
    from config.settings import settings

    return bool(getattr(settings.payment_rails, "readiness_demotion_enabled", False))


async def apply_demotion_if_warranted(
    service: Any,
    tenant_id: str,
    provider: str,
    *,
    verdict: Optional[DemotionVerdict] = None,
    actor: str = "readiness_demotion",
    now: Optional[datetime] = None,
    thresholds: Optional[DemotionThresholds] = None,
) -> dict[str, Any]:
    """Evaluate and, when warranted, demote the capability — monotonic + audited.

    Returns a result dict with ``applied`` and a reason token. Never raises for
    a demotion outcome: ``ConflictError`` from the readiness repo (already at or
    below the target) is a no-op, and a missing/unseeded snapshot is skipped
    (there is no promoted state to regress). The whole path is best-effort — a
    demotion failure must never break webhook/repair flow.
    """
    if not demotion_enabled():
        return {"applied": False, "reason": "disabled", "provider": provider}
    if verdict is None:
        verdict = await evaluate_demotion(service, tenant_id, provider, now=now, thresholds=thresholds)
    if not verdict.firing or verdict.target not in _DEMOTION_TARGETS:
        return {"applied": False, "reason": "no_demotion", "provider": provider,
                "signals": verdict.signals}

    try:
        from services.capabilities.readiness_repo import CapabilityReadinessService

        svc = CapabilityReadinessService()
        snapshot = await svc.snapshot(tenant_id, PAYMENT_RAILS_CAPABILITY)
        if snapshot is None:
            return {"applied": False, "reason": "not_seeded", "provider": provider,
                    "target": verdict.target.value, "signals": verdict.signals}
        current = CredentialReadiness(snapshot.get("state", "scaffolded"))
        if readiness_rank(current) <= readiness_rank(verdict.target):
            return {"applied": False, "reason": "already_at_or_below", "provider": provider,
                    "current": current.value, "target": verdict.target.value,
                    "signals": verdict.signals}
        await svc.demote(
            tenant_id,
            PAYMENT_RAILS_CAPABILITY,
            target=verdict.target,
            evidence={
                "provider": provider,
                "signals": verdict.signals,
                "reason": verdict.reason,
                "plane": "payment_rails",
            },
            reason=verdict.reason,
            actor=actor,
        )
    except Exception as exc:  # noqa: BLE001 — no-op on already-demoted / unavailable
        conflict = getattr(exc, "status_code", None) == 409 or "monotonic" in str(exc).lower()
        if conflict or "already" in str(exc).lower():
            return {"applied": False, "reason": "already_at_or_below", "provider": provider,
                    "signals": verdict.signals}
        return {"applied": False, "reason": "demotion_failed", "provider": provider,
                "signals": verdict.signals, "error": str(exc)}

    await _audit_demotion(service, tenant_id, provider, verdict, actor)
    return {"applied": True, "reason": "demoted", "provider": provider,
            "target": verdict.target.value, "signals": verdict.signals}


async def _audit_demotion(
    service: Any, tenant_id: str, provider: str, verdict: DemotionVerdict, actor: str
) -> None:
    try:
        await service.repos.audit.record(tenant_id, {
            "provider": provider,
            "action": "readiness_demoted",
            "detail": {
                "target": verdict.target.value if verdict.target else None,
                "signals": verdict.signals,
                "reason": verdict.reason,
                "actor": actor,
            },
        })
    except Exception:  # noqa: BLE001 — audit is best-effort
        pass


async def run_readiness_demotion_cycle(
    service: Any = None,
    *,
    limit: int = 500,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Supervised cross-tenant demotion sweep.

    Enumerates the durable provider accounts (cross-tenant, control-plane),
    evaluates each (tenant, provider) and applies warranted demotions. Best
    effort per row — one tenant must never abort the sweep. Returns counters.
    """
    if service is None:
        from services.integrations.providers.payment_rails.service import (
            get_payment_rails_service,
        )

        service = get_payment_rails_service()
    now = now or datetime.now(timezone.utc)
    thresholds = DemotionThresholds.from_settings()

    accounts = (await service.repos.accounts.list_all())[: max(1, min(limit, 2000))]
    stats = {"evaluated": 0, "applied": 0, "no_demotion": 0, "skipped": 0, "failed": 0}
    for account in accounts:
        tenant_id = account.get("tenant_id")
        provider = account.get("provider")
        if not tenant_id or not provider:
            continue
        stats["evaluated"] += 1
        try:
            result = await apply_demotion_if_warranted(
                service, tenant_id, provider, actor="readiness_demotion_worker", now=now,
                thresholds=thresholds,
            )
            if result.get("applied"):
                stats["applied"] += 1
            elif result.get("reason") in ("no_demotion", "already_at_or_below"):
                stats["no_demotion"] += 1
            else:
                stats["skipped"] += 1
        except Exception:  # noqa: BLE001 — one tenant must not abort the sweep
            stats["failed"] += 1
    return stats


__all__ = [
    "DemotionThresholds",
    "DemotionVerdict",
    "classify_demotion",
    "evaluate_demotion",
    "demotion_enabled",
    "apply_demotion_if_warranted",
    "run_readiness_demotion_cycle",
    "PAYMENT_RAILS_CAPABILITY",
]
