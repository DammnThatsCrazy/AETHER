// =============================================================================
// AETHER SDK — INSURANCE TRACKER
// Nexus Mutual, InsurAce, Unslashed, Bridge Mutual
// Events: buy_cover, claim, stake_cover, expire_cover
// =============================================================================

import type { VMType, DeFiCategory } from '../../types';
import { identifyProtocol } from './protocol-registry';

export interface InsuranceTrackerCallbacks {
  onInteraction: (data: Record<string, unknown>) => void;
  onPositionChange: (data: Record<string, unknown>) => void;
}

export class InsuranceTracker {
  private callbacks: InsuranceTrackerCallbacks;
  private readonly category: DeFiCategory;

  constructor(callbacks: InsuranceTrackerCallbacks) {
    this.callbacks = callbacks;
    this.category = 'insurance' as DeFiCategory;
  }

  /** Detect if a transaction interacts with a tracked protocol */
  detect(tx: {
    hash: string; to: string; chainId: number | string;
    vm: VMType; input?: string; value?: string; from?: string;
  }): boolean {
    const protocol = identifyProtocol(tx.chainId, tx.to);
    if (!protocol || protocol.category !== this.category) return false;

    this.callbacks.onInteraction({
      txHash: tx.hash, protocol: protocol.name, category: this.category,
      vm: tx.vm, chainId: tx.chainId, contractAddress: tx.to,
      from: tx.from, value: tx.value,
    });
    return true;
  }

  /** Process a specific protocol event */
  processEvent(data: {
    txHash: string; protocol: string; action: string;
    vm: VMType; chainId: number | string;
    [key: string]: unknown;
  }): void {
    this.callbacks.onInteraction({
      ...data, category: this.category,
    });
  }

  /** Record a position change */
  recordPositionChange(data: {
    protocol: string; positionType: string; action: string;
    assets: { symbol: string; amount: string; side?: string }[];
    valueUSD?: number; vm: VMType; chainId: number | string;
    [key: string]: unknown;
  }): void {
    this.callbacks.onPositionChange({
      ...data, category: this.category,
    });
  }

  destroy(): void { /* no resources */ }
}
