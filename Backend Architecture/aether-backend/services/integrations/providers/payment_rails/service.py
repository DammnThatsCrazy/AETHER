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
    PaymentRailHealth,
    utc_now_iso,
)
from services.integrations.providers.payment_rails.reconciliation import reconcile_session
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
        verified = await adapter.verify_webhook(
            tenant_id, payload=payload, signature=signature, timestamp=timestamp
        )
        if not verified:
            await self.repos.audit.record(tenant_id, adapter.audit_record(
                tenant_id, "webhook_rejected", {"reason": "signature_verification_failed"}
            ))
            metrics.increment("payment_rail_webhook_rejected_total",
                              labels={"provider": adapter.provider_name})
            return {"handled": False, "reason": "signature_verification_failed"}

        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequestError(f"Webhook payload is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise BadRequestError("Webhook payload must be a JSON object")

        events = adapter.parse_webhook(tenant_id, parsed, payload_hash(parsed))
        results = [await self._process_event(tenant_id, adapter, event) for event in events]
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
        results = [await self._process_event(tenant_id, adapter, event) for event in events]
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

    async def _webhook_secrets(
        self, tenant_id: str, provider: str, environment: str, adapter: Any
    ) -> list[str]:
        """Active + valid-previous webhook signing secrets, credential authority
        first, then the legacy vault as a migration fallback."""
        secrets: list[str] = []
        try:
            from services.providers.credentials.authority import credential_authority

            secrets = await credential_authority.get_verification_secrets(
                tenant_id, provider, environment, "webhook_signing_secret"
            )
        except Exception:  # authority not configured for this slot yet
            secrets = []
        if not secrets:
            try:
                from services.integrations.providers.payment_rails.base import (
                    get_payment_rails_vault,
                )

                legacy = await get_payment_rails_vault().get_key(
                    tenant_id, adapter.vault_provider_name
                )
                if legacy:
                    secrets = [legacy]
            except Exception:
                secrets = []
        return secrets

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

        poll_state: Optional[dict[str, Any]] = None
        if records is None and adapter.polling_supported:
            scope = str(params.get("partner_user_ref") or params.get("customer_id") or "default")
            cursors = dict(account.get("sync_cursors") or {})
            poll_state = {
                "cursor": cursors.get(scope), "scope": scope,
                "health": "ok", "next_cursor": None, "pages": 0,
            }
            events = await adapter.status_sync(tenant_id, poll_state=poll_state, **params)
        else:
            events = await adapter.status_sync(tenant_id, records=records)

        results = [await self._process_event(tenant_id, adapter, event) for event in events]

        # Persist sync cursor + provider poll health on the account record.
        account_changes: dict[str, Any] = {"last_poll_at": utc_now_iso()}
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

        await self.repos.audit.record(tenant_id, adapter.audit_record(
            tenant_id, "status_sync",
            {"event_count": len(events),
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
        self, tenant_id: str, adapter: PaymentRailAdapter, event: ParsedProviderEvent
    ) -> dict[str, Any]:
        _, disposition = await self.repos.events.record_event(tenant_id, event)
        if disposition == "ignored_duplicate":
            return {"provider_event_id": event.provider_event_id,
                    "disposition": "ignored_duplicate"}
        if disposition == "rejected":
            await self.repos.audit.record(tenant_id, adapter.audit_record(
                tenant_id, "event_hash_conflict",
                {"provider_event_id": event.provider_event_id},
            ))
            return {"provider_event_id": event.provider_event_id, "disposition": "rejected"}

        # Side records (never funding sessions themselves).
        deposit_address = adapter.extract_deposit_address(tenant_id, event)
        if deposit_address:
            await self.repos.deposit_addresses.upsert(tenant_id, deposit_address)
        virtual_account = adapter.extract_virtual_account(tenant_id, event)
        if virtual_account:
            await self.repos.virtual_accounts.upsert(tenant_id, virtual_account)

        session = adapter.normalize_to_funding_session(tenant_id, event)
        if session is None:
            return {"provider_event_id": event.provider_event_id,
                    "disposition": "side_record"}

        record, session_disposition = await self.repos.sessions.upsert_from_event(
            tenant_id, session, source=event.source
        )
        if session_disposition == "downgrade_blocked":
            await self.repos.audit.record(tenant_id, adapter.audit_record(
                tenant_id, "status_downgrade_blocked",
                {"funding_session_id": record["id"],
                 "attempted_status": session.status},
            ))

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
        return {
            "provider_event_id": event.provider_event_id,
            "disposition": session_disposition,
            "funding_session_id": record["id"],
            "status": record["status"],
            "reconciliation_state": reconciliation.state,
            "canonical_events_emitted": emitted,
        }

    async def _emit_canonical_events(
        self, tenant_id: str, adapter: PaymentRailAdapter, record: dict[str, Any]
    ) -> list[str]:
        """Emit implied payment_* events at most once per type per session."""
        from services.integrations.providers.payment_rails.models import FundingSession

        session = FundingSession.model_validate(record)
        implied = adapter.normalize_to_aether_events(session)
        already = set(record.setdefault("metadata", {}).get("emitted_canonical", []))
        emitted: list[str] = []
        for canonical in implied:
            event_type = canonical["event_type"]
            if event_type in already:
                continue
            await self.producer.publish(Event(
                topic=Topic.SDK_EVENTS_VALIDATED,
                tenant_id=tenant_id,
                source_service="payment_rails",
                payload={
                    "event_id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "session_id": canonical.get("session_id"),
                    "user_id": canonical.get("user_id"),
                    "device_id": None,
                    "properties": canonical["properties"],
                    "timestamp": canonical.get("occurred_at") or utc_now_iso(),
                    "ingested_at": utc_now_iso(),
                    "ip_enrichment": {},
                },
            ))
            emitted.append(event_type)
        if emitted:
            record["metadata"]["emitted_canonical"] = sorted(already | set(emitted))
            await self.repos.sessions.save(tenant_id, record)
        return emitted

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
