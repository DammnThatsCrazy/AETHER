// =============================================================================
// Aether SDK — BITCOIN PROVIDER
// UniSat, Xverse, Leather, OKX BTC wallet detection
// =============================================================================

import type { WalletInfo } from '../../types';
import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

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

export class BitcoinProvider extends BaseVMProvider {
  readonly vm: VMType = 'bitcoin';
  readonly defaultChainId: string = 'mainnet';

  private provider: BTCProvider | null = null;
  private network: string = 'mainnet';
  private handlers: Array<[string, (...args: unknown[]) => void]> = [];

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
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

  /** Override connect to include addressType and preserve BTC address casing */
  connect(address: string, options?: Partial<WalletInfo>): void {
    super.connect(address, options);
    // Emit extra addressType data
    this.callbacks.onWalletEvent('connect', {
      address,
      chainId: this.network,
      walletType: options?.type ?? this.walletType,
      vm: this.vm,
      classification: 'hot',
      addressType: this.detectAddressType(address),
    });
  }

  destroy(): void {
    if (this.provider) {
      this.handlers.forEach(([event, handler]) => {
        this.provider?.removeListener?.(event, handler);
      });
    }
    this.handlers = [];
    this.provider = null;
    super.destroy();
  }

  // ---------------------------------------------------------------------------
  // Protected — abstract implementations
  // ---------------------------------------------------------------------------

  protected detectWalletType(): string {
    if (typeof window === 'undefined') return 'unknown';
    if (window.unisat) return 'unisat';
    if (window.xverse?.bitcoin) return 'xverse';
    if (window.LeatherProvider) return 'leather';
    if (window.okxwallet?.bitcoin) return 'okx';
    return 'bitcoin';
  }

  protected async monitorTransaction(txid: string): Promise<void> {
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

  // ---------------------------------------------------------------------------
  // Private — VM-specific helpers
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

  private detectAddressType(address: string): string {
    if (address.startsWith('bc1p') || address.startsWith('tb1p')) return 'taproot';
    if (address.startsWith('bc1') || address.startsWith('tb1')) return 'native_segwit';
    if (address.startsWith('3')) return 'segwit';
    if (address.startsWith('1')) return 'legacy';
    return 'unknown';
  }
}
