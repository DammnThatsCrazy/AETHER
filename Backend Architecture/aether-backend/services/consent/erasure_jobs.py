"""Durable consent-erasure job (``consent.erasure`` on the jobs platform).

Replaces the fire-and-forget ``asyncio.create_task(handle_erasure_background(...))``
path in services/consent/routes.py: the DSR route now opens a DSR propagation
record and durably enqueues a ``consent.erasure`` job, and this handler executes
the measurement erasure — so a process death between request and completion is
recovered by the jobs worker (lease sweep + retry) instead of silently lost.

Evidence contract: the handler marks a propagation step ONLY for a store it
actually erased, carrying that store's own receipt (row counts, the job id as the
audit pointer). ``MeasurementPrivacyHandler.handle_erasure`` decomposes into
per-store try blocks (touchpoint tombstones, conversion tombstones, journey
rebuild) that all live in the measurement/attribution store, so the
``attribution_records`` component is marked from that store's tombstone counts.

The handler then reaches the mobile plane, erasing three more stores — each in
its own isolated try/except and each marked with its OWN real erased-row count:
``continuation_records`` (continuations + selections), ``mobile_installations``
(installations + push_subscriptions), and ``client_sync_records``
(sync_change_log). A store is never marked with a fabricated count; a per-store
failure marks that component ``failed`` and keeps the whole job retryable.

The operator (kyber) device plane is erased the same way (M8-E1): three stores —
``kyber_trusted_devices``, ``kyber_webauthn_credentials``,
``kyber_device_proof_keys`` — each erased by the DSR subject as an operator id
and each marked with its own real erased-row count. The append-only
``kyber_device_approval_events`` audit ledger is NOT erased (preserve/legal hold).
"""

from __future__ import annotations

from typing import Any

from shared.logger.logger import get_logger, metrics

from services.jobs.handlers import (
    HANDLER_REGISTRY,
    JobContext,
    JobOutcome,
    register_handler,
)

logger = get_logger("aether.consent.erasure_jobs")

ERASURE_JOB_TYPE = "consent.erasure"

# The single dsr_propagation component the measurement erasure produces real
# evidence for (see module docstring).
MEASUREMENT_COMPONENT = "attribution_records"

# The mobile-plane dsr_propagation components this handler now erases and marks
# with each store's own real erased-row receipt:
#   continuation_records → continuations + selections
#   mobile_installations → installations + push_subscriptions
#   client_sync_records  → sync_change_log
MOBILE_CONTINUATION_COMPONENT = "continuation_records"
MOBILE_INSTALLATION_COMPONENT = "mobile_installations"
MOBILE_CLIENT_SYNC_COMPONENT = "client_sync_records"

# The operator (kyber) device-plane components (M8-E1). A data-subject erasure
# that names an operator physically erases the device personal data: trusted
# devices, WebAuthn credentials and device proof keys. The append-only
# ``kyber_device_approval_events`` audit ledger is deliberately NOT covered —
# storage policy is ``preserve``/legal hold, and a DSR must not destroy the
# evidence of who approved which machine.
KYBER_DEVICE_COMPONENT = "kyber_trusted_devices"
KYBER_WEBAUTHN_COMPONENT = "kyber_webauthn_credentials"
KYBER_PROOF_KEY_COMPONENT = "kyber_device_proof_keys"


def _kyber_device_eraser(repo_cls: type) -> Any:
    """Build a mobile-eraser-shaped hook for one kyber device store.

    The mobile erasure loop calls ``erase(scope, user_id)``; kyber device stores
    are operator-keyed and NOT tenant-scoped, so the hook ignores ``scope`` and
    erases by the DSR subject. A subject who is not an operator (the normal
    tenant-DSR case) erases 0 rows and is marked ``completed`` with a real zero
    receipt — the hook is idempotent and never fabricates a count.
    """

    async def _erase(_scope: str, operator_id: str) -> int:
        return await repo_cls().delete_by_operator(operator_id)

    return _erase


