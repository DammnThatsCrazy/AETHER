// =============================================================================
// Aether SDK — APTOS PROVIDER
// Petra, Martian (Aptos), Pontem, Fewcha, Nightly, Rise wallet detection.
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface AptosAccount {
  address: string;
  publicKey?: string;
}

interface AptosWalletProvider {
  connect(): Promise<AptosAccount>;
  disconnect(): Promise<void>;
  account(): Promise<AptosAccount>;
  isConnected(): Promise<boolean>;
  signAndSubmitTransaction?(payload: unknown): Promise<{ hash: string }>;
  signMessage?(payload: unknown): Promise<unknown>;
  onAccountChange?(callback: (account: AptosAccount | null) => void): void;
  onNetworkChange?(callback: (network: { name: string; chainId?: string }) => void): void;
  network?: string;
  name?: string;
}

declare global {
  interface Window {
    petra?: AptosWalletProvider;
    pontem?: AptosWalletProvider;
    fewcha?: AptosWalletProvider;
    rise?: AptosWalletProvider;
    martian?: { aptos?: unknown; sui?: unknown };
    nightly?: { aptos?: unknown; solana?: unknown; sui?: unknown };
  }
}

export class AptosProvider extends BaseVMProvider {
  readonly vm: VMType = 'aptos';
  readonly defaultChainId: string = 'aptos:mainnet';

  private provider: AptosWalletProvider | null = null;
  private network: string = 'aptos:mainnet';

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;
    const provider: AptosWalletProvider | undefined =
      window.petra ??
      (window.martian?.aptos as AptosWalletProvider | undefined) ??
      window.pontem ??
      window.fewcha ??
      (window.nightly?.aptos as AptosWalletProvider | undefined) ??
      window.rise;
    if (provider) this.setupProvider(provider);
  }

  destroy(): void {
    this.provider = null;
    super.destroy();
  }

  // ---------------------------------------------------------------------------
  // Protected — abstract implementations
  // ---------------------------------------------------------------------------

  protected detectWalletType(): string {
    if (typeof window === 'undefined') return 'unknown';
    if (this.provider === window.petra) return 'petra';
    if (this.provider === window.martian?.aptos) return 'martian_aptos';
    if (this.provider === window.pontem) return 'pontem';
    if (this.provider === window.fewcha) return 'fewcha';
    if (this.provider === window.nightly?.aptos) return 'nightly_aptos';
    if (this.provider === window.rise) return 'rise';
    return this.provider?.name ?? 'aptos';
  }

  protected async monitorTransaction(txHash: string): Promise<void> {
    let attempts = 0;
    const check = async (): Promise<void> => {
      try {
        const response = await fetch(
          `https://fullnode.mainnet.aptoslabs.com/v1/transactions/by_hash/${txHash}`,
        );
        if (response.ok) {
          const tx = await response.json();
          if (tx?.type && tx.type !== 'pending_transaction') {
            const status = tx.success === true ? 'confirmed' : 'failed';
            this.callbacks.onTransaction(txHash, {
              txHash, chainId: this.network, vm: 'aptos', status,
              gasUsed: tx.gas_used,
            });
            return;
          }
        }
        if (++attempts < 30) setTimeout(check, 3000);
      } catch { /* RPC error */ }
    };
    setTimeout(check, 2000);
  }

  // ---------------------------------------------------------------------------
  // Private — VM-specific helpers
  // ---------------------------------------------------------------------------

  private async setupProvider(provider: AptosWalletProvider): Promise<void> {
    this.provider = provider;
    this.walletType = this.detectWalletType();

    // Auto-detect existing connection
    try {
      const connected = await provider.isConnected();
      if (connected) {
        const account = await provider.account();
        if (account?.address) {
          this.connect(account.address, { type: this.walletType });
        }
      }
    } catch { /* not connected */ }

    // Account change callback
    try {
      provider.onAccountChange?.((account) => {
        if (account?.address) {
          this.connect(account.address, { type: this.walletType });
        } else {
          this.disconnect();
        }
      });
    } catch { /* wallet doesn't support onAccountChange */ }

    // Network change callback
    try {
      provider.onNetworkChange?.((network) => {
        this.network = `aptos:${network.name ?? 'mainnet'}`;
      });
    } catch { /* wallet doesn't support onNetworkChange */ }
  }
}
