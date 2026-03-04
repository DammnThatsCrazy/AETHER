// =============================================================================
// AETHER SDK — BITCOIN PROVIDER
// UniSat, Xverse, Leather, OKX BTC wallet detection
// =============================================================================

import type { WalletInfo } from '../../types';

export interface BitcoinProviderCallbacks {
  onWalletEvent: (action: string, data: Record<string, unknown>) => void;
  onTransaction: (txid: string, data: Record<string, unknown>) => void;
}

interface BTCProvider {
  requestAccounts(): Promise<string[]>;
  getAccounts(): Promise<string[]>;
  getBalance?(): Promise<{ confirmed: number; unconfirmed: number; total: number }>;
  getNetwork?(): Promise<string>;
  signPsbt?(psbtHex: string): Promise<string>;
  signMessage?(message: string): Promise<string>;
  on?(event: string, handler: (...args: unknown[]) => void): void;
  removeListener?(event: string, handler: (...args: unknown[]) => void): void;
}

declare global {
  interface Window {
    unisat?: BTCProvider;
    xverse?: { bitcoin?: BTCProvider };
    LeatherProvider?: BTCProvider;
    okxwallet?: { bitcoin?: BTCProvider };
  }
}

export class BitcoinProvider {
  private callbacks: BitcoinProviderCallbacks;
  private provider: BTCProvider | null = null;
  private wallet: WalletInfo | null = null;
  private walletType: string = 'unknown';
  private network: string = 'mainnet';
  private handlers: Array<[string, (...args: unknown[]) => void]> = [];

  constructor(callbacks: BitcoinProviderCallbacks) {
    this.callbacks = callbacks;
  }

  init(): void {
    if (typeof window === 'undefined') return;

    const provider =
      window.unisat ??
      window.xverse?.bitcoin ??
      window.LeatherProvider ??
      window.okxwallet?.bitcoin;

    if (provider) {
      this.setupProvider(provider);
    }
  }

  connect(address: string, options?: Partial<WalletInfo>): void {
    this.wallet = {
      address,
      chainId: this.network,
      type: options?.type ?? this.walletType,
      vm: 'bitcoin',
      classification: 'hot',
      isConnected: true,
      connectedAt: new Date().toISOString(),
    };

    this.callbacks.onWalletEvent('connect', {
      address, chainId: this.network, walletType: this.wallet.type, vm: 'bitcoin',
      classification: 'hot', addressType: this.detectAddressType(address),
    });
  }

  disconnect(): void {
    if (!this.wallet) return;
    this.callbacks.onWalletEvent('disconnect', {
      address: this.wallet.address, chainId: this.network,
      walletType: this.wallet.type, vm: 'bitcoin',
    });
    this.wallet = { ...this.wallet, isConnected: false };
  }

  getWallet(): WalletInfo | null {
    return this.wallet ? { ...this.wallet } : null;
  }

  transaction(txid: string, data: Record<string, unknown>): void {
    this.callbacks.onTransaction(txid, {
      txHash: txid, chainId: this.network, vm: 'bitcoin',
      status: 'pending', ...data,
    });
    this.monitorTransaction(txid);
  }

  destroy(): void {
    if (this.provider) {
      this.handlers.forEach(([event, handler]) => {
        this.provider?.removeListener?.(event, handler);
      });
    }
    this.handlers = [];
    this.wallet = null;
    this.provider = null;
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private async setupProvider(provider: BTCProvider): Promise<void> {
    this.provider = provider;
    this.walletType = this.detectWalletType();

    // Detect network
    if (provider.getNetwork) {
      try {
        this.network = await provider.getNetwork() ?? 'mainnet';
      } catch { this.network = 'mainnet'; }
    }

    // Try to get existing accounts
    try {
      const accounts = await provider.getAccounts();
      if (accounts.length > 0) {
        this.connect(accounts[0], { type: this.walletType });
      }
    } catch { /* not connected */ }

    // Account change events
    if (provider.on) {
      const accountHandler = (accounts: unknown) => {
        const accts = accounts as string[];
        if (accts.length === 0) {
          this.disconnect();
        } else {
          this.connect(accts[0], { type: this.walletType });
        }
      };
      provider.on('accountsChanged', accountHandler);
      this.handlers.push(['accountsChanged', accountHandler]);
    }
  }

  private detectWalletType(): string {
    if (typeof window === 'undefined') return 'unknown';
    if (window.unisat) return 'unisat';
    if (window.xverse?.bitcoin) return 'xverse';
    if (window.LeatherProvider) return 'leather';
    if (window.okxwallet?.bitcoin) return 'okx';
    return 'bitcoin';
  }

  private detectAddressType(address: string): string {
    if (address.startsWith('bc1p') || address.startsWith('tb1p')) return 'taproot';
    if (address.startsWith('bc1') || address.startsWith('tb1')) return 'native_segwit';
    if (address.startsWith('3')) return 'segwit';
    if (address.startsWith('1')) return 'legacy';
    return 'unknown';
  }

  private async monitorTransaction(txid: string): Promise<void> {
    let attempts = 0;
    const maxAttempts = 120; // BTC blocks are ~10 min
    const check = async (): Promise<void> => {
      try {
        const response = await fetch(`https://mempool.space/api/tx/${txid}/status`);
        if (response.ok) {
          const status = await response.json();
          if (status.confirmed) {
            this.callbacks.onTransaction(txid, {
              txHash: txid, chainId: this.network, vm: 'bitcoin',
              status: 'confirmed', blockHeight: status.block_height,
              blockHash: status.block_hash, blockTime: status.block_time,
            });
            return;
          }
        }
        if (++attempts < maxAttempts) setTimeout(check, 15000);
      } catch { /* API error */ }
    };
    setTimeout(check, 10000);
  }
}
