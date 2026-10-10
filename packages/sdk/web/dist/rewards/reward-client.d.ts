export interface RewardConfig {
    endpoint: string;
    apiKey: string;
}
export interface RewardClientCallbacks {
    onTrack?: (event: string, properties: Record<string, unknown>) => void;
}
export declare class RewardClient {
    private endpoint;
    private apiKey;
    constructor(config: RewardConfig);
    /** Check eligibility via backend */
    checkEligibility(userId: string, rewardId: string): Promise<Record<string, unknown>>;
    /** Get claim payload from backend */
    getClaimPayload(userId: string, rewardId: string): Promise<Record<string, unknown>>;
    /** Submit a claim to backend */
    submitClaim(txHash: string, rewardId: string): Promise<Record<string, unknown>>;
    /** Clean up */
    destroy(): void;
}
/** Factory function for creating a RewardClient */
export declare function createRewardClient(config: RewardConfig): RewardClient;
