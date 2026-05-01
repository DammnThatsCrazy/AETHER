// =============================================================================
// Aether SDK — NEAR PROTOCOL PROVIDER
// NEAR Wallet, MyNearWallet, Meteor wallet detection
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface NEARWalletProvider {
  accountId?: string;
  isSignedIn?(): boolean;
  getAccountId?(): string;
  signIn?(opts?: { contractId?: string }): Promise<void>;
  signOut?(): Promise<void>;
  signAndSendTransaction?(params: unknown): Promise<{ transaction: { hash: string } }>;
  on?(event: string, handler: (...args: unknown[]) => void): void;
}

declare global {
  interface Window {
    near?: NEARWalletProvider;
    myNearWallet?: NEARWalletProvider;
    meteorWallet?: NEARWalletProvider;
  }
}

export class NEARProvider extends BaseVMProvider {
  readonly vm: VMType = 'near';
  readonly defaultChainId: string = 'near:mainnet';

  private provider: NEARWalletProvider | null = null;
  private network: string = 'near:mainnet';

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;
    const provider = window.near ?? window.myNearWallet ?? window.meteorWallet;
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
    if (window.meteorWallet) return 'meteor';
    if (window.myNearWallet) return 'mynearwallet';
    if (window.near) return 'near_wallet';
    return 'near';
  }

  protected async monitorTransaction(txHash: string): Promise<void> {
    let attempts = 0;
    const check = async (): Promise<void> => {
      try {
        const response = await fetch('https://rpc.mainnet.near.org', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            jsonrpc: '2.0', id: 1, method: 'tx',
            params: [txHash, this.wallet?.address ?? ''],
          }),
        });
        const result = await response.json();
        if (result?.result?.status) {
          const succeeded = typeof result.result.status === 'object' && 'SuccessValue' in result.result.status;
          this.callbacks.onTransaction(txHash, {
            txHash, chainId: this.network, vm: 'near',
            status: succeeded ? 'confirmed' : 'failed',
          });
          return;
        }
        if (++attempts < 30) setTimeout(check, 3000);
      } catch { /* RPC error */ }
    };
    setTimeout(check, 2000);
  }

  // ---------------------------------------------------------------------------
  // Private — VM-specific helpers
  // ---------------------------------------------------------------------------

  private setupProvider(provider: NEARWalletProvider): void {
    this.provider = provider;
    this.walletType = this.detectWalletType();
    if (provider.isSignedIn?.() && provider.getAccountId) {
      this.connect(provider.getAccountId(), { type: this.walletType });
    }
  }
}
