"""Payment-rail :class:`IntegrationAdapter` — observe-only rails on the §17 seam.

This module lifts AETHER's observe-only payment rails (Privy, Stripe crypto
onramp, Coinbase, MoonPay, Bridge) onto the *same* §17 lifecycle contract every
capability adapter presents (:class:`IntegrationAdapter`), without changing the
rails themselves.

Honesty / safety invariants preserved from the rails (see
``services.integrations.providers.payment_rails.base``):

* **Observe-only.** AETHER never executes, settles, originates, signs, or
  custodies funds. This adapter exposes *no* fund-movement capability. Every
  operation that would imply movement (authorization, backfill of history,
  account discovery, self-registration of webhooks) returns a typed
  ``not_supported`` — never a fabricated capability and never an exception.
* **Sanitized.** Provider payloads are stripped of sensitive fields (PAN, CVV,
  bank/routing, IBAN, SSN, KYC) recursively *before* they reach any store,
  log, or result. Every data path here routes through the rail's own
  sanitizing helpers, so a raw payment instrument can never surface in an
  :class:`AdapterResult`.
* **Manifest-gated.** Capability is read from the rail's honest observe-only
  :class:`ProviderManifest` (``<rail>.payment_rails.observe``): incremental
  sync only when the rail polls, reconciliation only when the manifest
  declares it. The adapter claims nothing the manifest does not evidence.

The wave is additive: no rail, manifest, registry, or route is mutated.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from services.integrations.adapter import AdapterContext, IntegrationAdapter
from services.integrations.providers.payment_rails import (
    ADAPTERS as PAYMENT_RAIL_ADAPTERS,
    get_adapter,
)
from services.integrations.providers.payment_rails.base import (
    PaymentRailAdapter,
    sanitize_payload,
)
from shared.integration_contracts.catalog import (
    PAYMENT_RAIL_MANIFESTS,
    manifest_from_payment_rail_adapter,
)
from shared.integration_contracts.manifest import ProviderManifest
from shared.integration_contracts.results import AdapterResult, AdapterStatus

# Prebuilt, honesty-validated observe-only manifest per registered rail family.
_PAYMENT_RAIL_MANIFEST_BY_FAMILY: dict[str, ProviderManifest] = {
    manifest.provider_family: manifest for manifest in PAYMENT_RAIL_MANIFESTS
}

# Projection of a rail ``ConnectionTestResult.status`` onto the canonical
# (success, AdapterStatus) pair for :meth:`health_check`. ``ok`` and
# ``webhook_only`` are both healthy, supported terminal states (a webhook-only
# rail's "connection" IS its signature verification). ``not_configured`` is an
# authorization gap (no signing secret); ``error`` is a retryable live-probe
# failure.
_RAIL_HEALTH_MAP: dict[str, tuple[bool, AdapterStatus]] = {
    "ok": (True, AdapterStatus.OK),
    "webhook_only": (True, AdapterStatus.OK),
    "not_configured": (False, AdapterStatus.UNAUTHORIZED),
    "error": (False, AdapterStatus.RETRYABLE_ERROR),
}


def _elapsed_ms(start: float) -> float:
    """Wall-independent elapsed milliseconds since a ``time.perf_counter`` mark."""
    return (time.perf_counter() - start) * 1000.0


class PaymentRailIntegrationAdapter(IntegrationAdapter):
    """Adapt an observe-only :class:`PaymentRailAdapter` to the §17 contract.

    Honest by construction: capability is gated by the rail's observe-only
    :class:`ProviderManifest`. The rails are webhook-first — signature
    verification IS the connection — so the supported operations are webhook
    verification, incremental status sync (polling rails only), health, and
    normalization. Everything implying fund movement or a capability the rail
    does not have (OAuth, credential rotation, historical backfill, account
    discovery, webhook self-registration, upstream revocation, disconnect)
    inherits the base :class:`IntegrationAdapter` default: a typed
    ``not_supported`` result — never a fabricated capability, never a raise.
    """

    def __init__(
        self, *, rail: PaymentRailAdapter, manifest: ProviderManifest
    ) -> None:
        self.rail = rail
        self.manifest = manifest

    # ── Webhooks (the rails are webhook-first) ────────────────────────────

    async def verify_webhook_registration(
        self, context: AdapterContext
    ) -> AdapterResult[Any]:
        """Verify the tenant is set up to verify inbound webhooks.

        These rails do not *register* webhooks upstream
        (``registration_supported`` is False), so "registration" here means the
        inbound signing secret is configured, i.e. AETHER can HMAC-verify the
        rail's signed deliveries. Configured → ok; missing secret →
        ``unauthorized``. Never claims upstream self-registration.
        """
        if not self.manifest.webhooks.supported:
            return AdapterResult.not_supported("verify_webhook_registration")
        configured = await self.rail.is_configured(context.tenant_id)
        if configured:
            return AdapterResult.ok(
                data={
                    "webhook_verification_ready": True,
                    "provider": self.rail.provider_name,
                    "verification_scheme": self.manifest.webhooks.verification_scheme,
                    "registration_supported": self.manifest.webhooks.registration_supported,
                },
                correlation_id=context.correlation_id,
            )
        return AdapterResult(
            success=False,
            status=AdapterStatus.UNAUTHORIZED,
            error_code="webhook_signing_secret_not_configured",
            retryable=False,
            correlation_id=context.correlation_id,
            data={
                "webhook_verification_ready": False,
                "provider": self.rail.provider_name,
            },
        )

    async def verify_webhook(
        self,
        context: AdapterContext,
        *,
        payload: bytes,
        signature: Optional[str],
        timestamp: Optional[str] = None,
    ) -> AdapterResult[Any]:
        """Verify one inbound webhook signature via the rail's HMAC scheme.

        Delegates to the rail's constant-time signature verification (the rail
        reads the tenant's signing secret from the BYOK vault and never logs it).
        Valid → ok; invalid → ``unauthorized``. Additive entry beyond the ABC:
        signature verification needs the raw body/signature/timestamp, which the
        connector-shaped :class:`AdapterContext` does not carry.
        """
        if not self.manifest.webhooks.supported:
            return AdapterResult.not_supported("verify_webhook")
        payload_bytes = (
            payload if isinstance(payload, (bytes, bytearray)) else str(payload).encode("utf-8")
        )
        verified = await self.rail.verify_webhook(
            context.tenant_id, bytes(payload_bytes), signature, timestamp
        )
        if verified:
            return AdapterResult.ok(
                data={
                    "verified": True,
                    "provider": self.rail.provider_name,
                    "signature_scheme": self.rail.signature_scheme,
                },
                correlation_id=context.correlation_id,
            )
        return AdapterResult(
            success=False,
            status=AdapterStatus.UNAUTHORIZED,
            error_code="webhook_signature_invalid",
            retryable=False,
            correlation_id=context.correlation_id,
            data={"verified": False, "provider": self.rail.provider_name},
        )

    # ── Sync (polling rails only; observe-only, never backfill) ───────────

    async def run_incremental_sync(
        self,
        context: AdapterContext,
        cursor: Optional[str] = None,
        *,
        records: Optional[list[dict[str, Any]]] = None,
        **params: Any,
    ) -> AdapterResult[Any]:
        """Pull provider truth for open sessions on a polling rail.

        Only when the rail polls AND the observe-only manifest declares
        incremental sync — otherwise ``not_supported`` (webhook-only rails have
        no pull API). Delegates to the rail's ``status_sync``; ``records`` lets a
        caller/test supply already-fetched provider-shaped records so no network
        is needed. The returned events are the rail's *sanitized*
        :class:`ParsedProviderEvent` records — the wrapped data is their
        JSON projection, so no raw payment instrument can surface.
        """
        if not (self.rail.polling_supported and self.manifest.sync.incremental):
            return AdapterResult.not_supported("run_incremental_sync")

        start = time.perf_counter()
        poll_state: dict[str, Any] = {}
        if cursor is not None:
            poll_state["cursor"] = cursor
        call_params: dict[str, Any] = dict(params)
        call_params.setdefault("poll_state", poll_state)

        events = await self.rail.status_sync(
            context.tenant_id, records=records, **call_params
        )
        # ParsedProviderEvent payloads are already sanitized (built via the
        # rail's ``_make_event`` -> ``sanitize_payload``). Project to JSON-safe
        # dicts for the result envelope.
        data: list[dict[str, Any]] = [
            event.model_dump(mode="json") for event in events
        ]
        return AdapterResult.ok(
            data=data,
            latency_ms=_elapsed_ms(start),
            correlation_id=context.correlation_id,
            account={
                "cursor": cursor,
                "next_cursor": poll_state.get("next_cursor"),
                "record_count": poll_state.get("record_count", len(data)),
                "pages": poll_state.get("pages"),
                "provider_health": poll_state.get("health"),
                "event_count": len(data),
            },
        )

    async def reconcile(self, context: AdapterContext) -> AdapterResult[Any]:
        """Reconcile SDK signals against provider truth — only if the manifest
        declares reconciliation and the rail exposes a reconcile entry.

        Reconciliation for these rails is a service-layer join over an SDK view,
        a provider view, and a persisted session (see
        ``payment_rails.reconciliation.reconcile_session``); no rail adapter
        exposes a context-only reconcile and every observe-only manifest sets
        ``sync.reconciliation`` False, so this honestly returns
        ``not_supported``. The delegation hook is retained for a future
        rail-level reconcile.
        """
        if not self.manifest.sync.reconciliation:
            return AdapterResult.not_supported("reconcile")
        rail_reconcile = getattr(self.rail, "reconcile", None)
        if not callable(rail_reconcile):
            return AdapterResult.not_supported("reconcile")
        result = rail_reconcile(context.tenant_id)  # pragma: no cover - no rail declares this
        if hasattr(result, "__await__"):
            result = await result
        sanitized, _ = sanitize_payload(
            result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        )
        return AdapterResult.ok(data=sanitized, correlation_id=context.correlation_id)

    # ── Operational ──────────────────────────────────────────────────────

    async def health_check(self, context: AdapterContext) -> AdapterResult[Any]:
        """Derive health from the rail's offline-safe connection test.

        The rail never performs network IO in local mode; a webhook-only rail
        resolves to a supported ``webhook_only`` state once its signing secret is
        configured. ``not_configured`` maps to ``unauthorized`` (no secret);
        ``error`` to a retryable live-probe failure.
        """
        start = time.perf_counter()
        result = await self.rail.test_connection(context.tenant_id)
        success, status = _RAIL_HEALTH_MAP.get(
            result.status,
            (result.ok, AdapterStatus.OK if result.ok else AdapterStatus.PERMANENT_ERROR),
        )
        data = {
            "provider": result.provider,
            "status": result.status,
            "detail": result.detail,
            "checked_at": result.checked_at,
            "configured": result.status != "not_configured",
        }
        if success:
            return AdapterResult.ok(
                data=data,
                latency_ms=_elapsed_ms(start),
                correlation_id=context.correlation_id,
            )
        return AdapterResult(
            success=False,
            status=status,
            error_code=f"health:{result.status}",
            retryable=status == AdapterStatus.RETRYABLE_ERROR,
            latency_ms=_elapsed_ms(start),
            correlation_id=context.correlation_id,
            data=data,
        )

    # ── Normalization (synchronous) ──────────────────────────────────────

    def normalize(self, raw_record: Any) -> Any:
        """Map a raw provider record toward the canonical, sanitized projection.

        Delegates to the rail's sanitizing normalizer (webhook payload →
        volatile-field-free canonical funding-session projection). When the rail
        yields no funding projection (e.g. a non-funding event, or a non-dict
        input), fall back to a *sanitized* copy of the raw record — a raw payment
        instrument can never surface either way.
        """
        normalizer = getattr(self.rail, "normalize", None)
        if callable(normalizer):
            normalized = normalizer(raw_record)
            if normalized is not None:
                return normalized
        sanitized, _ = sanitize_payload(raw_record)
        return sanitized

    # NOTE: begin_authorization / complete_authorization / validate_credentials /
    # rotate_credentials / discover_accounts / select_account /
    # validate_configuration / register_webhooks / run_initial_backfill /
    # revoke_upstream_authorization / disconnect are intentionally NOT overridden.
    # They inherit the base ``IntegrationAdapter`` default — a typed
    # ``not_supported`` — because observe-only payment rails do not OAuth, do not
    # rotate provider key material, do not backfill historical funding flows, do
    # not enumerate/self-register accounts or webhooks upstream, and hold no
    # adapter-owned local enablement state to flip. Inheriting the default is the
    # honest answer; fabricating any of these would imply capability the rails
    # (and their manifests) do not have.


def payment_rail_adapter_for(
    name: str, *, manifest: Optional[ProviderManifest] = None
) -> PaymentRailIntegrationAdapter:
    """Build a :class:`PaymentRailIntegrationAdapter` for a registered rail.

    Resolves the rail from the payment-rail registry (an unknown provider is a
    :class:`NotFoundError`, never a permissive fallback) and pairs it with its
    honest, honesty-validated observe-only catalog manifest
    (``<rail>.payment_rails.observe``). ``manifest`` may be supplied to override
    the catalog default (tests / custom rails).
    """
    rail = get_adapter(name)
    resolved = (
        manifest
        or _PAYMENT_RAIL_MANIFEST_BY_FAMILY.get(rail.provider_name)
        or manifest_from_payment_rail_adapter(rail)
    )
    return PaymentRailIntegrationAdapter(rail=rail, manifest=resolved)


__all__ = [
    "PAYMENT_RAIL_ADAPTERS",
    "PaymentRailIntegrationAdapter",
    "payment_rail_adapter_for",
]
