// =============================================================================
// Aether SDK — SOLANA (SVM) PROVIDER
// Phantom, Solflare, Backpack, Solana Wallet Standard
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface SolanaProvider {
  isPhantom?: boolean;
  isSolflare?: boolean;
  isBackpack?: boolean;
  isGlow?: boolean;
  publicKey?: { toString(): string; toBase58(): string };
  isConnected?: boolean;
  connect(opts?: { onlyIfTrusted?: boolean }): Promise<{ publicKey: { toString(): string } }>;
  disconnect(): Promise<void>;
  signTransaction?(tx: unknown): Promise<unknown>;
  signAllTransactions?(txs: unknown[]): Promise<unknown[]>;
  signMessage?(message: Uint8Array): Promise<{ signature: Uint8Array }>;
  on(event: string, handler: (...args: unknown[]) => void): void;
  off?(event: string, handler: (...args: unknown[]) => void): void;
  removeListener?(event: string, handler: (...args: unknown[]) => void): void;
}

declare global {
  interface Window {
    solana?: SolanaProvider;
    phantom?: { solana?: SolanaProvider };
    solflare?: SolanaProvider;
    backpack?: { solana?: SolanaProvider };
    glow?: SolanaProvider;
  }
}

export class SVMProvider extends BaseVMProvider {
  readonly vm: VMType = 'svm';
  readonly defaultChainId: string = 'mainnet-beta';

  private provider: SolanaProvider | null = null;
  private cluster: string = 'mainnet-beta';
  private handlers: Array<[string, (...args: unknown[]) => void]> = [];

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;

    // Priority order: Phantom > Solflare > Backpack > Glow > generic
    const provider =
      window.phantom?.solana ??
      window.solflare ??
      window.backpack?.solana ??
      window.glow ??
      window.solana;

    if (provider) {
      this.setupProvider(provider);
    }
  }

  destroy(): void {
    if (this.provider) {
      this.handlers.forEach(([event, handler]) => {
        if (this.provider!.off) {
          this.provider!.off(event, handler);
        } else if (this.provider!.removeListener) {
          this.provider!.removeListener(event, handler);
        }
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
    if (!this.provider) return 'unknown';
    if (this.provider.isPhantom) return 'phantom';
    if (this.provider.isSolflare) return 'solflare';
    if (this.provider.isBackpack) return 'backpack';
    if (this.provider.isGlow) return 'glow';
    return 'solana';
  }

  protected async monitorTransaction(signature: string): Promise<void> {
    if (!this.provider) return;
    let attempts = 0;
    const maxAttempts = 60;
    const check = async (): Promise<void> => {
      try {
        // Use JSON-RPC to check signature status
        const response = await fetch(this.getRpcUrl(), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            jsonrpc: '2.0', id: 1, method: 'getSignatureStatuses',
            params: [[signature], { searchTransactionHistory: true }],
          }),
        });
        const result = await response.json();
        const status = result?.result?.value?.[0];
        if (status) {
          const confirmed = status.confirmationStatus === 'finalized' || status.confirmationStatus === 'confirmed';
          const failed = status.err !== null;
          this.callbacks.onTransaction(signature, {
            txHash: signature, chainId: this.cluster, vm: 'svm',
            status: failed ? 'failed' : confirmed ? 'confirmed' : 'pending',
            slot: status.slot, confirmations: status.confirmations,
          });
          if (confirmed || failed) return;
        }
        if (++attempts < maxAttempts) setTimeout(check, 3000);
      } catch { /* RPC error */ }
    };
    setTimeout(check, 2000);
  }

  // ---------------------------------------------------------------------------
  // Private — VM-specific helpers
  // ---------------------------------------------------------------------------

  private setupProvider(provider: SolanaProvider): void {
    this.provider = provider;
    this.walletType = this.detectWalletType();

    // Auto-detect existing connection
    if (provider.isConnected && provider.publicKey) {
      this.connect(provider.publicKey.toString(), { type: this.walletType });
    }

    // Account changes
    const connectHandler = (...args: unknown[]) => {
      const publicKey = args[0] as { toString(): string } | undefined;
      if (publicKey) {
        this.connect(publicKey.toString(), { type: this.walletType });
      }
    };

    const disconnectHandler = () => { this.disconnect(); };

    const accountChangeHandler = (publicKey: unknown) => {
      if (publicKey) {
        this.connect((publicKey as { toString(): string }).toString(), { type: this.walletType });
      } else {
        this.disconnect();
      }
    };

    provider.on('connect', connectHandler);
    provider.on('disconnect', disconnectHandler);
    provider.on('accountChanged', accountChangeHandler);

    this.handlers.push(
      ['connect', connectHandler],
      ['disconnect', disconnectHandler],
      ['accountChanged', accountChangeHandler]
    );
  }

  private getRpcUrl(): string {
    const rpcMap: Record<string, string> = {
      'mainnet-beta': 'https://api.mainnet-beta.solana.com',
      devnet: 'https://api.devnet.solana.com',
      testnet: 'https://api.testnet.solana.com',
    };
    return rpcMap[this.cluster] ?? rpcMap['mainnet-beta'];
  }
}