def register_consent_erasure_handler() -> None:
    """Register the internal-only erasure job handler exactly once at startup."""
    if ERASURE_JOB_TYPE in HANDLER_REGISTRY:
        return

    @register_handler(ERASURE_JOB_TYPE, tenant_invocable=False)
    async def _handle(payload: dict, ctx: JobContext) -> JobOutcome:
        # Local imports keep startup registration free of repository imports.
        from repositories.repos import ConsentRepository
        from services.dsr_propagation.service import dsr_propagation_service
        from services.measurement.privacy import handle_erasure_background

        user_id = str(payload.get("user_id") or "")
        if not user_id:
            return JobOutcome(status="failed", result={}, error="user_id is required")
        propagation_request_id = payload.get("propagation_request_id")
        dsr_id = payload.get("dsr_id")

        if propagation_request_id:
            await dsr_propagation_service.mark_step(
                propagation_request_id,
                MEASUREMENT_COMPONENT,
                "running",
                tenant_id=ctx.tenant_id,
            )

        result = await handle_erasure_background(ctx.tenant_id, user_id)
        errors = [str(e) for e in (result.get("errors") or [])]
        records_impacted = int(result.get("touchpoints_tombstoned") or 0) + int(
            result.get("conversions_tombstoned") or 0
        )

        if propagation_request_id:
            step_status = "failed" if errors else "completed"
            # Evidence is the store's OWN receipt: the rows it tombstoned and
            # the durable job id as the audit pointer for this execution.
            await dsr_propagation_service.mark_step(
                propagation_request_id,
                MEASUREMENT_COMPONENT,
                step_status,
                tenant_id=ctx.tenant_id,
                records_impacted=records_impacted,
                requires_recompute=not bool(result.get("journey_rebuild_triggered")),
                audit_event_id=ctx.job_id,
            )
            # Program 3 M2: attach the re-attribution correction as DSR
            # propagation evidence on the same attribution_records component —
            # additive to the tombstone receipt above, only when re-attribution
            # actually ran (a profile with affected conversions).
            reattribution_summary = result.get("reattribution")
            if reattribution_summary:
                await dsr_propagation_service.record_reattribution(
                    propagation_request_id,
                    reattribution_summary,
                    tenant_id=ctx.tenant_id,
                    component=MEASUREMENT_COMPONENT,
                )

        # ── Mobile continuation / installation / client-sync stores ──────────
        # Each store is erased in its OWN try/except so one store's failure never
        # blocks the others, and each component is marked with that store's REAL
        # erased-row count (never a fabricated receipt). Only marked when a
        # propagation record exists (mirrors the measurement guard above).
        if propagation_request_id:
            from services.client_sync import service as client_sync_service
            from services.continuation import service as continuation_service
            from services.kyber.devices.repository import (
                DeviceProofKeyRepository,
                TrustedDeviceRepository,
                WebAuthnCredentialRepository,
            )
            from services.mobile import service as mobile_service

            # The three mobile stores isolate by ``t:{tenant_id}`` (installations +
            # push_subscriptions, continuations + selections, sync_change_log);
            # the kyber device stores are operator-keyed and ignore the scope,
            # erasing by the DSR subject as operator id (M8-E1).
            scope = mobile_service.tenant_scope(ctx.tenant_id)
            mobile_erasers = (
                (MOBILE_CONTINUATION_COMPONENT, continuation_service.erase_principal),
                (MOBILE_INSTALLATION_COMPONENT, mobile_service.erase_principal),
                (MOBILE_CLIENT_SYNC_COMPONENT, client_sync_service.erase_principal),
                (KYBER_DEVICE_COMPONENT, _kyber_device_eraser(TrustedDeviceRepository)),
                (KYBER_WEBAUTHN_COMPONENT, _kyber_device_eraser(WebAuthnCredentialRepository)),
                (KYBER_PROOF_KEY_COMPONENT, _kyber_device_eraser(DeviceProofKeyRepository)),
            )
            for component, erase in mobile_erasers:
                try:
                    erased = await erase(scope, user_id)
                except Exception as exc:  # noqa: BLE001 — isolate per-store failure
                    errors.append(f"{component}: {exc}")
                    try:
                        await dsr_propagation_service.mark_step(
                            propagation_request_id,
                            component,
                            "failed",
                            tenant_id=ctx.tenant_id,
                            audit_event_id=ctx.job_id,
                        )
                    except Exception:  # noqa: BLE001 — never let evidence-marking abort the loop
                        logger.warning(
                            "failed to mark DSR component %s failed", component, exc_info=True
                        )
                    continue
                # Evidence is the store's OWN receipt: the rows it erased + the
                # durable job id as the audit pointer for this execution.
                await dsr_propagation_service.mark_step(
                    propagation_request_id,
                    component,
                    "completed",
                    tenant_id=ctx.tenant_id,
                    records_impacted=int(erased),
                    audit_event_id=ctx.job_id,
                )

        if dsr_id:
            repo = ConsentRepository()
            record_id = f"dsr_{dsr_id}"
            dsr_row = await repo.find_by_id(record_id)
            if dsr_row is not None and dsr_row.get("tenant_id") == ctx.tenant_id:
                await repo.update(
                    record_id,
                    {
                        "status": "failed" if errors else "completed",
                        "erasure_result": result,
                        "propagation_request_id": propagation_request_id,
                    },
                )

        await ctx.emit_event(
            "consent.erasure.measurement",
            {
                "user_id": user_id,
                "dsr_id": dsr_id,
                "propagation_request_id": propagation_request_id,
                "records_impacted": records_impacted,
                "journey_rebuild_triggered": bool(result.get("journey_rebuild_triggered")),
                "errors": errors,
            },
        )
        metrics.increment(
            "consent_erasure_jobs",
            labels={"outcome": "failed" if errors else "succeeded"},
        )

        if errors:
            # Every operation above is idempotent, so a per-store failure is
            # retryable: fail the attempt and let the worker re-run the whole
            # erasure with backoff (dead-letter after max attempts).
            return JobOutcome(status="failed", result=result, error="; ".join(errors))
        return JobOutcome(status="succeeded", result=result)
