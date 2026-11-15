import type { BridgeResult, OrderSnapshot } from '@olympuslabs/aether-shared/commerce-bridge';
/** Project a canonical order snapshot into the canonical commerce vocabulary. */
export declare function payloadBridge(snapshot: OrderSnapshot): BridgeResult;
