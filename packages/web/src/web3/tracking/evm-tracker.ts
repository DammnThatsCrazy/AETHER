// =============================================================================
// AETHER SDK — EVM TRACKER
// Token/NFT/gas/whale tracking, transaction classification via method selectors
// =============================================================================

import type { TokenBalance, NFTAsset, GasAnalytics, WhaleAlert, DeFiCategory } from '../../types';

export interface EVMTrackerCallbacks {
  onTokenBalance: (balance: TokenBalance) => void;
  onNFTDetected: (nft: NFTAsset) => void;
  onGasAnalytics: (gas: GasAnalytics) => void;
  onWhaleAlert: (alert: WhaleAlert) => void;
  onDeFiInteraction: (data: Record<string, unknown>) => void;
}

export interface EVMTrackerConfig {
  whaleThresholdETH?: number;
  tokenRefreshIntervalMs?: number;
  enableTokenTracking?: boolean;
  enableNFTDetection?: boolean;
  enableGasAnalytics?: boolean;
  enableWhaleAlerts?: boolean;
}

// Well-known ERC-20 method selectors (first 4 bytes of keccak256)
const METHOD_SELECTORS: Record<string, { name: string; type: string; defiCategory?: DeFiCategory }> = {
  '0xa9059cbb': { name: 'transfer', type: 'transfer' },
  '0x23b872dd': { name: 'transferFrom', type: 'transfer' },
  '0x095ea7b3': { name: 'approve', type: 'approve' },
  '0x38ed1739': { name: 'swapExactTokensForTokens', type: 'swap', defiCategory: 'dex' },
  '0x7ff36ab5': { name: 'swapExactETHForTokens', type: 'swap', defiCategory: 'dex' },
  '0x18cbafe5': { name: 'swapExactTokensForETH', type: 'swap', defiCategory: 'dex' },
  '0x5c11d795': { name: 'swapExactTokensForTokensSupportingFeeOnTransferTokens', type: 'swap', defiCategory: 'dex' },
  '0x414bf389': { name: 'exactInputSingle', type: 'swap', defiCategory: 'dex' },
  '0xc04b8d59': { name: 'exactInput', type: 'swap', defiCategory: 'dex' },
  '0xe8e33700': { name: 'addLiquidity', type: 'add_liquidity', defiCategory: 'dex' },
  '0xf305d719': { name: 'addLiquidityETH', type: 'add_liquidity', defiCategory: 'dex' },
  '0xbaa2abde': { name: 'removeLiquidity', type: 'remove_liquidity', defiCategory: 'dex' },
  '0x02751cec': { name: 'removeLiquidityETH', type: 'remove_liquidity', defiCategory: 'dex' },
  '0xe8eda9df': { name: 'deposit (AAVE)', type: 'supply', defiCategory: 'lending' },
  '0x69328dec': { name: 'withdraw (AAVE)', type: 'withdraw', defiCategory: 'lending' },
  '0xa415bcad': { name: 'borrow (AAVE)', type: 'borrow', defiCategory: 'lending' },
  '0x573ade81': { name: 'repay (AAVE)', type: 'repay', defiCategory: 'lending' },
  '0xa0712d68': { name: 'mint (Compound)', type: 'supply', defiCategory: 'lending' },
  '0xdb006a75': { name: 'redeem (Compound)', type: 'withdraw', defiCategory: 'lending' },
  '0xa694fc3a': { name: 'stake', type: 'stake', defiCategory: 'staking' },
  '0x2e1a7d4d': { name: 'withdraw (unstake)', type: 'unstake', defiCategory: 'staking' },
  '0x3ccfd60b': { name: 'withdraw (claim)', type: 'claim_rewards', defiCategory: 'staking' },
  '0x1249c58b': { name: 'mint (NFT)', type: 'nft_mint' },
  '0x42842e0e': { name: 'safeTransferFrom (ERC-721)', type: 'nft_transfer' },
  '0xf242432a': { name: 'safeTransferFrom (ERC-1155)', type: 'nft_transfer' },
  '0xab834bab': { name: 'atomicMatch_ (OpenSea)', type: 'swap', defiCategory: 'nft_marketplace' },
  '0x56781388': { name: 'increasePosition (GMX)', type: 'open_position', defiCategory: 'perpetuals' },
  '0x33eeb147': { name: 'decreasePosition (GMX)', type: 'close_position', defiCategory: 'perpetuals' },
  '0xd0e30db0': { name: 'deposit (WETH wrap)', type: 'wrap' },
  '0x2e1a7d4e': { name: 'withdraw (WETH unwrap)', type: 'unwrap' },
  '0x5ae401dc': { name: 'multicall (Uniswap V3 Router)', type: 'swap', defiCategory: 'dex' },
  '0x3593564c': { name: 'execute (Universal Router)', type: 'swap', defiCategory: 'router' },
  '0x12aa3caf': { name: 'swap (1inch V5)', type: 'swap', defiCategory: 'router' },
  '0xe449022e': { name: 'uniswapV3Swap (1inch)', type: 'swap', defiCategory: 'router' },
  '0xb6f9de95': { name: 'swapExactETHForTokensSupportingFeeOnTransferTokens', type: 'swap', defiCategory: 'dex' },
  '0x56688700': { name: 'depositEther (Lido)', type: 'stake', defiCategory: 'staking' },
  '0x8fcbaf0c': { name: 'permit', type: 'approve' },
  '0x8b95dd71': { name: 'setSubnodeRecord (ENS)', type: 'governance' },
};

