import type { BridgeResult, OrderSnapshot } from '@aether/shared/commerce-bridge';
/** Project a canonical order snapshot into the canonical commerce vocabulary. */
export declare function payloadBridge(snapshot: OrderSnapshot): BridgeResult;
