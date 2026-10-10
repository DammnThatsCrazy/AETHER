// =============================================================================
// Aether SDK — ENVELOPE BRIDGE (WS2, web)
//
// TypeScript mirror of Python `envelope_bridge`
// (`shared/integration_contracts/commerce_bridge.py`). Projects a canonical
// `AetherEvent` (dotted `event_type` + `data`) onto a `BridgeResult` in the SDK
// vocabulary (BARE `sdk_event_type`).
//
// Deterministic: keyed exclusively off `event.event_type` + `event.data` —
// NEVER off `provider` (which travels through as metadata only). Unmapped
// canonical types PASS THROUGH (`sdk_event_type = event.event_type`) — the
// bridge never throws. Envelope bridging is a PROJECTION, not a confirmation:
// `confirmed=false` and `confirmation_state="not_found"` always. Confirmation
// verdicts come ONLY from `confirmInteraction`.
// =============================================================================

import {
  CANONICAL_EVENT_TO_SDK_SIGNAL,
  type AetherEvent,
  type BridgeResult,
} from '@aether/shared/commerce-bridge';

/**
 * Bridge a canonical envelope event into the commerce vocabulary.
 *
 * @param event The canonical `AetherEvent` — read via `event.event_type` +
 *   `event.data` (mirrors Python exactly).
 */
export function envelopeBridge(event: AetherEvent): BridgeResult {
  return {
    // BARE SDK signal name; unmapped canonical types pass through unchanged.
    sdk_event_type: CANONICAL_EVENT_TO_SDK_SIGNAL[event.event_type] ?? event.event_type,
    payload: { ...event.data },
    canonical_event_type: event.event_type,
    provider: event.provider ?? '',
    confirmed: false,
    confirmation_state: 'not_found',
  };
}
