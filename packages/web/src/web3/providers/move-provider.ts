// =============================================================================
// Aether SDK — MOVE VM PROVIDER (SUI)
// SUI Wallet, Ethos, Martian, Surf detection
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface SuiWalletProvider {
  hasPermissions?(): Promise<boolean>;
  requestPermissions?(): Promise<boolean>;
  getAccounts?(): Promise<{ address: string }[]>;
  signAndExecuteTransactionBlock?(input: unknown): Promise<{ digest: string }>;
  signMessage?(input: { message: Uint8Array }): Promise<{ signature: string }>;
  on?(event: string, handler: (...args: unknown[]) => void): void;
  off?(event: string, handler: (...args: unknown[]) => void): void;
  features?: Record<string, unknown>;
  name?: string;
}

declare global {
  interface Window {
    suiWallet?: SuiWalletProvider;
    ethosWallet?: SuiWalletProvider;
    martian?: { sui?: SuiWalletProvider };
    surfWallet?: SuiWalletProvider;
  }
}

export class MoveProvider extends BaseVMProvider {
  readonly vm: VMType = 'movevm';
  readonly defaultChainId: string = 'sui:mainnet';

  private provider: SuiWalletProvider | null = null;
  private network: string = 'sui:mainnet';

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;
    const provider = window.suiWallet ?? window.ethosWallet ?? window.martian?.sui ?? window.surfWallet;
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
    return this.provider?.name ?? 'sui_wallet';
  }

  protected async monitorTransaction(digest: string): Promise<void> {
    let attempts = 0;
    const check = async (): Promise<void> => {
      try {
        const response = await fetch('https://fullnode.mainnet.sui.io', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            jsonrpc: '2.0', id: 1, method: 'sui_getTransactionBlock',
            params: [digest, { showEffects: true }],
          }),
        });
        const result = await response.json();
        if (result?.result?.effects?.status) {
          const status = result.result.effects.status.status === 'success' ? 'confirmed' : 'failed';
          this.callbacks.onTransaction(digest, {
            txHash: digest, chainId: this.network, vm: 'movevm', status,
            gasUsed: result.result.effects.gasUsed,
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

  private async setupProvider(provider: SuiWalletProvider): Promise<void> {
    this.provider = provider;
    this.walletType = this.detectWalletType();
    try {
      const accounts = await provider.getAccounts?.();
      if (accounts && accounts.length > 0) {
        this.connect(accounts[0].address, { type: this.walletType });
      }
    } catch { /* not connected */ }
  }
}
