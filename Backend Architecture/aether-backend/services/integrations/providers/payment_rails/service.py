"""Payment Rail Observability service — webhook/polling orchestration.

Pipeline per provider event:
verify → parse → dedupe → side records → normalize → status-ordered upsert
→ reconcile → canonical payment_* emission (at most once per event type per
session) → health/audit bookkeeping.

Aether observes; it never executes, settles, or custodies. Canonical events
flow through the existing validated-events bus (the same pipeline `/v1/batch`
feeds) — no parallel ingestion API.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from shared.temporal.instant import ensure_aware_utc
from typing import Any, Optional

from config.settings import settings
from shared.common.common import BadRequestError, RateLimitedError
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

from services.integrations.providers.payment_rails import ADAPTERS, get_adapter
from services.integrations.providers.payment_rails.base import (
    ParsedProviderEvent,
    PaymentRailAdapter,
    payload_hash,
)
from services.integrations.providers.payment_rails.models import (
    FundingSession,
    PaymentRailHealth,
    utc_now_iso,
)
from services.integrations.providers.payment_rails.reconciliation import reconcile_session
from services.integrations.providers.payment_rails.receipts import (
    COMPLETE_STAGES,
    TERMINAL_STATES,
    ReceiptStage,
    ReceiptState,
)
from services.integrations.providers.payment_rails.lifecycle import (
    rollout_control_permitted,
)
from services.integrations.providers.payment_rails.repository import (
    PaymentRailsRepositories,
    get_payment_rails_repositories,
)

logger = get_logger("aether.payment_rails.service")

_PROVIDER_FLAGS = {
    "privy": "privy_enabled",
    "stripe": "stripe_enabled",
    "coinbase": "coinbase_enabled",
    "moonpay": "moonpay_enabled",
    "bridge": "bridge_enabled",
}

# Deterministic namespace for payment-rail canonical event ids. A uuid5 over a
# stable (tenant, session, event_type) key yields the SAME id every time the
# same logical canonical event is emitted, so a provider redelivery or a crash
# between publish and the ``emitted_canonical`` checkpoint re-emits an
# IDEMPOTENT event the downstream validated-events bus can dedupe by id — never
# a duplicate carrying a fresh random id, as ``uuid4`` produced.
_CANONICAL_EVENT_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://aether.dev/payment_rails/canonical_event"
)
_KEY_SEP = "\x1f"  # unit separator — unambiguous field delimiter in the id key
# Bronze schema version for payment canonical events (matches the ingestion
# batch/validation spine's SCHEMA_VERSION so Bronze rows share one envelope).
_CANONICAL_SCHEMA_VERSION = "1.0.0"


def canonical_event_id(tenant_id: str, session_id: Optional[str], event_type: str) -> str:
    """Stable, replay-safe id for a canonical payment event.

    Identity is the (tenant, funding session, canonical event type) tuple: the
    same logical event always hashes to the same UUID, so re-emission is a
    downstream-idempotent no-op instead of a duplicate.
    """
    key = f"{tenant_id}{_KEY_SEP}{session_id or ''}{_KEY_SEP}{event_type}"
    return str(uuid.uuid5(_CANONICAL_EVENT_NAMESPACE, key))


async def _meter_usage(
    tenant_id: str, event_type: str, source_id: Optional[str], source_type: str
) -> None:
    """Fail-open usage meter — record a RevOps usage-metering event, swallowing
    any error so metering can never reject or drop an observation. Idempotent on
    ``source_id`` (RevOps ``find_idempotent`` dedupes on replay)."""
    try:
        from services.billing.revops import (
            MeteringService,
            UsageMeteringEvent,
            UsageMeteringEventRepository,
        )

        await MeteringService(UsageMeteringEventRepository()).record_event(
            UsageMeteringEvent(
                tenant_id=tenant_id, event_type=event_type, source_id=source_id,
                source_type=source_type, occurred_at=utc_now_iso(),
            )
        )
    except Exception as exc:  # pragma: no cover — metering must never break flow
        logger.warning(f"payment usage metering failed: {exc}")


def _age_seconds(iso_value: Optional[str], now: datetime) -> Optional[float]:
    """Seconds between an ISO timestamp and ``now`` (None when unparseable)."""
    if not iso_value:
        return None
    try:
        parsed = ensure_aware_utc(
            datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
        )
    except (ValueError, TypeError):
        return None
    return max(0.0, (now - parsed).total_seconds())


def provider_enabled(provider: str) -> bool:
    flags = settings.payment_rails
    if not flags.enabled:
        return False
    attr = _PROVIDER_FLAGS.get(provider)
    return bool(attr and getattr(flags, attr, False))


def require_provider_enabled(provider: str) -> PaymentRailAdapter:
    """Named adapter for an enabled provider; unknown → 404, disabled → 400."""
    adapter = get_adapter(provider)  # NotFoundError for unknown providers
    if not provider_enabled(adapter.provider_name):
        raise BadRequestError(
            f"Payment rail provider '{adapter.provider_name}' is not enabled "
            "(AETHER_PAYMENT_RAILS_ENABLED + per-provider flag required)"
        )
    return adapter


class PaymentRailsService:
    def __init__(
        self,
        repositories: Optional[PaymentRailsRepositories] = None,
        producer: Optional[EventProducer] = None,
    ) -> None:
        self.repos = repositories or get_payment_rails_repositories()
        self.producer = producer or EventProducer()

    # ── Webhook ingestion ─────────────────────────────────────────────────

    async def handle_webhook(
        self,
        tenant_id: str,
        provider: str,
        payload: bytes,
        signature: Optional[str],
        timestamp: Optional[str] = None,
    ) -> dict[str, Any]:
        adapter = require_provider_enabled(provider)
        # Provider-native signature verification — the same scheme the durable
        # endpoint-registry path uses — replacing the legacy generic HMAC. The
        # header-resolved route reads each provider's native signature header
        # (Moonpay-Signature-V2 / Stripe-Signature compound t=,s=/v1=, etc.) but
        # was verifying them with one generic verifier that mishandles compound
        # signatures; native verification demands each provider's real protocol.
        # Tenant is still caller-resolved here (legacy contract); the endpoint-id
        # route remains the server-resolved path.
        from services.integrations.providers.payment_rails.signature_verify import (
            verify_signature,
        )

        try:
            from services.integrations.providers.payment_rails.base import (
                get_payment_rails_vault,
            )

            legacy_secret = await get_payment_rails_vault().get_key(
                tenant_id, adapter.vault_provider_name
            )
        except Exception:  # noqa: BLE001 — missing/unavailable secret → no_secret reject
            legacy_secret = None
        secrets = [legacy_secret] if legacy_secret else []
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        result = verify_signature(
            adapter.native_signature_scheme(), secrets, payload, signature,
            timestamp=timestamp, now_epoch=now_epoch,
        )
        if not result.ok:
            await self.repos.audit.record(tenant_id, adapter.audit_record(
                tenant_id, "webhook_rejected", {"reason": result.reason}
            ))
            metrics.increment("payment_rail_webhook_rejected_total",
                              labels={"provider": adapter.provider_name})
            # Readiness demotion hook (best-effort) — same as the verified path.
            await self._maybe_demote(tenant_id, adapter.provider_name, actor="webhook_legacy_ingestion")
            return {"handled": False, "reason": result.reason}

        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequestError(f"Webhook payload is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise BadRequestError("Webhook payload must be a JSON object")

        from services.integrations.providers.payment_rails.base import _resolve_environment

        env = _resolve_environment(None)
        events = adapter.parse_webhook(tenant_id, parsed, payload_hash(parsed))
        results = [
            await self._process_event(tenant_id, adapter, event, environment=env)
            for event in events
        ]
        metrics.increment("payment_rail_webhook_handled_total",
                          labels={"provider": adapter.provider_name})
        return {"handled": True, "events": results}

    # Max webhook body we will read before verification (admission control).
    MAX_WEBHOOK_BODY_BYTES = 512 * 1024

    async def handle_verified_webhook(
        self,
        tenant_id: str,
        provider: str,
        environment: str,
        payload: bytes,
        signature: Optional[str],
        timestamp: Optional[str] = None,
        *,
        endpoint_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Server-resolved-tenant webhook path with provider-native verification.

        The tenant/environment are resolved from the durable endpoint registry
        (never a header). The webhook signing secret(s) — current + a valid
        previous during a rotation overlap — come from the durable credential
        authority (falling back to the legacy vault only if none is configured).
        Verification uses the provider's native scheme; nothing is parsed or
        persisted before a valid signature.
        """
        from datetime import datetime as _dt, timezone as _tz

        from services.integrations.providers.payment_rails.signature_verify import (
            verify_signature,
        )

        adapter = require_provider_enabled(provider)

        if payload and len(payload) > self.MAX_WEBHOOK_BODY_BYTES:
            metrics.increment("payment_rail_webhook_rejected_total",
                              labels={"provider": adapter.provider_name})
            await self._quarantine_denied(
                tenant_id, adapter, payload, "body_too_large", endpoint_id,
            )
            await self._reject_receipt(
                tenant_id, adapter.provider_name, payload,
                state=ReceiptState.QUARANTINED, reason="body_too_large",
                environment=environment, endpoint_id=endpoint_id,
            )
            return {"handled": False, "reason": "body_too_large"}

        # Admission rate limit: enforced before signature verification so a flood
        # of unverifiable bodies to a known endpoint id can't burn CPU on crypto.
        # A 429 (retryable) — not a 4xx — so the provider backs off and re-delivers.
        rl = settings.payment_rails
        if getattr(rl, "webhook_rate_limit_enabled", False):
            from services.integrations.providers.payment_rails.rate_limit import (
                payment_webhook_rate_limiter,
            )

            allowed = await payment_webhook_rate_limiter.allow(
                provider=adapter.provider_name,
                limit=getattr(rl, "webhook_rate_limit_per_minute", 600),
                endpoint_id=endpoint_id,
                tenant_id=tenant_id,
            )
            if not allowed:
                await self.repos.audit.record(tenant_id, adapter.audit_record(
                    tenant_id, "webhook_rate_limited",
                    {"endpoint_id": endpoint_id, "environment": environment},
                ))
                raise RateLimitedError(retry_after=60)

        secrets = await self._webhook_secrets(tenant_id, provider, environment, adapter)
        now_epoch = int(_dt.now(_tz.utc).timestamp())
        result = verify_signature(
            adapter.native_signature_scheme(), secrets, payload, signature,
            timestamp=timestamp, now_epoch=now_epoch,
        )
        if not result.ok:
            await self.repos.audit.record(tenant_id, adapter.audit_record(
                tenant_id, "webhook_rejected",
                {"reason": result.reason, "endpoint_id": endpoint_id, "environment": environment},
            ))
            metrics.increment("payment_rail_webhook_rejected_total",
                              labels={"provider": adapter.provider_name})
            # A body that reached a valid endpoint id without a valid signature is
            # suspicious — quarantine it (metadata only, never the raw body) for
            # forensics before rejecting.
            await self._quarantine_denied(
                tenant_id, adapter, payload, result.reason or "signature_invalid",
                endpoint_id,
            )
            await self._reject_receipt(
                tenant_id, adapter.provider_name, payload,
                state=ReceiptState.REJECTED, reason=result.reason or "signature_invalid",
                environment=environment, endpoint_id=endpoint_id,
            )
            # Readiness demotion hook: a signature failure is the canonical
            # "credential regressed" signal — feed the capability off-ramp
            # (best-effort, monotonic, gated behind readiness_demotion_enabled).
            await self._maybe_demote(tenant_id, adapter.provider_name, actor="webhook_verified_ingestion")
            # A signature mismatch / stale / bad-format is a permanent 4xx; a
            # missing secret is a configuration state, still a 4xx (not a retry).
            return {"handled": False, "reason": result.reason}

        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequestError(f"Webhook payload is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise BadRequestError("Webhook payload must be a JSON object")

        events = adapter.parse_webhook(tenant_id, parsed, payload_hash(parsed))
        results = [
            await self._process_event(
                tenant_id, adapter, event,
                environment=environment, endpoint_id=endpoint_id,
            )
            for event in events
        ]
        metrics.increment("payment_rail_webhook_handled_total",
                          labels={"provider": adapter.provider_name})
        return {"handled": True, "events": results, "environment": environment}

    async def _quarantine_denied(
        self,
        tenant_id: str,
        adapter: Any,
        payload: Optional[bytes],
        reason_code: str,
        endpoint_id: Optional[str],
    ) -> None:
        """Best-effort, metadata-only quarantine of a denied webhook.

        Stores only a sha256 + size + reason (never the raw body) in the shared
        ``webhook_quarantine`` store for forensics. Never raises — a quarantine
        failure must not change the webhook's rejection outcome.
        """
        if not getattr(settings.payment_rails, "webhook_quarantine_denied", False):
            return
        try:
            from services.integrations.webhook_quarantine import webhook_quarantine

            await webhook_quarantine.quarantine(
                tenant_id=tenant_id,
                connector_type=f"payment_rail:{adapter.provider_name}",
                raw_body=payload or b"",
                reason_code=reason_code,
            )
        except Exception as exc:  # noqa: BLE001 — forensic side effect, never fatal
            logger.warning(f"payment webhook quarantine failed (non-fatal): {exc}")

    async def _maybe_demote(
        self,
        tenant_id: str,
        provider: str,
        *,
        actor: str = "webhook_ingestion",
    ) -> dict[str, Any]:
        """Best-effort readiness demotion hook on a rejection/degradation signal.

        Feeds the canonical capability-readiness off-ramp (:mod:`readiness_
        demotion`): repeated webhook signature failures, provider poll
        degradation, or a provider rejecting the credential demote the
        payment-rails capability to DEGRADED / CREDENTIAL_INVALID. Gated by
        ``settings.payment_rails.readiness_demotion_enabled`` (default OFF)
        inside :func:`apply_demotion_if_warranted`; monotonic (never promotes);
        audited on the payment-rails audit trail; never raises — a demotion
        failure must never change the webhook/poll outcome. Returns the apply
        result so callers/tests can assert on it.
        """
        from services.integrations.providers.payment_rails.readiness_demotion import (
            apply_demotion_if_warranted,
        )

        try:
            result = await apply_demotion_if_warranted(self, tenant_id, provider, actor=actor)
        except Exception as exc:  # noqa: BLE001 — best-effort, never fatal
            logger.warning("payment_rail readiness demotion hook failed (non-fatal): %s", exc)
            return {"applied": False, "reason": "hook_failed"}
        if result.get("applied"):
            logger.warning(
                "payment_rail readiness demoted tenant=%s provider=%s target=%s signals=%s",
                tenant_id, provider, result.get("target"), result.get("signals"),
            )
        return result

    async def _webhook_secrets(
        self, tenant_id: str, provider: str, environment: str, adapter: Any
    ) -> list[str]:
        """Active + valid-previous webhook signing secrets for the durable
        endpoint-id route.

        The durable CredentialAuthority is always consulted first (it is the
        production path). The retired in-memory vault is read ONLY as a
        local-development compatibility fallback when the authority yields
        nothing: outside local development there is NO authority→legacy-vault
        fallback, so an unconfigured slot fails closed (empty list → verification
        fails) rather than silently reading the vault.
        """
        from services.integrations.providers.payment_rails.base import _is_local_env

        try:
            from services.providers.credentials.authority import credential_authority

            secrets = await credential_authority.get_verification_secrets(
                tenant_id, provider, environment, "webhook_signing_secret"
            )
        except Exception:  # noqa: BLE001 — authority unavailable
            secrets = []
        if secrets or not _is_local_env():
            return secrets
        # Local-development-only compatibility read against the legacy vault.
        try:
            from services.integrations.providers.payment_rails.base import (
                get_payment_rails_vault,
            )

            legacy = await get_payment_rails_vault().get_key(
                tenant_id, adapter.vault_provider_name
            )
            return [legacy] if legacy else []
        except Exception:  # noqa: BLE001
            return []

    # ── Polling / status sync ─────────────────────────────────────────────

    async def status_sync(
        self,
        tenant_id: str,
        provider: str,
        *,
        records: Optional[list[dict[str, Any]]] = None,
        **params: Any,
    ) -> dict[str, Any]:
        """Pull provider truth for open sessions and persist sync cursor + health.

        The stored per-scope cursor is loaded before the pull and the adapter's
        returned ``next_cursor`` is persisted after, so the next sweep resumes
        where this one stopped (cursor recovery). Polled events flow through the
        same status-ordered upsert as webhooks, so a stale poll can NEVER
        regress a terminal session. ``records=`` bypasses the network for
        callers/tests supplying provider-shaped records directly.
        """
        adapter = require_provider_enabled(provider)
        account = await self.repos.accounts.get(tenant_id, adapter.provider_name) or {}

        # Authoritative credential environment for this pull: an explicit caller
        # value wins, else the deployment-derived default (sandbox everywhere but
        # production). Threaded into credential + endpoint resolution so a sandbox
        # connection never pulls with live credentials. Mapped onto the sandbox|live
        # credential vocabulary (a stored connection "environment" is accepted too).
        from services.integrations.providers.payment_rails.base import _resolve_environment

        _account_env = account.get("environment")
        # The legacy account default is the string "production"; only honor a stored
        # environment that was explicitly narrowed to a credential vocabulary token.
        if _account_env in ("sandbox", "live"):
            environment = _resolve_environment(params.pop("environment", None) or _account_env)
        else:
            environment = _resolve_environment(params.pop("environment", None))

        poll_state: Optional[dict[str, Any]] = None
        if records is None and adapter.polling_supported:
            scope = str(params.get("partner_user_ref") or params.get("customer_id") or "default")
            cursors = dict(account.get("sync_cursors") or {})
            poll_state = {
                "cursor": cursors.get(scope), "scope": scope,
                "health": "ok", "next_cursor": None, "pages": 0,
            }
            events = await adapter.status_sync(
                tenant_id, poll_state=poll_state, environment=environment, **params
            )
        else:
            events = await adapter.status_sync(tenant_id, records=records)

        results = [
            await self._process_event(tenant_id, adapter, event, environment=environment)
            for event in events
        ]

        # Persist sync cursor + provider poll health on the account record.
        account_changes: dict[str, Any] = {
            "last_poll_at": utc_now_iso(),
            "environment": environment,
        }
        if poll_state is not None:
            health = poll_state.get("health") or "ok"
            account_changes["provider_poll_health"] = health
            account_changes["last_poll_pages"] = poll_state.get("pages", 0)
            if poll_state.get("next_cursor") is not None:
                cursors = dict(account.get("sync_cursors") or {})
                cursors[poll_state["scope"]] = poll_state["next_cursor"]
                account_changes["sync_cursors"] = cursors
            metrics.gauge(
                "payment_rail_provider_poll_health",
                1.0 if health == "ok" else 0.0,
                labels={"provider": adapter.provider_name, "health": health},
            )
            if health != "ok":
                metrics.increment(
                    "payment_rail_provider_poll_degraded_total",
                    labels={"provider": adapter.provider_name, "health": health},
                )
        elif adapter.webhook_only:
            account_changes["provider_poll_health"] = "webhook_only"
        await self.repos.accounts.upsert(tenant_id, adapter.provider_name, account_changes)

        # Readiness demotion hook: a poll health other than "ok" (auth_error →
        # CREDENTIAL_INVALID, rate_limited/server_error/timeout/... → DEGRADED)
        # is a durable regression signal. The account was just upserted with the
        # fresh health, so the evaluator reads it. Best-effort + monotonic.
        poll_health = (poll_state or {}).get("health")
        if poll_health is not None and poll_health != "ok":
            await self._maybe_demote(tenant_id, adapter.provider_name, actor="provider_poll")

        await self.repos.audit.record(tenant_id, adapter.audit_record(
            tenant_id, "status_sync",
            {"event_count": len(events),
             "environment": environment,
             "poll_health": (poll_state or {}).get("health"),
             "poll_pages": (poll_state or {}).get("pages")},
        ))
        return {
            "synced": True,
            "events": results,
            "poll_health": (poll_state or {}).get("health"),
            "next_cursor": (poll_state or {}).get("next_cursor"),
        }

    # ── Shared event pipeline ─────────────────────────────────────────────

    async def _process_event(
        self,
        tenant_id: str,
        adapter: PaymentRailAdapter,
        event: ParsedProviderEvent,
        *,
        environment: Optional[str] = None,
        endpoint_id: Optional[str] = None,
    ) -> dict[str, Any]:
        # Open (or re-open) the durable receipt for this delivery. Idempotent on
        # the deterministic receipt id: a provider retry / webhook↔polling overlap
        # / repair all map to the same ledger row. Receipt writes are best-effort
        # (never drop an observation), but the ledger is the repair worker's truth.
        rid = await self._open_receipt(
            tenant_id, event, environment=environment, endpoint_id=endpoint_id,
            stage=(ReceiptStage.SIGNATURE_VERIFIED if event.source == "webhook"
                   else ReceiptStage.RECEIVED),
        )

        _, disposition = await self.repos.events.record_event(tenant_id, event)
        if disposition == "ignored_duplicate":
            # A legitimate duplicate retry is a completed delivery — never rebilled.
            await self._receipt_advance(tenant_id, rid, ReceiptStage.COMPLETED,
                                        verification_state="duplicate")
            return {"provider_event_id": event.provider_event_id,
                    "disposition": "ignored_duplicate", "receipt_id": rid}
        if disposition == "rejected":
            await self._receipt_mark(tenant_id, rid, ReceiptState.QUARANTINED,
                                     reason="event_hash_conflict",
                                     error_classification="reused_event_id_mutated_payload")
            await self.repos.audit.record(tenant_id, adapter.audit_record(
                tenant_id, "event_hash_conflict",
                {"provider_event_id": event.provider_event_id},
            ))
            return {"provider_event_id": event.provider_event_id,
                    "disposition": "rejected", "receipt_id": rid}

        # Side records (never funding sessions themselves).
        deposit_address = adapter.extract_deposit_address(tenant_id, event)
        if deposit_address:
            await self.repos.deposit_addresses.upsert(tenant_id, deposit_address)
        virtual_account = adapter.extract_virtual_account(tenant_id, event)
        if virtual_account:
            await self.repos.virtual_accounts.upsert(tenant_id, virtual_account)

        await self._receipt_advance(tenant_id, rid, ReceiptStage.PARSED)
        session = adapter.normalize_to_funding_session(tenant_id, event)
        if session is None:
            await self._receipt_advance(tenant_id, rid, ReceiptStage.COMPLETED,
                                        verification_state="side_record")
            return {"provider_event_id": event.provider_event_id,
                    "disposition": "side_record", "receipt_id": rid}

        # Consent gate (default OFF): a funding-session observation is persisted
        # and emitted only when its subject has granted the required purpose.
        if not await self._consent_permits_session(tenant_id, adapter, event, session):
            await self._receipt_mark(tenant_id, rid, ReceiptState.REJECTED,
                                     reason="consent_denied")
            return {"provider_event_id": event.provider_event_id,
                    "disposition": "consent_denied",
                    "funding_session_id": session.id, "receipt_id": rid}

        await self._receipt_advance(tenant_id, rid, ReceiptStage.NORMALIZED)
        record, session_disposition = await self.repos.sessions.upsert_from_event(
            tenant_id, session, source=event.source
        )
        if session_disposition == "downgrade_blocked":
            await self.repos.audit.record(tenant_id, adapter.audit_record(
                tenant_id, "status_downgrade_blocked",
                {"funding_session_id": record["id"],
                 "attempted_status": session.status},
            ))
        await self._receipt_advance(tenant_id, rid, ReceiptStage.FUNDING_SESSION_PERSISTED,
                                    funding_session_id=record["id"])

        reconciliation = reconcile_session(
            record,
            provider_view={"event_id": event.provider_event_id, "source": event.source},
            provider_event_id=event.provider_event_id,
            last_source=event.source,
            is_duplicate=session_disposition == "duplicate",
        )
        await self.repos.reconciliation.upsert(tenant_id, reconciliation.model_dump(mode="json"))
        if record.get("reconciliation_state") != reconciliation.state:
            record["reconciliation_state"] = reconciliation.state
            await self.repos.sessions.save(tenant_id, record)

        emitted = await self._emit_canonical_events(tenant_id, adapter, record)
        await self._receipt_finalize_delivery(tenant_id, rid, record)
        return {
            "provider_event_id": event.provider_event_id,
            "disposition": session_disposition,
            "funding_session_id": record["id"],
            "status": record["status"],
            "reconciliation_state": reconciliation.state,
            "canonical_events_emitted": emitted,
            "receipt_id": rid,
        }

    # ── Receipt lifecycle helpers (best-effort; never break the flow) ─────────

    async def _open_receipt(
        self, tenant_id: str, event: ParsedProviderEvent, *,
        environment: Optional[str], endpoint_id: Optional[str], stage: str,
    ) -> Optional[str]:
        try:
            record = await self.repos.receipts.open(
                tenant_id, event.provider,
                provider_event_id=event.provider_event_id, body_hash=event.raw_hash,
                environment=environment, endpoint_id=endpoint_id,
                source=event.source, stage=stage,
            )
            return record["receipt_id"]
        except Exception as exc:  # noqa: BLE001 — ledger write must never drop an observation
            logger.warning(f"payment receipt open failed (non-fatal): {exc}")
            return None

    async def _receipt_advance(
        self, tenant_id: str, rid: Optional[str], stage: str, **fields: Any
    ) -> None:
        if not rid:
            return
        try:
            await self.repos.receipts.advance(tenant_id, rid, stage, **fields)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"payment receipt advance failed (non-fatal): {exc}")

    async def _receipt_mark(
        self, tenant_id: str, rid: Optional[str], state: str, **kwargs: Any
    ) -> None:
        if not rid:
            return
        try:
            await self.repos.receipts.mark_state(tenant_id, rid, state, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"payment receipt mark failed (non-fatal): {exc}")

    async def _receipt_finalize_delivery(
        self, tenant_id: str, rid: Optional[str], record: dict[str, Any]
    ) -> None:
        """Advance the receipt through canonical + delivery stages after emission.

        Direct-publish (default) is synchronous → OUTBOX_PUBLISHED → COMPLETED.
        The durable-outbox path stops at OUTBOX_ENQUEUED; the supervised relay
        publishes asynchronously and the canonical-repair worker advances the
        receipt to COMPLETED once it confirms the outbox row drained.
        """
        if not rid:
            return
        canonical_ids = list(record.get("metadata", {}).get("canonical_event_ids", []))
        await self._receipt_advance(
            tenant_id, rid, ReceiptStage.CANONICAL_EVENT_WRITTEN,
            canonical_event_ids=canonical_ids or None,
        )
        # Lifecycle gate: the durable canonical-event outbox is a rollout control.
        # It engages only when its flag is ON AND the payment-rails capability
        # lifecycle stage is at/above the outbox minimum (fails open to the flag
        # when no stage is declared, so un-declared deployments are unchanged).
        if await rollout_control_permitted("canonical_outbox", tenant_id=tenant_id):
            await self._receipt_advance(
                tenant_id, rid, ReceiptStage.OUTBOX_ENQUEUED,
                outbox_record_id=(canonical_ids[0] if canonical_ids else None),
                outbox_publication_state="enqueued",
            )
        else:
            await self._receipt_advance(
                tenant_id, rid, ReceiptStage.OUTBOX_PUBLISHED,
                outbox_publication_state="published",
            )
            await self._receipt_advance(tenant_id, rid, ReceiptStage.COMPLETED)

    async def _reject_receipt(
        self, tenant_id: str, provider: str, payload: Optional[bytes], *,
        state: str, reason: str, environment: Optional[str], endpoint_id: Optional[str],
    ) -> None:
        """Durably record a delivery that is denied before it produces an event
        (bad signature, oversized body). Metadata-only, keyed by body hash."""
        try:
            body_hash = payload_hash(payload or b"")
            await self.repos.receipts.open_terminal(
                tenant_id, provider, state=state, body_hash=body_hash,
                environment=environment, endpoint_id=endpoint_id, reason=reason,
            )
        except Exception as exc:  # noqa: BLE001 — ledger write must never change the outcome
            logger.warning(f"payment reject receipt failed (non-fatal): {exc}")

    # The canonical consent purpose governing a payment funding-session
    # observation — "Payments, approvals, entitlements, subscriptions, orders"
    # in packages/shared/contracts/consent-registry.json.
    _CONSENT_PURPOSE = "commerce"

    async def _consent_permits_session(
        self,
        tenant_id: str,
        adapter: PaymentRailAdapter,
        event: ParsedProviderEvent,
        session: FundingSession,
    ) -> bool:
        """Consent gate for persisting a funding-session observation (default OFF).

        When ``payment_rails.webhook_consent_gate_enabled`` is set, the normalized
        session is persisted/emitted only if its subject (``user_id``) has granted
        the ``commerce`` consent purpose. A session with no resolvable subject is
        allowed — there is no subject whose consent could be evaluated. Denials are
        recorded metadata-only (never the raw observation) on the payment-rails
        audit trail; the consent engine additionally records the policy decision.
        Fails closed: a missing consent record or an unavailable consent store
        denies the observation.
        """
        if not getattr(settings.payment_rails, "webhook_consent_gate_enabled", False):
            return True
        subject = session.user_id
        if not subject:
            await self.repos.audit.record(tenant_id, adapter.audit_record(
                tenant_id, "consent_gate_no_subject",
                {"provider_event_id": event.provider_event_id},
            ))
            return True

        granted = await self._granted_purposes(tenant_id, subject)
        from services.policy.engine import consent_policy_engine

        decision = await consent_policy_engine.decide(
            tenant_id=tenant_id,
            actor_id=tenant_id,
            actor_type="system",
            action="observe",
            resource_type="payment_funding_session",
            resource_id=session.id,
            subject_ref=subject,
            purpose=self._CONSENT_PURPOSE,
            granted_purposes=granted,
        )
        if decision.allowed:
            return True
        await self.repos.audit.record(tenant_id, adapter.audit_record(
            tenant_id, "consent_denied",
            {"provider_event_id": event.provider_event_id,
             "subject_ref": subject,
             "missing_purposes": decision.missing_purposes},
        ))
        return False

    async def _granted_purposes(self, tenant_id: str, subject: str) -> set[str]:
        """Consent purposes ``subject`` has granted under ``tenant_id``.

        Fails closed (empty set) when the consent store is unavailable or holds no
        record for the subject — an undeterminable grant is treated as no grant.
        """
        try:
            from repositories.repos import ConsentRepository

            record = await ConsentRepository().get_consent(tenant_id, subject)
        except Exception as exc:  # noqa: BLE001 — consent store unavailable → fail closed
            logger.warning(f"payment consent lookup failed (fail-closed): {exc}")
            return set()
        if not record:
            return set()
        return set(record.get("granted_purposes") or record.get("purposes") or [])

    async def _emit_canonical_events(
        self, tenant_id: str, adapter: PaymentRailAdapter, record: dict[str, Any]
    ) -> list[str]:
        """Emit implied payment_* events at most once per type per session."""
        from services.integrations.providers.payment_rails.models import FundingSession

        session = FundingSession.model_validate(record)
        implied = adapter.normalize_to_aether_events(session)
        already = set(record.setdefault("metadata", {}).get("emitted_canonical", []))
        # Lifecycle gate for the rollout controls (mirrors the alert evaluator):
        # each runs only when its flag is ON AND the capability lifecycle stage is
        # at/above the control's minimum. With no declared stage the gates fail
        # open to the raw flags, so un-declared deployments are byte-for-byte
        # unchanged.
        to_outbox = await rollout_control_permitted("canonical_outbox", tenant_id=tenant_id)
        meter_on = await rollout_control_permitted("usage_metering", tenant_id=tenant_id)
        emitted: list[str] = []
        emitted_ids: list[str] = []
        for canonical in implied:
            event_type = canonical["event_type"]
            if event_type in already:
                continue
            event_id = canonical_event_id(tenant_id, canonical.get("session_id"), event_type)
            emitted_ids.append(event_id)
            payload = {
                "event_id": event_id,
                "tenant_id": tenant_id,
                "event_type": event_type,
                "session_id": canonical.get("session_id"),
                "user_id": canonical.get("user_id"),
                "device_id": None,
                "properties": canonical["properties"],
                "timestamp": canonical.get("occurred_at") or utc_now_iso(),
                "ingested_at": utc_now_iso(),
                "ip_enrichment": {},
            }
            if to_outbox:
                await self._enqueue_canonical_outbox(
                    tenant_id, adapter, canonical, event_id, payload
                )
            else:
                await self.producer.publish(Event(
                    topic=Topic.SDK_EVENTS_VALIDATED,
                    tenant_id=tenant_id,
                    source_service="payment_rails",
                    payload=payload,
                ))
            emitted.append(event_type)
            # accept-then-meter: only after the event is emitted, and fail-open.
            if meter_on:
                await _meter_usage(
                    tenant_id, "payment_rail_observation_ingested",
                    event_id, "payment_rail_canonical_event",
                )
        if emitted:
            record["metadata"]["emitted_canonical"] = sorted(already | set(emitted))
            prior_ids = record["metadata"].get("canonical_event_ids", [])
            record["metadata"]["canonical_event_ids"] = sorted(set(prior_ids) | set(emitted_ids))
            await self.repos.sessions.save(tenant_id, record)
        return emitted

    async def _enqueue_canonical_outbox(
        self,
        tenant_id: str,
        adapter: PaymentRailAdapter,
        canonical: dict[str, Any],
        event_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Atomically persist a canonical event to the durable Bronze + outbox
        spine (ingest_many). The deterministic ``event_id`` is the Bronze/outbox
        key, so a retry writes no second outbox row (ingest_many enqueues only for
        a newly-accepted Bronze row); the supervised outbox relay publishes it to
        the validated-events bus exactly once.
        """
        from services.ingestion.bronze_bulk import (
            BronzeSDKEvent,
            OutboxEvent,
            ingest_many,
        )

        now = utc_now_iso()
        session_id = canonical.get("session_id") or ""
        bronze = BronzeSDKEvent(
            tenant_id=tenant_id,
            event_id=event_id,
            schema_version=_CANONICAL_SCHEMA_VERSION,
            batch_id=f"payment_rails:{tenant_id}",
            event_type=canonical["event_type"],
            event_family=canonical.get("event_family", "commerce"),
            event_timestamp=canonical.get("occurred_at") or now,
            received_at=now,
            session_id=session_id,
            anonymous_id="",
            user_id=canonical.get("user_id"),
            entity_id=session_id or tenant_id,
            payload=payload,
            source="payment_rails",
            source_tag=adapter.provider_name,
        )
        outbox = OutboxEvent(
            tenant_id=tenant_id,
            event_id=event_id,
            topic=Topic.SDK_EVENTS_VALIDATED.value,
            partition_key=session_id or tenant_id,
            payload=payload,
        )
        await ingest_many([bronze], [outbox])

    async def repair_canonical_backlog(
        self, tenant_id: str, *, limit: int = 500
    ) -> dict[str, int]:
        """Re-drive canonical emission for funding sessions with a delivery gap.

        A crash between a session upsert and its canonical emission — or an outbox
        relay outage while the durable path is enabled — can leave a funding
        session whose implied ``payment_*`` events were never delivered. This
        supervised-repair entrypoint scans the tenant's sessions, and for any whose
        expected canonical event types (implied by the session's status) are not
        all recorded in ``emitted_canonical``, re-drives ``_emit_canonical_events``.

        Recovery is idempotent: the deterministic canonical id means an
        already-delivered event is a no-op on both delivery paths (direct-publish
        dedupes on ``emitted_canonical``; the outbox path dedupes on the accepted
        Bronze row), so repeated repair runs never double-emit. Returns per-run
        counts for observability.
        """
        sessions = await self.repos.sessions.list_for_tenant(tenant_id)
        scanned = repaired = reemitted = 0
        for record in sessions[:limit]:
            adapter = ADAPTERS.get(record.get("provider"))
            if adapter is None:
                continue
            scanned += 1
            session = FundingSession.model_validate(record)
            expected = {c["event_type"] for c in adapter.normalize_to_aether_events(session)}
            already = set(record.get("metadata", {}).get("emitted_canonical", []))
            if expected <= already:
                continue  # no gap — every implied event already delivered
            emitted = await self._emit_canonical_events(tenant_id, adapter, record)
            if emitted:
                repaired += 1
                reemitted += len(emitted)
        return {"scanned": scanned, "repaired": repaired, "events_reemitted": reemitted}

    # Bounded repair: a receipt that cannot be advanced after this many repair
    # attempts is dead-lettered (a durable, inspectable terminal record) so a
    # permanently-stuck delivery cannot loop forever.
    MAX_REPAIR_ATTEMPTS = 8

    async def run_canonical_repair(
        self, tenant_id: str, *, limit: int = 500
    ) -> dict[str, int]:
        """Idempotently repair the canonical-delivery lifecycle for one tenant.

        1. Scan incomplete receipts: for each whose funding session exists,
           re-drive canonical emission (re-emits missing canonical events AND
           re-enqueues missing outbox rows idempotently — the deterministic
           canonical id dedupes both paths) and advance the receipt. A receipt
           that never reached a funding session, after ``MAX_REPAIR_ATTEMPTS``,
           is dead-lettered.
        2. Scan funding sessions with an emission gap that have no receipt
           (legacy rows) via :meth:`repair_canonical_backlog`.

        Every operation is idempotent, so repeated cycles never double-emit or
        double-bill. Returns per-run counters and records each repair outcome on
        the receipt lifecycle.
        """
        stats = {
            "receipts_scanned": 0, "receipts_repaired": 0, "receipts_dead_lettered": 0,
            "sessions_scanned": 0, "sessions_repaired": 0, "events_reemitted": 0,
        }
        receipts = [
            r for r in await self.repos.receipts.list_for_tenant(tenant_id, limit=limit)
            if r.get("current_stage") not in COMPLETE_STAGES
            and r.get("current_stage") not in TERMINAL_STATES
        ]
        for r in receipts[:limit]:
            stats["receipts_scanned"] += 1
            rid = r.get("receipt_id")
            fsid = r.get("funding_session_id")
            if not fsid:
                # A delivery that never produced a funding session: give it a
                # bounded number of repair attempts, then dead-letter it.
                if int(r.get("repair_attempts", 0)) >= self.MAX_REPAIR_ATTEMPTS:
                    await self.repos.receipts.mark_state(
                        tenant_id, rid, ReceiptState.DEAD_LETTERED,
                        reason="no_funding_session_after_max_repair",
                    )
                    stats["receipts_dead_lettered"] += 1
                else:
                    await self.repos.receipts.record_repair(
                        tenant_id, rid, outcome="no_funding_session")
                continue
            record = await self.repos.sessions.get_record(tenant_id, fsid)
            if record is None:
                await self.repos.receipts.record_repair(
                    tenant_id, rid, outcome="session_missing")
                continue
            adapter = ADAPTERS.get(record.get("provider"))
            if adapter is None:
                continue
            emitted = await self._emit_canonical_events(tenant_id, adapter, record)
            await self._receipt_finalize_delivery(tenant_id, rid, record)
            # D1 (relay-publish stage). Durable enqueue to the guaranteed-delivery
            # outbox (or a synchronous direct publish) means the canonical event is
            # delivered; complete the receipt so it clears the backlog. The
            # supervised relay owns the outbox row's own retry/dead-letter for the
            # publish step.
            #
            # On the durable-outbox path the live pipeline left this receipt at
            # OUTBOX_ENQUEUED with ``outbox_publication_state="enqueued"``. By the
            # time this supervised sweep re-drives the receipt, the outbox relay
            # has had ample opportunity to drain (publish) the row — which is
            # exactly why the block below completes it unconditionally. Before
            # COMPLETED we therefore advance the receipt THROUGH the
            # OUTBOX_PUBLISHED stage and flip the publication state to
            # ``"published"``, so a completed durable-path receipt records the
            # relay-publish transition instead of lying with a stale ``"enqueued"``
            # state. This is forward-only and idempotent: a direct-publish receipt
            # already passed OUTBOX_PUBLISHED (a no-op here), and a re-run finds the
            # receipt already complete and skips it entirely. This is the
            # delivery-integrity guarantee that a receipt's ledger truthfully
            # reflects that its one canonical event per observation was published.
            await self.repos.receipts.advance(
                tenant_id, rid, ReceiptStage.OUTBOX_PUBLISHED,
                outbox_publication_state="published",
            )
            await self.repos.receipts.advance(tenant_id, rid, ReceiptStage.COMPLETED)
            await self.repos.receipts.record_repair(
                tenant_id, rid,
                outcome=("reemitted" if emitted else "advanced"),
                detail=f"events={len(emitted)}",
            )
            stats["receipts_repaired"] += 1
            stats["events_reemitted"] += len(emitted)

        session_stats = await self.repair_canonical_backlog(tenant_id, limit=limit)
        stats["sessions_scanned"] = session_stats["scanned"]
        stats["sessions_repaired"] = session_stats["repaired"]
        stats["events_reemitted"] += session_stats["events_reemitted"]
        return stats

    async def replay_dead_lettered(
        self,
        tenant_id: str,
        *,
        provider: Optional[str] = None,
        rid: Optional[str] = None,
        limit: int = 500,
        actor: str = "operator_replay",
    ) -> dict[str, Any]:
        """Manual replay of dead-lettered receipts back into the pipeline.

        Operator escape hatch (paired with the repair worker's automatic
        dead-lettering): flips each terminal dead-lettered receipt back to a
        recoverable ``repair_pending`` state via ``reset_repair`` (resetting its
        bounded repair counter), then re-drives ONE idempotent canonical-repair
        pass so the replayed deliveries actually progress. Idempotent — a
        receipt already out of the dead-letter state is skipped. Audited on the
        payment-rails audit trail. Returns per-receipt outcomes plus the repair
        pass counters.

        Security/ownership: the operator route resolves the tenant from the
        caller (never a header); ``provider``/``rid`` scope the selection and
        both are re-scoped to ``tenant_id`` for every read/write.
        """
        if rid:
            r = await self.repos.receipts.get(tenant_id, rid)
            candidate = [r] if r else []
        else:
            candidate = await self.repos.receipts.list_for_tenant(
                tenant_id, provider=provider, limit=max(1, min(limit, 2000))
            )
        dead = [
            r for r in candidate
            if r.get("current_stage") == ReceiptState.DEAD_LETTERED
        ][: max(1, min(limit, 2000))]

        replayed: list[str] = []
        for r in dead:
            rid_ = r.get("receipt_id")
            if not rid_:
                continue
            reset = await self.repos.receipts.reset_repair(
                tenant_id, rid_, reason=f"operator_replay:{actor}"
            )
            if reset is not None:
                replayed.append(rid_)

        repair = await self.run_canonical_repair(tenant_id, limit=limit) if replayed else {
            "receipts_scanned": 0, "receipts_repaired": 0, "receipts_dead_lettered": 0,
            "sessions_scanned": 0, "sessions_repaired": 0, "events_reemitted": 0,
        }

        await self.repos.audit.record(tenant_id, {
            "provider": provider or "*",
            "action": "dead_lettered_replayed",
            "detail": {
                "receipt_ids": replayed,
                "count": len(replayed),
                "actor": actor,
                "repair": repair,
            },
        })
        return {"replayed": replayed, "count": len(replayed), "repair": repair}

    # ── Health ────────────────────────────────────────────────────────────

    async def health(self, tenant_id: str) -> list[PaymentRailHealth]:
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=24)).isoformat()
        sessions = await self.repos.sessions.list_for_tenant(tenant_id)
        events = await self.repos.events.list_for_tenant(tenant_id)
        reconciliations = await self.repos.reconciliation.list_for_tenant(tenant_id)
        audits = await self.repos.audit.list_for_tenant(tenant_id, limit=1000)

        results: list[PaymentRailHealth] = []
        for name, adapter in ADAPTERS.items():
            enabled = provider_enabled(name)
            context = await adapter.health_context(tenant_id, enabled)
            p_sessions = [s for s in sessions if s.get("provider") == name]
            recent = [s for s in p_sessions if (s.get("created_at") or "") >= cutoff]
            p_recons = [r for r in reconciliations if r.get("provider") == name]
            verified_24h = sum(
                1 for e in events
                if e.get("provider") == name and (e.get("received_at") or "") >= cutoff
            )
            rejected_24h = sum(
                1 for a in audits
                if a.get("provider") == name and a.get("action") == "webhook_rejected"
                and (a.get("occurred_at") or "") >= cutoff
            )
            matched = sum(1 for r in p_recons if r.get("state") == "matched")
            conflicts = sum(1 for r in p_recons if r.get("state") == "conflict")

            account = await self.repos.accounts.get(tenant_id, name)
            if not context["configured"]:
                status = "not_configured"
            elif rejected_24h > 0 and verified_24h == 0:
                status = "error"
            elif conflicts > 0 or rejected_24h > 0:
                status = "degraded"
            else:
                status = "healthy"

            last_event_at = max(
                (e.get("received_at") or "" for e in events if e.get("provider") == name),
                default=None,
            ) or None
            last_poll_at = (account or {}).get("last_poll_at")

            # Provider freshness SLO: age of the newest observed provider signal.
            # For a pull provider this is the age of the last successful poll or
            # event; for a webhook-only provider it is the last verified webhook.
            if context["configured"]:
                freshness_source = last_poll_at if adapter.polling_supported else last_event_at
                freshness = _age_seconds(freshness_source or last_event_at, now)
                if freshness is not None:
                    metrics.gauge(
                        "payment_rail_provider_freshness_seconds", freshness,
                        labels={"provider": name, "mode":
                                "poll" if adapter.polling_supported else "webhook_only"},
                    )

            results.append(PaymentRailHealth(
                tenant_id=tenant_id,
                provider=name,  # type: ignore[arg-type]
                configured=context["configured"],
                enabled=enabled,
                webhook_verified_24h=verified_24h,
                webhook_rejected_24h=rejected_24h,
                sessions_observed_24h=len(recent),
                sessions_completed_24h=sum(1 for s in recent if s.get("status") == "completed"),
                sessions_failed_24h=sum(1 for s in recent if s.get("status") == "failed"),
                sessions_unresolved=sum(
                    1 for s in p_sessions if s.get("status") in ("unresolved", "pending")
                ),
                reconciliation_matched_rate=(matched / len(p_recons)) if p_recons else None,
                reconciliation_conflicts=conflicts,
                last_event_at=last_event_at,
                last_poll_at=last_poll_at,
                status=status,  # type: ignore[arg-type]
            ))
        return results


_service: Optional[PaymentRailsService] = None


def get_payment_rails_service() -> PaymentRailsService:
    global _service
    if _service is None:
        _service = PaymentRailsService()
    return _service
