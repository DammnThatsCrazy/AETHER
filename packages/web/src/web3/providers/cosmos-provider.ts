// =============================================================================
// Aether SDK — COSMOS / SEI PROVIDER
// Keplr, Leap wallet detection
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface KeplrProvider {
  enable(chainId: string): Promise<void>;
  getKey(chainId: string): Promise<{ bech32Address: string; name: string; algo: string; pubKey: Uint8Array }>;
  signAmino?(chainId: string, signer: string, signDoc: unknown): Promise<unknown>;
  signDirect?(chainId: string, signer: string, signDoc: unknown): Promise<unknown>;
  experimentalSuggestChain?(chainInfo: unknown): Promise<void>;
}

declare global {
  interface Window {
    keplr?: KeplrProvider;
    leap?: KeplrProvider;
  }
}

export class CosmosProvider extends BaseVMProvider {
  readonly vm: VMType = 'cosmos';
  readonly defaultChainId: string = 'sei-pacific-1';

  private provider: KeplrProvider | null = null;
  private chainId: string = 'sei-pacific-1';

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;
    const provider = window.keplr ?? window.leap;
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
    if (window.keplr) return 'keplr';
    if (window.leap) return 'leap';
    return 'cosmos';
  }

  protected async monitorTransaction(txHash: string): Promise<void> {
    let attempts = 0;
    const rpc = this.chainId === 'sei-pacific-1'
      ? 'https://sei-rpc.polkachu.com'
      : 'https://cosmos-rpc.polkachu.com';
    const check = async (): Promise<void> => {
      try {
        const response = await fetch(`${rpc}/tx?hash=0x${txHash}`);
        const result = await response.json();
        if (result?.result?.tx_result) {
          const code = result.result.tx_result.code;
          this.callbacks.onTransaction(txHash, {
            txHash, chainId: this.chainId, vm: 'cosmos',
            status: code === 0 ? 'confirmed' : 'failed',
            gasUsed: result.result.tx_result.gas_used,
          });
          return;
        }
        if (++attempts < 30) setTimeout(check, 5000);
      } catch { /* RPC error */ }
    };
    setTimeout(check, 3000);
  }

  // ---------------------------------------------------------------------------
  // Private — VM-specific helpers
  // ---------------------------------------------------------------------------

  private async setupProvider(provider: KeplrProvider): Promise<void> {
    this.provider = provider;
    this.walletType = this.detectWalletType();
    try {
      await provider.enable(this.chainId);
      const key = await provider.getKey(this.chainId);
      this.connect(key.bech32Address, { type: this.walletType });
    } catch { /* not authorized */ }

    // Keplr account change
    window.addEventListener('keplr_keystorechange', async () => {
      if (!this.provider) return;
      try {
        const key = await this.provider.getKey(this.chainId);
        this.connect(key.bech32Address, { type: this.walletType });
      } catch { /* error */ }
    });
  }
}
