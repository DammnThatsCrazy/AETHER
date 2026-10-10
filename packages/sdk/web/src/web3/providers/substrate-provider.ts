// =============================================================================
// Aether SDK — SUBSTRATE / POLKADOT PROVIDER
// Polkadot.js, SubWallet, Talisman, Nova wallet detection.
// Uses the injectedWeb3 standard (window.injectedWeb3).
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface InjectedAccount {
  address: string;
  name?: string;
  type?: string;
  genesisHash?: string | null;
}

interface InjectedAccounts {
  get(anyType?: boolean): Promise<InjectedAccount[]>;
  subscribe(cb: (accounts: InjectedAccount[]) => void): () => void;
}

interface InjectedExtension {
  name: string;
  version?: string;
  accounts: InjectedAccounts;
  enable(origin: string): Promise<{ accounts: InjectedAccounts }>;
}

declare global {
  interface Window {
    injectedWeb3?: Record<string, { version?: string; enable(origin: string): Promise<InjectedExtension> }>;
    SubWallet?: unknown;
    talismanEth?: unknown;
  }
}

const SUBSTRATE_WALLET_PRIORITY = [
  'subwallet-js',
  'talisman',
  'polkadot-js',
  'nova',
  'enkrypt',
];

export class SubstrateProvider extends BaseVMProvider {
  readonly vm: VMType = 'substrate';
  readonly defaultChainId: string = 'polkadot';

  private extension: InjectedExtension | null = null;
  private unsubscribe: (() => void) | null = null;

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined' || !window.injectedWeb3) return;
    const injected = window.injectedWeb3;
    for (const name of SUBSTRATE_WALLET_PRIORITY) {
      if (injected[name]) {
        this.walletType = name;
        this.setupProvider(injected[name], name);
        return;
      }
    }
    // Fallback: first available
    const firstKey = Object.keys(injected)[0];
    if (firstKey) {
      this.walletType = firstKey;
      this.setupProvider(injected[firstKey], firstKey);
    }
  }

  destroy(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.extension = null;
    super.destroy();
  }

  // ---------------------------------------------------------------------------
  // Protected — abstract implementations
  // ---------------------------------------------------------------------------

  protected detectWalletType(): string {
    return this.walletType ?? 'polkadot';
  }

  protected async monitorTransaction(txHash: string): Promise<void> {
    let attempts = 0;
    const check = async (): Promise<void> => {
      try {
        const response = await fetch(
          `https://polkadot.api.subscan.io/api/scan/extrinsic`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hash: txHash }),
          },
        );
        if (response.ok) {
          const data = await response.json() as { data?: { finalized?: boolean } };
          if (data?.data?.finalized) {
            this.callbacks.onTransaction(txHash, {
              txHash, chainId: this.defaultChainId, vm: 'substrate', status: 'confirmed',
            });
            return;
          }
        }
        if (++attempts < 30) setTimeout(check, 6000);
      } catch { /* API unavailable */ }
    };
    setTimeout(check, 4000);
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private async setupProvider(
    raw: { version?: string; enable(origin: string): Promise<InjectedExtension> },
    name: string,
  ): Promise<void> {
    try {
      const ext = await raw.enable('Aether SDK');
      this.extension = ext;
      const accounts = await ext.accounts.get();
      if (accounts.length > 0) {
        this.connect(accounts[0].address, { type: name, chainId: 'polkadot' });
      }
      // Subscribe to account changes
      this.unsubscribe = ext.accounts.subscribe((updated) => {
        if (updated.length > 0) {
          this.connect(updated[0].address, { type: name, chainId: 'polkadot' });
        } else {
          this.disconnect();
        }
      });
    } catch { /* user rejected or extension unavailable */ }
  }
}
