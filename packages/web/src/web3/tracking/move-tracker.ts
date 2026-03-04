// =============================================================================
// AETHER SDK — MOVE VM (SUI) TRACKER
// Object/coin tracking, Move call detection, gas analytics
// =============================================================================

import type { TokenBalance, GasAnalytics, DeFiCategory } from '../../types';

export interface MoveTrackerCallbacks {
  onTokenBalance: (balance: TokenBalance) => void;
  onGasAnalytics: (gas: GasAnalytics) => void;
  onDeFiInteraction: (data: Record<string, unknown>) => void;
  onMoveCall: (data: Record<string, unknown>) => void;
}

const KNOWN_SUI_PROTOCOLS: Record<string, { name: string; category?: DeFiCategory }> = {
  '0xdee9': { name: 'DeepBook', category: 'dex' },
  '0xa0eba10b173538c8fecca1dff298e488402cc9ff374f8a12ca7758eebe5b0521': { name: 'Cetus', category: 'dex' },
  '0x2': { name: 'SUI Framework' },
  '0x3': { name: 'SUI System', category: 'staking' },
  '0x5306f64e312b581766351c07af79c72fcb1cd25147157fdc2f8ad76de9a3fb6a': { name: 'Scallop', category: 'lending' },
  '0xefe8b36d5b2e43728cc323298626b83177803521d195cfb11e15b910e892fddf': { name: 'Turbos', category: 'dex' },
};

export class MoveTracker {
  private callbacks: MoveTrackerCallbacks;
  private network: string = 'sui:mainnet';

  constructor(callbacks: MoveTrackerCallbacks, network?: string) {
    this.callbacks = callbacks;
    if (network) this.network = network;
  }

  /** Process a SUI transaction */
  processTransaction(tx: {
    digest: string;
    effects?: { gasUsed?: { computationCost: string; storageCost: string; storageRebate: string }; status?: { status: string } };
    transaction?: { data?: { transaction?: { kind: string; inputs?: unknown[]; commands?: { MoveCall?: { package: string; module: string; function: string } }[] } } };
  }): void {
    // Gas analytics
    if (tx.effects?.gasUsed) {
      const gas = tx.effects.gasUsed;
      const totalCost = BigInt(gas.computationCost) + BigInt(gas.storageCost) - BigInt(gas.storageRebate);
      this.callbacks.onGasAnalytics({
        gasCostNative: (Number(totalCost) / 1e9).toFixed(9),
        chainId: this.network, vm: 'movevm',
        gasUsed: gas.computationCost,
      });
    }

    // Move call detection
    const commands = tx.transaction?.data?.transaction?.commands ?? [];
    for (const cmd of commands) {
      if (cmd.MoveCall) {
        const { package: pkg, module, function: fn } = cmd.MoveCall;
        const protocol = this.identifyProtocol(pkg);
        this.callbacks.onMoveCall({
          digest: tx.digest, package: pkg, module, function: fn,
          protocolName: protocol.name, category: protocol.category,
          vm: 'movevm', chainId: this.network,
        });
        if (protocol.category) {
          this.callbacks.onDeFiInteraction({
            txHash: tx.digest, protocol: protocol.name,
            category: protocol.category, action: `${module}::${fn}`,
            vm: 'movevm', chainId: this.network,
          });
        }
      }
    }
  }

  /** Get SUI coin balance */
  async getSUIBalance(address: string): Promise<TokenBalance | null> {
    try {
      const response = await fetch(this.getRpcUrl(), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0', id: 1, method: 'suix_getBalance',
          params: [address, '0x2::sui::SUI'],
        }),
      });
      const result = await response.json();
      const balance: TokenBalance = {
        symbol: 'SUI', name: 'SUI', contractAddress: '0x2::sui::SUI',
        balance: result?.result?.totalBalance ?? '0', decimals: 9,
        vm: 'movevm', chainId: this.network, standard: 'sui_coin',
      };
      this.callbacks.onTokenBalance(balance);
      return balance;
    } catch { return null; }
  }

  /** Get all coin balances for an address */
  async getAllBalances(address: string): Promise<TokenBalance[]> {
    try {
      const response = await fetch(this.getRpcUrl(), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0', id: 1, method: 'suix_getAllBalances', params: [address],
        }),
      });
      const result = await response.json();
      const balances: TokenBalance[] = (result?.result ?? []).map((b: { coinType: string; totalBalance: string }) => ({
        symbol: b.coinType.split('::').pop() ?? '', name: b.coinType,
        contractAddress: b.coinType, balance: b.totalBalance, decimals: 9,
        vm: 'movevm' as const, chainId: this.network, standard: 'sui_coin' as const,
      }));
      balances.forEach((b) => this.callbacks.onTokenBalance(b));
      return balances;
    } catch { return []; }
  }

  private identifyProtocol(packageId: string): { name: string; category?: DeFiCategory } {
    const shortId = packageId.slice(0, 6);
    return KNOWN_SUI_PROTOCOLS[shortId] ?? KNOWN_SUI_PROTOCOLS[packageId] ?? { name: 'Unknown' };
  }

  private getRpcUrl(): string {
    if (this.network.includes('testnet')) return 'https://fullnode.testnet.sui.io';
    if (this.network.includes('devnet')) return 'https://fullnode.devnet.sui.io';
    return 'https://fullnode.mainnet.sui.io';
  }

  destroy(): void { /* no timers */ }
}
