# Derivatives Event Registry

Derivatives uses two event layers.

## Tenant/SDK-observable lifecycle events

SDK-visible lifecycle events are low-volume account and governance events such as `trading_account_connected`, `trading_account_disconnected`, `trading_account_authorized`, `trading_account_deauthorized`, `trading_agent_enabled`, `trading_agent_disabled`, `trade_intent_created`, `trade_approval_requested`, `trade_approval_resolved`, `risk_policy_updated`, and `human_trade_override_recorded`.

## Server-side operational events

High-volume venue, market, order, fill, position, funding, fee, price, account snapshot, and reconciliation events are server-side operational facts. They should flow through connector ingestion, Bronze/Silver storage, and canonical activity adapters instead of overloading browser or mobile SDK registries.
