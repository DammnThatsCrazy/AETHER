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
    martian?: { aptos?: unknown; sui?: unknown };
    surfWallet?: SuiWalletProvider;
    suiet?: SuiWalletProvider;
    nightly?: { aptos?: unknown; solana?: unknown; sui?: unknown };
  }
}

export class MoveProvider extends BaseVMProvider {
  readonly vm: VMType = 'movevm';
  readonly defaultChainId: string = 'sui:mainnet';

  private provider: SuiWalletProvider | null = null;

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;
    const provider: SuiWalletProvider | undefined =
      window.suiWallet ??
      window.ethosWallet ??
      (window.martian?.sui as SuiWalletProvider | undefined) ??
      window.surfWallet ??
      window.suiet ??
      (window.nightly?.sui as SuiWalletProvider | undefined);
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
    if (typeof window === 'undefined' || !this.provider) return 'sui_wallet';
    if (this.provider === window.suiet) return 'suiet';
    if (this.provider === (window.nightly?.sui as SuiWalletProvider | undefined)) return 'nightly_sui';
    if (this.provider === window.surfWallet) return 'surf';
    if (this.provider === window.ethosWallet) return 'ethos';
    if (this.provider === (window.martian?.sui as SuiWalletProvider | undefined)) return 'martian';
    return this.provider.name ?? 'sui_wallet';
  }

  protected async monitorTransaction(digest: string): Promise<void> {
    // Keep this SDK observation-only. Sui JSON-RPC is deprecated and disabled
    // on Mainnet; the backend verifies the digest through a configured Sui
    // GraphQL provider and is the only layer allowed to update execution status.
    void digest;
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
        this.connect(accounts[0]!.address, { type: this.walletType });
      }
    } catch { /* not connected */ }
  }
}
