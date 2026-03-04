// =============================================================================
// AETHER SDK — DEX TRACKER
// Uniswap, SushiSwap, PancakeSwap, Raydium, Jupiter, Orca, Cetus,
// Ref Finance, SunSwap, Curve, Balancer, Trader Joe, Camelot, Velodrome, Aerodrome
// =============================================================================

import type { VMType, DeFiPosition } from '../../types';
import { identifyProtocol } from './protocol-registry';

export interface DexTrackerCallbacks {
  onSwap: (data: Record<string, unknown>) => void;
  onLiquidityChange: (data: Record<string, unknown>) => void;
  onPoolInteraction: (data: Record<string, unknown>) => void;
}

export class DexTracker {
  private callbacks: DexTrackerCallbacks;

  constructor(callbacks: DexTrackerCallbacks) {
    this.callbacks = callbacks;
  }

  /** Detect if a transaction is a DEX swap */
  detectSwap(tx: { hash: string; to: string; chainId: number | string; vm: VMType; input?: string; value?: string }): boolean {
    const protocol = identifyProtocol(tx.chainId, tx.to);
    if (protocol?.category !== 'dex') return false;

    this.callbacks.onSwap({
      txHash: tx.hash, protocol: protocol.name, category: 'dex',
      action: 'swap', vm: tx.vm, chainId: tx.chainId,
      contractAddress: tx.to, value: tx.value,
    });
    return true;
  }

  /** Process a decoded swap event */
  processSwapEvent(data: {
    txHash: string; protocol: string; tokenIn: string; tokenOut: string;
    amountIn: string; amountOut: string; priceImpact?: number;
    poolAddress?: string; vm: VMType; chainId: number | string;
  }): void {
    this.callbacks.onSwap({
      ...data, action: 'swap', category: 'dex',
    });
  }

  /** Process liquidity provision event */
  processLiquidityEvent(data: {
    txHash: string; protocol: string; action: 'add_lp' | 'remove_lp';
    token0: string; token1: string; amount0: string; amount1: string;
    lpTokens?: string; poolAddress: string; vm: VMType; chainId: number | string;
  }): void {
    this.callbacks.onLiquidityChange({
      ...data, category: 'dex',
    });
  }

  /** Get LP positions as DeFi positions */
  getLPPosition(data: {
    protocol: string; token0: string; token1: string;
    amount0: string; amount1: string; valueUSD?: number;
    poolAddress: string; vm: VMType; chainId: number | string;
  }): DeFiPosition {
    return {
      protocol: data.protocol, category: 'dex', positionType: 'liquidity_provider',
      assets: [
        { symbol: data.token0, amount: data.amount0, side: 'supply' },
        { symbol: data.token1, amount: data.amount1, side: 'supply' },
      ],
      valueUSD: data.valueUSD, vm: data.vm, chainId: data.chainId,
    };
  }

  destroy(): void { /* no resources */ }
}
