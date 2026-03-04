// =============================================================================
// AETHER SDK — TRON (TVM) TRACKER
// TRC-20/TRC-721, energy/bandwidth tracking, contract interactions
// =============================================================================

import type { TokenBalance, GasAnalytics, DeFiCategory } from '../../types';

export interface TronTrackerCallbacks {
  onTokenBalance: (balance: TokenBalance) => void;
  onGasAnalytics: (gas: GasAnalytics) => void;
  onDeFiInteraction: (data: Record<string, unknown>) => void;
}

const KNOWN_TRON_CONTRACTS: Record<string, { name: string; category?: DeFiCategory }> = {
  'TKzxdSv2FZKQrEqkKVgp5DcwEXBEKMg2Ax': { name: 'SunSwap V2', category: 'dex' },
  'TSSMHYeV2uE9qYH95DqyoCuNCzEL1NvU3S': { name: 'SUN.io', category: 'dex' },
  'TYsbWxNnyTgsZaTFaue9hby3KptV34DkFi': { name: 'JustLend', category: 'lending' },
  'TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8': { name: 'USDC (TRC-20)' },
  'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t': { name: 'USDT (TRC-20)' },
  'TNUC9Qb1rRpS5CbWLmNMxXBjyFoydXjWFR': { name: 'WTRX' },
};

export class TronTracker {
  private callbacks: TronTrackerCallbacks;
  private network: string = 'tron:mainnet';

  constructor(callbacks: TronTrackerCallbacks, network?: string) {
    this.callbacks = callbacks;
    if (network) this.network = network;
  }

  /** Process a TRON transaction */
  processTransaction(tx: {
    txID: string;
    contractAddress?: string;
    energyUsage?: number;
    bandwidthUsage?: number;
    netFee?: number;
    energyFee?: number;
    contractRet?: string;
  }): void {
    // Energy/Bandwidth analytics (TRON's resource model)
    this.callbacks.onGasAnalytics({
      gasCostNative: (((tx.netFee ?? 0) + (tx.energyFee ?? 0)) / 1e6).toFixed(6),
      chainId: this.network, vm: 'tvm',
      energyUsed: tx.energyUsage, bandwidthUsed: tx.bandwidthUsage,
    });

    // Protocol detection
    if (tx.contractAddress) {
      const protocol = KNOWN_TRON_CONTRACTS[tx.contractAddress];
      if (protocol?.category) {
        this.callbacks.onDeFiInteraction({
          txHash: tx.txID, protocol: protocol.name,
          category: protocol.category, vm: 'tvm', chainId: this.network,
        });
      }
    }
  }

  /** Get TRX balance */
  async getTRXBalance(address: string): Promise<TokenBalance | null> {
    try {
      const response = await fetch(`${this.getApiUrl()}/v1/accounts/${address}`);
      const data = await response.json();
      const balance: TokenBalance = {
        symbol: 'TRX', name: 'TRON', contractAddress: 'native',
        balance: String(data?.data?.[0]?.balance ?? 0), decimals: 6,
        vm: 'tvm', chainId: this.network, standard: 'native',
      };
      this.callbacks.onTokenBalance(balance);
      return balance;
    } catch { return null; }
  }

  /** Get TRC-20 token balances */
  async getTRC20Balances(address: string): Promise<TokenBalance[]> {
    try {
      const response = await fetch(`${this.getApiUrl()}/v1/accounts/${address}/tokens?limit=100`);
      const data = await response.json();
      const balances: TokenBalance[] = (data?.data ?? [])
        .filter((t: { type: string }) => t.type === 'trc20')
        .map((t: { symbol: string; name: string; balance: string; decimals: number; id: string }) => ({
          symbol: t.symbol, name: t.name, contractAddress: t.id,
          balance: t.balance, decimals: t.decimals,
          vm: 'tvm' as const, chainId: this.network, standard: 'trc20' as const,
        }));
      balances.forEach((b) => this.callbacks.onTokenBalance(b));
      return balances;
    } catch { return []; }
  }

  private getApiUrl(): string {
    const map: Record<string, string> = {
      'tron:mainnet': 'https://api.trongrid.io',
      'tron:shasta': 'https://api.shasta.trongrid.io',
      'tron:nile': 'https://nile.trongrid.io',
    };
    return map[this.network] ?? map['tron:mainnet'];
  }

  destroy(): void { /* no timers */ }
}
