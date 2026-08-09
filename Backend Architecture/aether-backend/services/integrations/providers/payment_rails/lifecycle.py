"""Payment-rail rollout-control lifecycle gate.

The payment-rails plane ships several delivery/observability controls that are
default-OFF for safe rollout: the derived-condition alert evaluator
(``alert_eval_enabled``), the durable canonical-event outbox
(``canonical_outbox_enabled``), and observation usage metering
(``usage_metering_enabled``). Their raw env flags are NOT the whole story — this
module ties each control's enablement to the payment-rails CAPABILITY LIFECYCLE
(the canonical ``CapabilityReadiness`` token the readiness model persists per
tenant+capability, :mod:`shared.certification.readiness` + the capability
readiness repo).

Rules:
- Each control declares a MINIMUM lifecycle stage (a ``CredentialReadiness``)
  it may run at. ``controls_for_readiness`` is the pure mapping.
- ``rollout_control_permitted(name)`` is the enforcement gate: a control runs
  only when its flag is ON **and** the current lifecycle stage is at or above
  its minimum. When the current stage is UNKNOWN (nothing wired / capability
  not yet seeded), the gate FAILS OPEN to the raw flag — so wiring this gate
  in never changes behavior for a deployment that has not declared a lifecycle
  stage, and once a stage IS declared the gate becomes fail-closed.
- ``rollout_control_enabled(name)`` is the lenient read used to *decide* an
  action (e.g. whether to write an outbox row): flag ON, or lifecycle already
  at/above the minimum.
- ``current_lifecycle_stage`` prefers an explicit operator override
  (``AETHER_PAYMENT_CAPABILITY_LIFECYCLE_STAGE``) and otherwise best-effort
  reads the persisted per-tenant capability readiness. The integration pass
  sets the settings default for the override.

Pure and import-safe: no settings import at module load; the control registry
is plain data a test can assert on.
"""

from __future__ import annotations

import dataclasses
from typing import Optional

from shared.certification.readiness import CredentialReadiness, readiness_rank

#: Canonical capability name the readiness model records payment rails under.
PAYMENT_RAILS_CAPABILITY = "payment_rails"

#: Settings attribute on ``settings.payment_rails`` holding the lifecycle-stage
#: override (an empty value means "not declared → use persisted readiness").
SETTINGS_LIFECYCLE_STAGE_ATTR = "capability_lifecycle_stage"


@dataclasses.dataclass(frozen=True)
class RolloutControl:
    """One default-OFF delivery/observability control and its lifecycle gate.

    ``settings_attr`` is the raw flag name on ``settings.payment_rails``.
    ``min_readiness`` is the canonical readiness token the capability must have
    reached before the control is PERMITTED (fail-closed once a stage exists).
    ``env_var`` documents the flag's env override for ops.
    """

    name: str
    settings_attr: str
    min_readiness: CredentialReadiness
    env_var: str
    description: str

    @property
    def min_rank(self) -> int:
        return readiness_rank(self.min_readiness)


#: Registry of every rollout control and its lifecycle minimum.
ROLLOUT_CONTROLS: dict[str, RolloutControl] = {
    control.name: control
    for control in (
        RolloutControl(
            name="derived_alert_evaluator",
            settings_attr="alert_eval_enabled",
            min_readiness=CredentialReadiness.CREDENTIAL_WAITING,
            env_var="AETHER_PAYMENT_ALERT_EVAL_ENABLED",
            description=(
                "in-process derived-condition alert evaluator (reconciliation-"
                "conflict backlog, provider silence, backlog growth) — ops "
                "observability may run as soon as the capability is standing up"
            ),
        ),
        RolloutControl(
            name="canonical_outbox",
            settings_attr="canonical_outbox_enabled",
            min_readiness=CredentialReadiness.OFFLINE_VALIDATED,
            env_var="AETHER_PAYMENT_CANONICAL_OUTBOX_ENABLED",
            description=(
                "durable canonical-event outbox delivery — requires the offline "
                "replay-validation evidence that delivery is idempotent"
            ),
        ),
        RolloutControl(
            name="usage_metering",
            settings_attr="usage_metering_enabled",
            min_readiness=CredentialReadiness.SANDBOX_VALIDATED,
            env_var="AETHER_PAYMENT_USAGE_METERING_ENABLED",
            description=(
                "RevOps observation usage metering — writes billing bookkeeping, "
                "so it waits for sandbox-validated evidence"
            ),
        ),
    )
}


def controls_for_readiness(readiness: CredentialReadiness) -> dict[str, bool]:
    """The recommended enablement of every control at ``readiness``.

    Pure and deterministic: a control is enabled exactly when the capability's
    lifecycle rank is at or above the control's minimum. This is the mapping the
    integration pass can use to derive settings defaults from a declared stage.
    """
    stage_rank = readiness_rank(readiness)
    return {
        name: (control.min_rank <= stage_rank)
        for name, control in ROLLOUT_CONTROLS.items()
    }


