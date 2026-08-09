// =============================================================================
// Aether SDK — PAYLOAD BRIDGE (WS2, web)
//
// TypeScript mirror of Python `payload_bridge`
// (`shared/integration_contracts/commerce_bridge.py`). Projects a canonical
// `OrderSnapshot` onto a `BridgeResult`.
//
// The payload is the canonical JSON-safe `OrderSnapshot`:
// `{order_id, status, currency, total: {amount: "<exact decimal string>",
// currency}, created_at, updated_at, account_id}` — `total.amount` is an exact
// decimal STRING (never a float). The bridge never calls `decimalToCents` on
// the canonical wire shape, so it cannot crash on it.
//
// A projection, not a confirmation: `confirmed=false` and
// `confirmation_state="not_found"` always; the snapshot carries no provider
// lineage, so `provider` is empty metadata.
// =============================================================================

import type { BridgeResult, OrderSnapshot } from '@aether/shared/commerce-bridge';

/** Project a canonical order snapshot into the canonical commerce vocabulary. */
export function payloadBridge(snapshot: OrderSnapshot): BridgeResult {
  return {
    sdk_event_type: 'order_confirmed',
    payload: {
      order_id: snapshot.order_id,
      status: snapshot.status,
      currency: snapshot.currency,
      total: {
        amount: snapshot.total.amount,
        currency: snapshot.total.currency,
      },
      created_at: snapshot.created_at,
      updated_at: snapshot.updated_at,
      account_id: snapshot.account_id,
    },
    canonical_event_type: 'commerce.order.confirmed',
    provider: '',
    confirmed: false,
    confirmation_state: 'not_found',
  };
}
