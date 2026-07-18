"""Coinbase onramp/offramp adapter — webhooks + transaction-status polling.

Normalizes Coinbase onramp/offramp transactions keyed by ``partner_user_ref``:
transaction id, partner user ref, wallet address, purchase/cashout assets and
networks, totals/fees where safely reported, and the on-chain tx hash.
Status polling (``status_sync``) filters provider transaction records by
``partner_user_ref``. In-progress/started map to pending/submitted, success to
completed, failed to failed.
"""

from __future__ import annotations

from typing import Any, Optional

from services.integrations.providers.payment_rails.base import (
    ConnectionTestResult,
    ParsedProviderEvent,
    PaymentRailAdapter,
    ProviderPollError,
    _extract_secret,
    sum_amounts,
)
from services.integrations.providers.payment_rails.models import FundingSession


def _money(value: Any) -> Optional[str]:
    """Extract a safe amount string from either "1.23" or {value, currency}."""
    if isinstance(value, dict):
        value = value.get("value")
    return str(value) if value not in (None, "") else None


def _money_currency(value: Any) -> Optional[str]:
    if isinstance(value, dict) and value.get("currency"):
        return str(value["currency"]).upper()
    return None


def _str(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


class CoinbaseAdapter(PaymentRailAdapter):
    provider_name = "coinbase"
    display_name = "Coinbase onramp/offramp"
    vault_provider_name = "payment_coinbase"
    flows = ("fiat_onramp", "offramp")
    webhook_supported = True
    polling_supported = True
    default_rail = "coinbase"
    signature_scheme = "body_hex"  # HMAC-SHA256 over the raw body

    # Pull path — CDP Onramp transaction-status API, cursor-paginated.
    poll_base_url = "https://api.developer.coinbase.com"
    cert_supported_operations = (
        "webhook_ingest", "normalize", "reconcile", "status_poll", "backfill",
    )
    cert_required_credentials = ("webhook_signing_secret", "onramp_api_key")
    cert_required_endpoints = ("/onramp/v1/buy/user/{partner_user_ref}/transactions",)
    cert_pagination_model = "cursor"

    STATUS_MAP: dict[str, str] = {
        "onramp_transaction_status_created": "initiated",
        "onramp_transaction_status_started": "submitted",
        "onramp_transaction_status_in_progress": "pending",
        "onramp_transaction_status_pending": "pending",
        "onramp_transaction_status_success": "completed",
        "onramp_transaction_status_failed": "failed",
        "offramp_transaction_status_created": "initiated",
        "offramp_transaction_status_started": "submitted",
        "offramp_transaction_status_in_progress": "pending",
        "offramp_transaction_status_pending": "pending",
        "offramp_transaction_status_success": "completed",
        "offramp_transaction_status_failed": "failed",
        "created": "initiated",
        "started": "submitted",
        "in_progress": "pending",
        "pending": "pending",
        "success": "completed",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "refunded": "refunded",
    }

    def parse_webhook(
        self, tenant_id: str, payload: dict[str, Any], raw_hash: str
    ) -> list[ParsedProviderEvent]:
        event_type = str(
            payload.get("event_type") or payload.get("eventType") or "onramp.transaction.updated"
        )
        tx = payload.get("transaction") or payload.get("data") or {}
        event_id = (
            payload.get("event_id") or payload.get("eventId")
            or f"{tx.get('transaction_id')}:{tx.get('status')}"
        )
        return [self._make_event(
            provider_event_id=str(event_id),
            event_type=event_type,
            payload=payload,
            raw_hash=raw_hash,
            occurred_at=payload.get("created_at") or tx.get("updated_at"),
        )]

    def _parse_poll_records(
        self, tenant_id: str, records: list[dict[str, Any]], **params: Any
    ) -> list[ParsedProviderEvent]:
        """Normalize transaction-status polling records keyed by partnerUserRef."""
        partner_user_ref = params.get("partner_user_ref") or params.get("partnerUserRef")
        events: list[ParsedProviderEvent] = []
        for tx in records:
            ref = tx.get("partner_user_ref") or tx.get("partnerUserRef")
            if partner_user_ref and str(ref) != str(partner_user_ref):
                continue
            direction = "offramp" if "offramp" in str(tx.get("status", "")).lower() or \
                str(tx.get("type", "")).lower() == "offramp" else "onramp"
            events.append(self._make_event(
                provider_event_id=f"poll:{tx.get('transaction_id')}:{str(tx.get('status')).lower()}",
                event_type=f"{direction}.transaction.polled",
                payload={"transaction": tx},
                occurred_at=tx.get("updated_at") or tx.get("created_at"),
                source="polling",
            ))
        return events

    # ── Pull path: authenticated request construction + pagination ────────

    def build_request(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Construct the authenticated CDP Onramp transaction-status request.

        Bearer auth from the tenant BYOK secret; keyed by ``partner_user_ref``;
        cursor via ``page_key``. ``tenant_scope`` proves tenant-scoped isolation
        (never sent to the provider — used by internal request tracing only).
        """
        secret = _extract_secret(ctx.get("credential"))
        base = str(ctx.get("base_url") or self.poll_base_url).rstrip("/")
        ref = ctx.get("partner_user_ref") or ctx.get("partnerUserRef")
        path = (
            f"/onramp/v1/buy/user/{ref}/transactions" if ref
            else "/onramp/v1/buy/transactions"
        )
        params: dict[str, Any] = {"page_size": ctx.get("page_size", self.poll_page_size)}
        cursor = ctx.get("cursor")
        if cursor:
            params["page_key"] = cursor
        headers = {"Accept": "application/json"}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        return {
            "method": "GET",
            "url": f"{base}{path}",
            "headers": headers,
            "params": params,
            "tenant_scope": ctx.get("tenant_id", ""),
            "timeout": self._http_timeout,
        }

    async def _fetch_poll_records(
        self, tenant_id: str, **params: Any
    ) -> list[dict[str, Any]]:
        """Bounded, cursor-paginated pull of onramp/offramp transaction status.

        The ``page_key`` cursor is an ephemeral within-query token, so no resume
        cursor is persisted — each sweep re-scans (transaction volume per user is
        low) and the event dedupe absorbs overlap. Never raises: a classified
        failure degrades provider health and returns what was gathered.
        """
        poll_state = params.get("poll_state")
        secret = await self._require_secret(tenant_id)
        if not secret:
            self._mark_health(poll_state, "not_configured")
            return []
        base = await self._resolve_base_url(tenant_id)
        ref = params.get("partner_user_ref") or params.get("partnerUserRef")
        page_size = params.get("page_size", self.poll_page_size)

        records: list[dict[str, Any]] = []
        cursor = (poll_state or {}).get("cursor")
        pages = 0
        async with self._open_http_client() as client:
            try:
                while pages < self.poll_max_pages:
                    request = self.build_request({
                        "tenant_id": tenant_id, "credential": secret, "base_url": base,
                        "cursor": cursor, "partner_user_ref": ref, "page_size": page_size,
                    })
                    body = await self._request_json(client, request, poll_state=poll_state)
                    page = (
                        list(body.get("transactions") or body.get("data") or [])
                        if isinstance(body, dict) else (list(body) if isinstance(body, list) else [])
                    )
                    records.extend(page)
                    pages += 1
                    cursor = (
                        body.get("next_page_key") or body.get("nextPageKey")
                        or body.get("page_key") or body.get("pageKey")
                    ) if isinstance(body, dict) else None
                    if not cursor or not page:
                        break
            except ProviderPollError as exc:
                self._degraded(poll_state, exc)
        self._finish_poll(poll_state, next_cursor=None, pages=pages, records=records)
        return records

    async def _live_connection_test(self, tenant_id: str) -> ConnectionTestResult:
        """Authenticated health ping: a bounded transaction-status GET."""
        secret = await self._require_secret(tenant_id)
        if not secret:
            return ConnectionTestResult(
                provider=self.provider_name, ok=False, status="not_configured",
                detail="missing credential (configure the key vault)",
            )
        base = await self._resolve_base_url(tenant_id)
        request = self.build_request({
            "tenant_id": tenant_id, "credential": secret, "base_url": base, "page_size": 1,
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
            detail="authenticated transaction-status ping ok",
        )

    def normalize_to_funding_session(
        self, tenant_id: str, event: ParsedProviderEvent
    ) -> Optional[FundingSession]:
        tx = event.payload.get("transaction") or event.payload.get("data") or {}
        tx_id = tx.get("transaction_id") or tx.get("id")
        if not tx_id:
            return None
        provider_status = str(tx.get("status") or "")
        is_offramp = (
            str(tx.get("type") or "").lower() == "offramp"
            or "offramp" in provider_status.lower()
            or "offramp" in event.event_type.lower()
        )
        flow_type = "offramp" if is_offramp else "fiat_onramp"

        purchase_amount = tx.get("purchase_amount") if not is_offramp else tx.get("sell_amount")
        payment_total = tx.get("payment_total") if not is_offramp else tx.get("cashout_total")
        asset = tx.get("purchase_currency") if not is_offramp else tx.get("sell_currency")
        network = tx.get("purchase_network") if not is_offramp else tx.get("sell_network")
        fee_amount = sum_amounts(_money(tx.get("coinbase_fee")), _money(tx.get("network_fee")))

        if is_offramp:
            source_asset = _upper(asset)
            source_chain = _str(network)
            source_amount = _money(purchase_amount)
            destination_asset = None
            destination_chain = None
            destination_amount = _money(payment_total)
        else:
            source_asset = None
            source_chain = None
            source_amount = _money(payment_total)
            destination_asset = _upper(asset)
            destination_chain = _str(network)
            destination_amount = _money(purchase_amount)

        return FundingSession(
            tenant_id=tenant_id,
            provider="coinbase",
            flow_type=flow_type,  # type: ignore[arg-type]
            rail="coinbase",
            status=self.map_status(provider_status),  # type: ignore[arg-type]
            provider_status=provider_status or None,
            status_reason=tx.get("failure_reason"),
            actor_kind="human",
            user_id=_str(tx.get("partner_user_ref") or tx.get("partnerUserRef")),
            source_asset=source_asset,
            source_chain=source_chain,
            source_amount=source_amount,
            fiat_currency=_money_currency(payment_total) or _upper(tx.get("payment_currency")),
            destination_asset=destination_asset,
            destination_chain=destination_chain,
            destination_amount=destination_amount,
            destination_address=tx.get("wallet_address"),
            fee_amount=fee_amount,
            fee_currency=_money_currency(tx.get("coinbase_fee")),
            provider_transaction_id=str(tx_id),
            provider_customer_ref=_str(tx.get("partner_user_ref") or tx.get("partnerUserRef")),
            tx_hash=tx.get("tx_hash") or tx.get("transaction_hash"),
            idempotency_key=f"coinbase:{tx_id}",
            occurred_at=event.occurred_at,
        )


def _upper(value: Any) -> Optional[str]:
    return str(value).upper() if value not in (None, "") else None
