// =============================================================================
// AETHER SDK — EVM TRACKER (Tier 2 Thin Client)
// Keeps METHOD_SELECTORS for basic tx naming. Ships raw data to backend.
// No gas analytics, no whale detection, no DeFi classification.
// =============================================================================

import type { DeFiCategory } from '../../types';
import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';

// Well-known ERC-20 method selectors (first 4 bytes of keccak256)
const METHOD_SELECTORS: Record<string, { name: string; type: string }> = {
  '0xa9059cbb': { name: 'transfer', type: 'transfer' },
  '0x23b872dd': { name: 'transferFrom', type: 'transfer' },
  '0x095ea7b3': { name: 'approve', type: 'approve' },
  '0x38ed1739': { name: 'swapExactTokensForTokens', type: 'swap' },
  '0x7ff36ab5': { name: 'swapExactETHForTokens', type: 'swap' },
  '0x18cbafe5': { name: 'swapExactTokensForETH', type: 'swap' },
  '0x414bf389': { name: 'exactInputSingle', type: 'swap' },
  '0xc04b8d59': { name: 'exactInput', type: 'swap' },
  '0xe8e33700': { name: 'addLiquidity', type: 'add_liquidity' },
  '0xf305d719': { name: 'addLiquidityETH', type: 'add_liquidity' },
  '0xa694fc3a': { name: 'stake', type: 'stake' },
  '0x2e1a7d4d': { name: 'withdraw', type: 'unstake' },
  '0x1249c58b': { name: 'mint', type: 'nft_mint' },
  '0x42842e0e': { name: 'safeTransferFrom', type: 'nft_transfer' },
  '0x5ae401dc': { name: 'multicall', type: 'swap' },
  '0x3593564c': { name: 'execute', type: 'swap' },
};

export class EVMTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) {
    super(callbacks);
  }

  /** Classify a transaction by its input data (basic naming only) */
  classifyTransaction(input?: string): { name: string; type: string } {
    if (!input || input === '0x' || input.length < 10) {
      return { name: 'transfer', type: 'transfer' };
    }
    const selector = input.slice(0, 10).toLowerCase();
    return METHOD_SELECTORS[selector] ?? { name: 'unknown', type: 'custom' };
  }

  /** Process a transaction — ship raw data to backend */
  processTransaction(tx: {
    hash: string; from: string; to: string; value: string;
    gasUsed?: string; gasPrice?: string; input?: string; chainId: number;
  }): void {
    const classification = this.classifyTransaction(tx.input);
    this.callbacks.onTransaction(tx.hash, {
      ...tx,
      methodName: classification.name,
      txType: classification.type,
      vm: 'evm',
    });
  }

  destroy(): void {
    super.destroy();
  }
}
