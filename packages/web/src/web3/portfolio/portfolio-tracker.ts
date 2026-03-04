// =============================================================================
// AETHER SDK — PORTFOLIO TRACKER
// Cross-chain multi-wallet aggregation across all VMs
// =============================================================================

import type {
  VMType, ConnectedWallet, TokenBalance, NFTAsset,
  DeFiPosition, PortfolioSnapshot, WalletClassification,
} from '../../types';

export interface PortfolioCallbacks {
  onPortfolioUpdate: (snapshot: PortfolioSnapshot) => void;
  onWalletAdded: (wallet: ConnectedWallet) => void;
  onWalletRemoved: (address: string, vm: VMType) => void;
}

export interface PortfolioConfig {
  refreshIntervalMs?: number;
  autoRefresh?: boolean;
}

export class PortfolioTracker {
  private callbacks: PortfolioCallbacks;
  private config: Required<PortfolioConfig>;
  private wallets: Map<string, ConnectedWallet> = new Map();
  private tokenBalances: Map<string, TokenBalance[]> = new Map();
  private nfts: Map<string, NFTAsset[]> = new Map();
  private defiPositions: Map<string, DeFiPosition[]> = new Map();
  private refreshTimer: ReturnType<typeof setInterval> | null = null;
  private listeners: ((snapshot: PortfolioSnapshot) => void)[] = [];

  constructor(callbacks: PortfolioCallbacks, config?: PortfolioConfig) {
    this.callbacks = callbacks;
    this.config = {
      refreshIntervalMs: config?.refreshIntervalMs ?? 60000,
      autoRefresh: config?.autoRefresh ?? true,
    };

    if (this.config.autoRefresh) {
      this.startAutoRefresh();
    }
  }

  /** Add a connected wallet */
  addWallet(wallet: ConnectedWallet): void {
    const key = this.walletKey(wallet.address, wallet.vm);
    this.wallets.set(key, wallet);
    this.callbacks.onWalletAdded(wallet);
    this.emitUpdate();
  }

  /** Remove a wallet */
  removeWallet(address: string, vm: VMType): void {
    const key = this.walletKey(address, vm);
    this.wallets.delete(key);
    this.tokenBalances.delete(key);
    this.nfts.delete(key);
    this.defiPositions.delete(key);
    this.callbacks.onWalletRemoved(address, vm);
    this.emitUpdate();
  }

  /** Update token balances for a wallet */
  updateTokenBalances(address: string, vm: VMType, balances: TokenBalance[]): void {
    const key = this.walletKey(address, vm);
    this.tokenBalances.set(key, balances);
  }

  /** Update NFTs for a wallet */
  updateNFTs(address: string, vm: VMType, assets: NFTAsset[]): void {
    const key = this.walletKey(address, vm);
    this.nfts.set(key, assets);
  }

  /** Update DeFi positions for a wallet */
  updateDeFiPositions(address: string, vm: VMType, positions: DeFiPosition[]): void {
    const key = this.walletKey(address, vm);
    this.defiPositions.set(key, positions);
  }

  /** Get all connected wallets */
  getWallets(): ConnectedWallet[] {
    return Array.from(this.wallets.values());
  }

  /** Get wallets by VM type */
  getWalletsByVM(vm: VMType): ConnectedWallet[] {
    return this.getWallets().filter((w) => w.vm === vm);
  }

  /** Get complete portfolio snapshot */
  getPortfolio(): PortfolioSnapshot {
    const wallets = this.getWallets();
    const tokens = this.getAllTokens();
    const nfts = this.getAllNFTs();
    const defiPositions = this.getAllDeFiPositions();

    // Calculate total USD value
    const tokenValue = tokens.reduce((sum, t) => sum + (t.usdValue ?? 0), 0);
    const defiValue = defiPositions.reduce((sum, p) => sum + (p.valueUSD ?? 0), 0);
    const totalValueUSD = tokenValue + defiValue;

    // Aggregate by chain
    const chainMap = new Map<string, { vm: VMType; chainId: number | string; name: string; valueUSD: number }>();
    for (const token of tokens) {
      const key = `${token.vm}:${token.chainId}`;
      const existing = chainMap.get(key);
      if (existing) {
        existing.valueUSD += token.usdValue ?? 0;
      } else {
        chainMap.set(key, {
          vm: token.vm, chainId: token.chainId,
          name: `${token.vm}:${token.chainId}`, valueUSD: token.usdValue ?? 0,
        });
      }
    }

    return {
      wallets,
      totalValueUSD: totalValueUSD > 0 ? totalValueUSD : undefined,
      chains: Array.from(chainMap.values()),
      tokens, nfts, defiPositions,
      timestamp: new Date().toISOString(),
    };
  }

  /** Register callback for portfolio changes */
  onUpdate(callback: (snapshot: PortfolioSnapshot) => void): () => void {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== callback);
    };
  }

  /** Get primary wallet (first connected) */
  getPrimaryWallet(): ConnectedWallet | null {
    const primary = Array.from(this.wallets.values()).find((w) => w.isPrimary);
    if (primary) return primary;
    const first = this.wallets.values().next().value;
    return first ?? null;
  }

  /** Create a ConnectedWallet from basic info */
  static createWallet(
    address: string, vm: VMType, chainId: number | string,
    walletType: string, classification: WalletClassification,
    options?: { ens?: string; sns?: string; isPrimary?: boolean },
  ): ConnectedWallet {
    return {
      address, vm, chainId, walletType, classification,
      displayName: `${walletType} (${address.slice(0, 6)}...${address.slice(-4)})`,
      ens: options?.ens, sns: options?.sns,
      connectedAt: new Date().toISOString(),
      isConnected: true,
      isPrimary: options?.isPrimary ?? false,
    };
  }

  /** Destroy and clean up */
  destroy(): void {
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = null;
    }
    this.wallets.clear();
    this.tokenBalances.clear();
    this.nfts.clear();
    this.defiPositions.clear();
    this.listeners = [];
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private walletKey(address: string, vm: VMType): string {
    return `${vm}:${address.toLowerCase()}`;
  }

  private getAllTokens(): TokenBalance[] {
    const all: TokenBalance[] = [];
    this.tokenBalances.forEach((balances) => all.push(...balances));
    return all;
  }

  private getAllNFTs(): NFTAsset[] {
    const all: NFTAsset[] = [];
    this.nfts.forEach((assets) => all.push(...assets));
    return all;
  }

  private getAllDeFiPositions(): DeFiPosition[] {
    const all: DeFiPosition[] = [];
    this.defiPositions.forEach((positions) => all.push(...positions));
    return all;
  }

  private emitUpdate(): void {
    const snapshot = this.getPortfolio();
    this.callbacks.onPortfolioUpdate(snapshot);
    this.listeners.forEach((l) => { try { l(snapshot); } catch { /* */ } });
  }

  private startAutoRefresh(): void {
    this.refreshTimer = setInterval(() => {
      this.emitUpdate();
    }, this.config.refreshIntervalMs);
  }
}
