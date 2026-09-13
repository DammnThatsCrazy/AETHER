"""Tenant Launch Readiness (§3.13).

Computes a launch-readiness checklist for a tenant. Each check is one of the
§3.13 launch gates and carries a status of ``pending`` / ``passed`` / ``failed``
/ ``not_applicable`` plus optional evidence.

Design principles:

* **Additive** — introduces its own table (``tenant_launch_readiness``) and
  reuses the shared ``_ScopedRepo``; touches nothing else.
* **Fail-closed** — a tenant is ``ready`` only when *every required* check is
  ``passed`` (or explicitly ``not_applicable``). Missing signals default to
  ``pending`` (blocking), never to passed.

``evaluate(tenant_id, signals)`` is pure. ``record`` / ``get`` persist and read
the latest snapshot per tenant via :class:`TenantReadinessRepository`.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.security.repositories import _ScopedRepo

logger = get_logger("aether.tenant_readiness")

# Check status values.
STATUS_PENDING = "pending"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_NOT_APPLICABLE = "not_applicable"

VALID_STATUSES: tuple[str, ...] = (
    STATUS_PENDING,
    STATUS_PASSED,
    STATUS_FAILED,
    STATUS_NOT_APPLICABLE,
)

# A check is "satisfied" (non-blocking) when passed or explicitly N/A.
_SATISFIED = frozenset({STATUS_PASSED, STATUS_NOT_APPLICABLE})

# Canonical §3.13 launch-readiness checks, in evaluation/display order.
LAUNCH_READINESS_CHECKS: tuple[str, ...] = (
    "tenant_created",
    "api_key_issued",
    "sdk_or_connector_configured",
    "events_received",
    "consent_snapshots_received",
    "bronze_write_verified",
    "event_bus_verified",
    "identity_resolution_verified",
    "graph_projection_verified",
    "profile360_verified",
    "data_quality_verified",
    "security_policy_verified",
    "tenant_isolation_verified",
    "dsr_export_verified",
    "dsr_delete_verified",
    "usage_metering_verified",
    "billing_mode_verified",
    "rate_limits_verified",
    "feature_flags_verified",
    "model_policy_verified",
    "connector_signature_verified",
    "generic_webhook_disabled",
    "kyber_operator_visibility_verified",
    "tenant_trust_states_visible",
    "financial_value_semantics_verified",
)


def _normalize_signal(raw: Any) -> tuple[str, Optional[Any]]:
    """Normalize a raw per-check signal into ``(status, evidence)``.

    Accepted forms:

    * ``True``  -> ``("passed", None)``
    * ``False`` -> ``("failed", None)``
    * ``None`` / missing -> ``("pending", None)``
    * a status string in :data:`VALID_STATUSES` -> ``(status, None)``
    * a dict ``{"status": ..., "evidence": ...}`` -> ``(status, evidence)``

    Raises ``ValueError`` on an explicit but invalid status.
    """
    if raw is None:
        return STATUS_PENDING, None
    if raw is True:
        return STATUS_PASSED, None
    if raw is False:
        return STATUS_FAILED, None
    if isinstance(raw, str):
        if raw not in VALID_STATUSES:
            raise ValueError(f"invalid readiness status: {raw!r}")
        return raw, None
    if isinstance(raw, dict):
        status = raw.get("status", STATUS_PENDING)
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid readiness status: {status!r}")
        return status, raw.get("evidence")
    # Any other truthy/falsey object: fail closed to pending.
    return STATUS_PENDING, None


class TenantReadinessRepository(_ScopedRepo):
    """Persists the latest launch-readiness snapshot per tenant.

    Keyed by ``tenant_id`` (one row per tenant, latest wins). Tenant-scoped via
    the ``tenant_id`` column so cross-tenant reads stay isolated.
    """

    def __init__(self) -> None:
        super().__init__("tenant_launch_readiness")


class TenantLaunchReadiness:
    """Computes and persists §3.13 tenant launch-readiness checklists."""

    #: All checks are required by default; a required check must be satisfied
    #: (passed or not_applicable) for the tenant to be ``ready``.
    CHECKS: tuple[str, ...] = LAUNCH_READINESS_CHECKS

    def __init__(
        self,
        repo: Optional[TenantReadinessRepository] = None,
        required: Optional[set[str]] = None,
    ) -> None:
        self._repo = repo or TenantReadinessRepository()
        self.required: frozenset[str] = frozenset(
            required if required is not None else self.CHECKS
        )

    # ── Pure evaluation ──────────────────────────────────────────────────────

    def evaluate(self, tenant_id: str, signals: dict[str, Any]) -> dict[str, Any]:
        """Evaluate the checklist for ``tenant_id`` against ``signals``.

        Returns ``{"tenant_id", "checks": [...], "ready": bool, "blocking": [...]}``.
        ``ready`` is True iff every required check is satisfied. ``blocking``
        lists the required checks still ``pending`` or ``failed``.
        """
        signals = signals or {}
        checks: list[dict[str, Any]] = []
        blocking: list[str] = []

        for name in self.CHECKS:
            status, evidence = _normalize_signal(signals.get(name))
            check: dict[str, Any] = {"name": name, "status": status}
            if evidence is not None:
                check["evidence"] = evidence
            checks.append(check)
            if name in self.required and status not in _SATISFIED:
                blocking.append(name)

        return {
            "tenant_id": tenant_id,
            "checks": checks,
            "ready": not blocking,
            "blocking": blocking,
        }

    # ── Persistence ──────────────────────────────────────────────────────────

    async def record(
        self, tenant_id: str, signals: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate and persist the latest readiness snapshot for a tenant."""
        evaluation = self.evaluate(tenant_id, signals)
        record = {
            "readiness_id": tenant_id,
            "tenant_id": tenant_id,
            "checks": evaluation["checks"],
            "ready": evaluation["ready"],
            "blocking": evaluation["blocking"],
            "recorded_at": utc_now().isoformat(),
        }
        stored = await self._repo.insert(tenant_id, record)
        logger.info(
            "tenant_launch_readiness recorded tenant=%s ready=%s blocking=%d",
            tenant_id, evaluation["ready"], len(evaluation["blocking"]),
        )
        return stored

    async def get(self, tenant_id: str) -> Optional[dict[str, Any]]:
        """Return the latest recorded readiness snapshot for a tenant (or None).

        Tenant-scoped: a snapshot whose ``tenant_id`` does not match is never
        returned.
        """
        record = await self._repo.find_by_id(tenant_id)
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return record