export class EVMTracker {
  private callbacks: EVMTrackerCallbacks;
  private config: Required<EVMTrackerConfig>;
  private tokenCache: Map<string, TokenBalance[]> = new Map();
  private refreshTimer: ReturnType<typeof setInterval> | null = null;

  constructor(callbacks: EVMTrackerCallbacks, config?: EVMTrackerConfig) {
    this.callbacks = callbacks;
    this.config = {
      whaleThresholdETH: config?.whaleThresholdETH ?? 100,
      tokenRefreshIntervalMs: config?.tokenRefreshIntervalMs ?? 60000,
      enableTokenTracking: config?.enableTokenTracking ?? true,
      enableNFTDetection: config?.enableNFTDetection ?? true,
      enableGasAnalytics: config?.enableGasAnalytics ?? true,
      enableWhaleAlerts: config?.enableWhaleAlerts ?? true,
    };
  }

  /** Classify a transaction by its input data */
  classifyTransaction(input?: string): { name: string; type: string; defiCategory?: DeFiCategory } {
    if (!input || input === '0x' || input.length < 10) {
      return { name: 'transfer', type: 'transfer' };
    }
    const selector = input.slice(0, 10).toLowerCase();
    return METHOD_SELECTORS[selector] ?? { name: 'unknown', type: 'custom' };
  }

  /** Process a confirmed transaction for analytics */
  processTransaction(tx: {
    hash: string; from: string; to: string; value: string;
    gasUsed: string; gasPrice: string; input?: string; chainId: number;
  }): void {
    // Gas analytics
    if (this.config.enableGasAnalytics) {
      const gasUsedBN = BigInt(tx.gasUsed || '0');
      const gasPriceBN = BigInt(tx.gasPrice || '0');
      const gasCostWei = gasUsedBN * gasPriceBN;
      this.callbacks.onGasAnalytics({
        gasPrice: tx.gasPrice, gasUsed: tx.gasUsed,
        gasCostNative: (Number(gasCostWei) / 1e18).toFixed(8),
        chainId: tx.chainId, vm: 'evm',
      });
    }

    // Whale detection
    if (this.config.enableWhaleAlerts) {
      const valueETH = Number(BigInt(tx.value || '0')) / 1e18;
      if (valueETH >= this.config.whaleThresholdETH) {
        this.callbacks.onWhaleAlert({
          txHash: tx.hash, value: tx.value, from: tx.from, to: tx.to,
          chainId: tx.chainId, vm: 'evm',
          threshold: String(this.config.whaleThresholdETH),
        });
      }
    }

    // DeFi classification
    const classification = this.classifyTransaction(tx.input);
    if (classification.defiCategory) {
      this.callbacks.onDeFiInteraction({
        txHash: tx.hash, protocol: classification.name,
        category: classification.defiCategory, action: classification.type,
        chainId: tx.chainId, vm: 'evm', from: tx.from, to: tx.to, value: tx.value,
      });
    }
  }

  /** Check ERC-20 token balance */
  async checkTokenBalance(
    provider: { request: (args: { method: string; params?: unknown[] }) => Promise<unknown> },
    ownerAddress: string, tokenAddress: string, chainId: number,
    tokenInfo: { symbol: string; name: string; decimals: number }
  ): Promise<TokenBalance | null> {
    if (!this.config.enableTokenTracking) return null;
    try {
      // balanceOf(address) = 0x70a08231
      const data = '0x70a08231' + ownerAddress.slice(2).padStart(64, '0');
      const result = await provider.request({
        method: 'eth_call',
        params: [{ to: tokenAddress, data }, 'latest'],
      });
      const balance = BigInt(result as string);
      const tokenBalance: TokenBalance = {
        symbol: tokenInfo.symbol, name: tokenInfo.name,
        contractAddress: tokenAddress, balance: balance.toString(),
        decimals: tokenInfo.decimals, vm: 'evm', chainId,
        standard: 'erc20',
      };
      this.callbacks.onTokenBalance(tokenBalance);
      return tokenBalance;
    } catch { return null; }
  }

  /** Check ERC-721 NFT ownership */
  async checkNFTOwnership(
    provider: { request: (args: { method: string; params?: unknown[] }) => Promise<unknown> },
    ownerAddress: string, contractAddress: string, tokenId: string, chainId: number,
    nftInfo?: { name?: string; collection?: string }
  ): Promise<NFTAsset | null> {
    if (!this.config.enableNFTDetection) return null;
    try {
      // ownerOf(uint256) = 0x6352211e
      const data = '0x6352211e' + BigInt(tokenId).toString(16).padStart(64, '0');
      const result = await provider.request({
        method: 'eth_call',
        params: [{ to: contractAddress, data }, 'latest'],
      });
      const owner = '0x' + (result as string).slice(-40);
      if (owner.toLowerCase() === ownerAddress.toLowerCase()) {
        const nft: NFTAsset = {
          contractAddress, tokenId, name: nftInfo?.name,
          collection: nftInfo?.collection, standard: 'erc721',
          vm: 'evm', chainId,
        };
        this.callbacks.onNFTDetected(nft);
        return nft;
      }
      return null;
    } catch { return null; }
  }

  destroy(): void {
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = null;
    }
    this.tokenCache.clear();
  }
}
