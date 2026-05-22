// =============================================================================
// Aether SDK — STELLAR PROVIDER
// Freighter wallet detection (window.freighter / SEP-0007).
// xBull, Rabet wallet detection.
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface FreighterAPI {
  getPublicKey(): Promise<string>;
  isConnected(): Promise<boolean>;
  getNetwork(): Promise<string>;
  getNetworkDetails(): Promise<{ network: string; networkUrl: string; networkPassphrase: string }>;
  signTransaction(xdr: string, opts?: { network?: string; networkPassphrase?: string }): Promise<string>;
}

interface XBullAPI {
  connect(opts?: { canRequestPublicKey?: boolean }): Promise<{ message?: string }>;
  getPublicKey(): Promise<string>;
}

declare global {
  interface Window {
    freighter?: FreighterAPI;
    xBullSDK?: XBullAPI;
    rabet?: { connect(): Promise<{ publicKey: string; network: string }> };
  }
}

export class StellarProvider extends BaseVMProvider {
  readonly vm: VMType = 'stellar';
  readonly defaultChainId: string = 'stellar:mainnet';

  private network: string = 'stellar:mainnet';

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;
    if (window.freighter) {
      this.walletType = 'freighter';
      this.setupFreighter(window.freighter);
    } else if (window.xBullSDK) {
      this.walletType = 'xbull';
      this.setupXBull(window.xBullSDK);
    } else if (window.rabet) {
      this.walletType = 'rabet';
      this.setupRabet(window.rabet);
    }
  }

  destroy(): void {
    super.destroy();
  }

  // ---------------------------------------------------------------------------
  // Protected — abstract implementations
  // ---------------------------------------------------------------------------

  protected detectWalletType(): string {
    if (typeof window === 'undefined') return 'stellar';
    if (window.freighter) return 'freighter';
    if (window.xBullSDK) return 'xbull';
    if (window.rabet) return 'rabet';
    return 'stellar';
  }

  protected async monitorTransaction(txHash: string): Promise<void> {
    let attempts = 0;
    const check = async (): Promise<void> => {
      try {
        const response = await fetch(
          `https://horizon.stellar.org/transactions/${txHash}`,
        );
        if (response.ok) {
          const tx = await response.json() as { successful?: boolean };
          if (tx?.successful !== undefined) {
            this.callbacks.onTransaction(txHash, {
              txHash, chainId: this.network, vm: 'stellar',
              status: tx.successful ? 'confirmed' : 'failed',
            });
            return;
          }
        }
        if (++attempts < 20) setTimeout(check, 5000);
      } catch { /* Horizon unavailable */ }
    };
    setTimeout(check, 3000);
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private async setupFreighter(api: FreighterAPI): Promise<void> {
    try {
      const connected = await api.isConnected();
      if (!connected) return;
      const [publicKey, network] = await Promise.all([api.getPublicKey(), api.getNetwork()]);
      this.network = network === 'TESTNET' ? 'stellar:testnet' : 'stellar:mainnet';
      if (publicKey) {
        this.connect(publicKey, { type: 'freighter', chainId: this.network });
      }
    } catch { /* not connected */ }
  }

  private async setupXBull(api: XBullAPI): Promise<void> {
    try {
      await api.connect({ canRequestPublicKey: true });
      const publicKey = await api.getPublicKey();
      if (publicKey) {
        this.connect(publicKey, { type: 'xbull', chainId: this.network });
      }
    } catch { /* user rejected */ }
  }

  private async setupRabet(rabet: { connect(): Promise<{ publicKey: string; network: string }> }): Promise<void> {
    try {
      const result = await rabet.connect();
      if (result?.publicKey) {
        this.network = result.network === 'testnet' ? 'stellar:testnet' : 'stellar:mainnet';
        this.connect(result.publicKey, { type: 'rabet', chainId: this.network });
      }
    } catch { /* user rejected */ }
  }
}
