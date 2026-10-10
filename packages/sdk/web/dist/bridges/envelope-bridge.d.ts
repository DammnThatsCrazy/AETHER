import { type AetherEvent, type BridgeResult } from '@aether/shared/commerce-bridge';
/**
 * Bridge a canonical envelope event into the commerce vocabulary.
 *
 * @param event The canonical `AetherEvent` — read via `event.event_type` +
 *   `event.data` (mirrors Python exactly).
 */
export declare function envelopeBridge(event: AetherEvent): BridgeResult;
