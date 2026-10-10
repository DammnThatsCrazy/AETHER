// =============================================================================
// Aether SDK — REWARD CLIENT (Tier 2 Thin Client)
// Thin claim-only stub. All eligibility checks, proof generation,
// and campaign management handled by backend.
// =============================================================================

export interface RewardConfig {
  endpoint: string;
  apiKey: string;
}

export interface RewardClientCallbacks {
  onTrack?: (event: string, properties: Record<string, unknown>) => void;
}

export class RewardClient {
  private endpoint: string;
  private apiKey: string;

  constructor(config: RewardConfig) {
    this.endpoint = config.endpoint;
    this.apiKey = config.apiKey;
  }

  /** Check eligibility via backend */
  async checkEligibility(userId: string, rewardId: string): Promise<Record<string, unknown>> {
    const response = await fetch(`${this.endpoint}/v1/rewards/${rewardId}/eligibility`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ userId }),
    });
    if (!response.ok) throw new Error(`Eligibility check failed: ${response.status}`);
    return response.json();
  }

  /** Get claim payload from backend */
  async getClaimPayload(userId: string, rewardId: string): Promise<Record<string, unknown>> {
    const response = await fetch(`${this.endpoint}/v1/rewards/${rewardId}/payload`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ userId }),
    });
    if (!response.ok) throw new Error(`Claim payload fetch failed: ${response.status}`);
    return response.json();
  }

  /** Submit a claim to backend */
  async submitClaim(txHash: string, rewardId: string): Promise<Record<string, unknown>> {
    const response = await fetch(`${this.endpoint}/v1/rewards/${rewardId}/claim`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ txHash }),
    });
    if (!response.ok) throw new Error(`Claim submission failed: ${response.status}`);
    return response.json();
  }

  /** Clean up */
  destroy(): void {
    // No resources to clean up in thin client
  }
}

/** Factory function for creating a RewardClient */
export function createRewardClient(config: RewardConfig): RewardClient {
  return new RewardClient(config);
}
