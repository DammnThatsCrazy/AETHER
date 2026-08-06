"""MoonPay payment rail adapter — buy (fiat→crypto) and sell (crypto→fiat)
webhook observability with optional status lookup.

Duplicate and out-of-order webhook deliveries are absorbed by the provider
event dedupe (exact duplicates → ignored_duplicate) and the funding-session
status ordering (final states never regress). AML / fraud / minimum-amount
rejections surface as canonical ``failed`` with the provider's reason kept
in ``status_reason`` metadata — never the underlying KYC content.

Observation-only: MoonPay executes the flows; Aether records them.
"""

from __future__ import annotations

from typing import Any, Optional

from services.integrations.providers.payment_rails.base import (
    ConnectionTestResult,
    ParsedProviderEvent,
    PaymentRailAdapter,
    ProviderPollError,
    _extract_secret,
)
from services.integrations.providers.payment_rails.models import FundingSession

_REJECTION_REASONS = (
    "aml",
    "fraud",
    "compliance",
    "minimum",
    "min_amount",
    "sanction",
    "risk",
)


class MoonPayAdapter(PaymentRailAdapter):
    provider_name = "moonpay"
    display_name = "MoonPay"
    vault_provider_name = "payment_moonpay"
    flows = ("fiat_onramp", "offramp")
    webhook_supported = True
    polling_supported = True
    default_rail = "moonpay"
    signature_scheme = "timestamped_hex"

    # Pull path — MoonPay transactions API, time-window paginated by updatedAt.
    poll_base_url = "https://api.moonpay.com"
    cert_supported_operations = (
        "webhook_ingest", "normalize", "reconcile", "status_poll", "backfill",
    )
    cert_required_credentials = ("webhook_signing_secret", "server_api_key")
    cert_required_endpoints = ("/v3/transactions",)
    cert_pagination_model = "time_window"

    STATUS_MAP: dict[str, str] = {
        "waitingpayment": "initiated",
        "waiting_payment": "initiated",
        "pending": "pending",
        "waitingauthorization": "pending",
        "waiting_authorization": "pending",
        "waitingcapture": "pending",
        "processing": "pending",
        "completed": "completed",
        "finished": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "refunded": "refunded",
        "expired": "cancelled",
    }

    def parse_webhook(
        self, tenant_id: str, payload: dict[str, Any], raw_hash: str
    ) -> list[ParsedProviderEvent]:
        event_type = str(payload.get("type") or "transaction_updated")
        data = payload.get("data") or {}
        tx_id = data.get("id") or payload.get("externalTransactionId") or "unknown"
        # Status participates in the event id so a genuine status progression is
        # a new provider event while a redelivery of the same status dedupes.
        event_id = f"{tx_id}:{data.get('status')}"
        return [self._make_event(
            provider_event_id=event_id,
            event_type=event_type,
            payload=payload,
            raw_hash=raw_hash,
            occurred_at=data.get("updatedAt") or data.get("createdAt"),
        )]

    def normalize_to_funding_session(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> Optional[FundingSession]:
        data = event.payload.get("data") or {}
        tx_id = data.get("id")
        if not tx_id:
            return None

        is_sell = "sell" in event.event_type.lower() or bool(data.get("isSell"))
        flow_type = "offramp" if is_sell else "fiat_onramp"

        provider_status = str(data.get("status") or "")
        status = self.map_status(provider_status)
        status_reason = _failure_reason(data)
        if status_reason and status not in ("failed", "cancelled", "refunded"):
            # AML/fraud/min-amount rejections arrive as reasons on otherwise
            # ambiguous statuses — a rejection reason is authoritative.
            if any(marker in status_reason.lower() for marker in _REJECTION_REASONS):
                status = "failed"

        base_currency = _code(data.get("baseCurrency")) or _upper(data.get("baseCurrencyCode"))
        quote_currency = _code(data.get("currency")) or _upper(data.get("currencyCode"))
        fees = _sum_fee(data)

        if is_sell:
            source_asset, source_amount = quote_currency, _amount(data.get("quoteCurrencyAmount"))
            fiat_currency = base_currency
            destination_asset = base_currency
            destination_amount = _amount(data.get("baseCurrencyAmount"))
        else:
            source_asset, source_amount = base_currency, _amount(data.get("baseCurrencyAmount"))
            fiat_currency = base_currency
            destination_asset = quote_currency
            destination_amount = _amount(data.get("quoteCurrencyAmount"))

        agent_id = data.get("agentId") or data.get("agent_id")
        return FundingSession(
            tenant_id=tenant_id,
            provider="moonpay",
            flow_type=flow_type,  # type: ignore[arg-type]
            rail="moonpay",
            status=status,  # type: ignore[arg-type]
            provider_status=provider_status or None,
            status_reason=status_reason,
            actor_kind="agent" if agent_id else "human",  # type: ignore[arg-type]
            user_id=data.get("externalCustomerId") or data.get("customerId"),
            agent_id=agent_id,
            session_id=data.get("externalTransactionId"),
            journey_id=data.get("journeyId") or data.get("journey_id"),
            campaign_id=data.get("campaignId") or data.get("campaign_id"),
            source_asset=source_asset,
            source_amount=source_amount,
            fiat_currency=fiat_currency,
            destination_asset=destination_asset,
            destination_amount=destination_amount,
            destination_address=data.get("walletAddress"),
            fee_amount=fees,
            fee_currency=base_currency,
            provider_session_id=str(tx_id),
            provider_transaction_id=data.get("cryptoTransactionId") or str(tx_id),
            provider_customer_ref=data.get("customerId"),
            tx_hash=data.get("cryptoTransactionId") or data.get("payoutTransactionHash"),
            idempotency_key=f"moonpay:{tx_id}",
            occurred_at=event.occurred_at,
            metadata={"is_sell": is_sell} if is_sell else {},
        )

    def _parse_poll_records(
        self, tenant_id: str, records: list[dict[str, Any]], **params: Any
    ) -> list[ParsedProviderEvent]:
        events: list[ParsedProviderEvent] = []
        for record in records:
            tx_id = record.get("id")
            if not tx_id:
                continue
            events.append(self._make_event(
                provider_event_id=f"{tx_id}:{record.get('status')}",
                event_type="transaction_polled",
                payload={"data": record},
                occurred_at=record.get("updatedAt"),
                source="polling",
            ))
        return events

    # ── Pull path: authenticated request construction + time-window pull ──

    def build_request(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Construct the authenticated MoonPay transactions request.

        Api-Key auth from the tenant BYOK secret; ``startDate`` is the
        time-window cursor (last observed ``updatedAt``); optional
        ``externalCustomerId`` scoping. ``tenant_scope`` proves isolation.
        """
        secret = _extract_secret(ctx.get("credential"))
        base = str(ctx.get("base_url") or self.poll_base_url).rstrip("/")
        params: dict[str, Any] = {"limit": ctx.get("limit", self.poll_page_size)}
        start_date = ctx.get("cursor") or ctx.get("start_date")
        if start_date:
            params["startDate"] = start_date
        if ctx.get("end_date"):
            params["endDate"] = ctx["end_date"]
        if ctx.get("external_customer_id"):
            params["externalCustomerId"] = ctx["external_customer_id"]
        headers = {"Accept": "application/json"}
        if secret:
            headers["Authorization"] = f"Api-Key {secret}"
        return {
            "method": "GET",
            "url": f"{base}/v3/transactions",
            "headers": headers,
            "params": params,
            "tenant_scope": ctx.get("tenant_id", ""),
            "timeout": self._http_timeout,
        }

    async def _fetch_poll_records(
        self, tenant_id: str, **params: Any
    ) -> list[dict[str, Any]]:
        """Bounded, time-window pull of MoonPay transactions.

        The persisted cursor is the newest ``updatedAt`` observed (the next
        ``startDate`` watermark), so the next sweep only re-reads from that
        point. Never raises: a classified failure degrades provider health.
        """
        poll_state = params.get("poll_state")
        environment = params.get("environment")
        secret = await self._require_secret(tenant_id, environment)
        if not secret:
            self._mark_health(poll_state, "not_configured")
            return []
        base = await self._resolve_base_url(tenant_id, environment)
        limit = int(params.get("limit", self.poll_page_size))

        records: list[dict[str, Any]] = []
        start_date = (poll_state or {}).get("cursor")
        watermark = start_date or ""
        pages = 0
        async with self._open_http_client() as client:
            try:
                while pages < self.poll_max_pages:
                    request = self.build_request({
                        "tenant_id": tenant_id, "credential": secret, "base_url": base,
                        "cursor": start_date, "end_date": params.get("end_date"),
                        "external_customer_id": params.get("external_customer_id"),
                        "limit": limit,
                    })
                    body = await self._request_json(client, request, poll_state=poll_state)
                    page = (
                        list(body) if isinstance(body, list)
                        else list(body.get("data") or body.get("transactions") or [])
                        if isinstance(body, dict) else []
                    )
                    records.extend(page)
                    pages += 1
                    newest = max(
                        (str(r.get("updatedAt") or r.get("createdAt") or "") for r in page),
                        default="",
                    )
                    if newest > watermark:
                        watermark = newest
                    if not page or len(page) < limit or not newest or newest == start_date:
                        break
                    start_date = newest
            except ProviderPollError as exc:
                self._degraded(poll_state, exc)
        self._finish_poll(
            poll_state, next_cursor=(watermark or None), pages=pages, records=records,
        )
        return records

    async def _live_connection_test(
        self, tenant_id: str, environment: Optional[str] = None
    ) -> ConnectionTestResult:
        """Authenticated health ping: a bounded transactions GET (limit=1)."""
        secret = await self._require_secret(tenant_id, environment)
        if not secret:
            return ConnectionTestResult(
                provider=self.provider_name, ok=False, status="not_configured",
                detail="missing credential (provision the required slots)",
            )
        base = await self._resolve_base_url(tenant_id, environment)
        request = self.build_request({
            "tenant_id": tenant_id, "credential": secret, "base_url": base, "limit": 1,
        })
        try:
            async with self._open_http_client() as client:
                await self._request_json(client, request)
        except ProviderPollError as exc:
            return ConnectionTestResult(
                provider=self.provider_name, ok=False, status="error",
                detail=f"health ping failed ({exc.classification})",
            )
        return ConnectionTestResult(
            provider=self.provider_name, ok=True, status="ok",
            detail="authenticated transactions ping ok",
        )


def _amount(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


def _upper(value: Any) -> Optional[str]:
    return str(value).upper() if value not in (None, "") else None


def _code(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        return _upper(value.get("code"))
    return None


def _failure_reason(data: dict[str, Any]) -> Optional[str]:
    reason = data.get("failureReason") or data.get("failure_reason") or data.get("statusReason")
    return str(reason) if reason not in (None, "") else None


def _sum_fee(data: dict[str, Any]) -> Optional[str]:
    total = 0.0
    seen = False
    for key in ("feeAmount", "extraFeeAmount", "networkFeeAmount"):
        value = data.get(key)
        if value in (None, ""):
            continue
        try:
            total += float(value)
            seen = True
        except (TypeError, ValueError):
            continue
    return f"{total:.8f}".rstrip("0").rstrip(".") if seen else None