def _coerce_stage(raw: object) -> Optional[CredentialReadiness]:
    """Coerce a string/enum stage token to ``CredentialReadiness`` or None."""
    if raw is None:
        return None
    if isinstance(raw, CredentialReadiness):
        return raw
    text = str(raw).strip().lower()
    if not text:
        return None
    try:
        return CredentialReadiness(text)
    except ValueError:
        return None


def settings_lifecycle_stage() -> Optional[CredentialReadiness]:
    """Operator-declared lifecycle stage from settings (empty → None)."""
    from config.settings import settings

    return _coerce_stage(getattr(settings.payment_rails, SETTINGS_LIFECYCLE_STAGE_ATTR, ""))


async def persisted_lifecycle_stage(tenant_id: Optional[str] = None) -> Optional[CredentialReadiness]:
    """Best-effort read of the persisted capability readiness for payment rails.

    Returns ``None`` when the readiness model is unavailable or the capability
    has no snapshot yet (nothing seeded → lifecycle unknown → gates fail open to
    the raw flags). ``tenant_id`` scopes the read; ``None`` reads the
    deployment-wide row keyed under the capability itself, which the promotion
    path seeds. Async: the readiness repo is a ``DurableStore`` (async). Never
    raises — unavailability degrades to "stage unknown", which fails the gates
    open to the raw flags rather than blocking.
    """
    try:
        from services.capabilities.readiness_repo import CapabilityReadinessService

        scope = tenant_id or PAYMENT_RAILS_CAPABILITY
        snapshot = await CapabilityReadinessService().snapshot(scope, PAYMENT_RAILS_CAPABILITY)
        return _coerce_stage((snapshot or {}).get("state"))
    except Exception:  # noqa: BLE001 — readiness unavailable → unknown stage
        return None


async def current_lifecycle_stage(tenant_id: Optional[str] = None) -> Optional[CredentialReadiness]:
    """The payment-rails capability lifecycle stage to gate controls on.

    Explicit operator override wins; otherwise the persisted capability
    readiness. ``None`` = lifecycle not declared (gates fail open to flags).
    """
    return settings_lifecycle_stage() or await persisted_lifecycle_stage(tenant_id)


async def rollout_control_permitted(
    name: str, *, tenant_id: Optional[str] = None, flag: Optional[bool] = None
) -> bool:
    """Enforcement gate: may control ``name`` run right now?

    ``flag`` defaults to the control's raw settings flag. The control runs only
    when the flag is ON **and** the lifecycle stage (when known) is at/above the
    minimum. With no declared stage, falls back to the flag alone so wiring the
    gate never changes un-declared deployments. Async because the persisted
    lifecycle read is async.
    """
    control = ROLLOUT_CONTROLS.get(name)
    if control is None:
        raise KeyError(f"unknown rollout control {name!r}")
    if flag is None:
        from config.settings import settings

        flag = bool(getattr(settings.payment_rails, control.settings_attr, False))
    if not flag:
        return False
    stage = await current_lifecycle_stage(tenant_id)
    if stage is None:
        return True  # lifecycle not declared → flag is authoritative
    return readiness_rank(stage) >= control.min_rank


async def rollout_control_enabled(
    name: str, *, tenant_id: Optional[str] = None, flag: Optional[bool] = None
) -> bool:
    """Lenient read: should an action under control ``name`` be taken now?

    ON when the raw flag is on, OR when the lifecycle stage has reached the
    control's minimum — used to decide an action (e.g. write an outbox row).
    Unlike :func:`rollout_control_permitted` this never blocks a flagged-on
    control, but once a lifecycle stage exists it still reflects it. Async
    because the persisted lifecycle read is async.
    """
    control = ROLLOUT_CONTROLS.get(name)
    if control is None:
        raise KeyError(f"unknown rollout control {name!r}")
    if flag is None:
        from config.settings import settings

        flag = bool(getattr(settings.payment_rails, control.settings_attr, False))
    if flag:
        return True
    stage = await current_lifecycle_stage(tenant_id)
    return stage is not None and readiness_rank(stage) >= control.min_rank


__all__ = [
    "PAYMENT_RAILS_CAPABILITY",
    "SETTINGS_LIFECYCLE_STAGE_ATTR",
    "RolloutControl",
    "ROLLOUT_CONTROLS",
    "controls_for_readiness",
    "settings_lifecycle_stage",
    "persisted_lifecycle_stage",
    "current_lifecycle_stage",
    "rollout_control_permitted",
    "rollout_control_enabled",
]
