// =============================================================================
// AETHER SDK — WEB3 MODULE
// Wallet tracking, chain detection, transaction monitoring
// =============================================================================

import type { WalletInfo, TransactionOptions } from './WebSDKTypes(CoreTypeDefinitions)';

export interface Web3Callbacks {
  onWalletEvent: (action: string, data: Record<string, unknown>) => void;
  onTransaction: (txHash: string, data: Record<string, unknown>) => void;
}

interface EthereumProvider {
  isMetaMask?: boolean;
  isCoinbaseWallet?: boolean;
  isBraveWallet?: boolean;
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  on: (event: string, handler: (...args: unknown[]) => void) => void;
  removeListener: (event: string, handler: (...args: unknown[]) => void) => void;
  selectedAddress?: string;
  chainId?: string;
}

declare global {
  interface Window {
    ethereum?: EthereumProvider;
  }
}

export class Web3Module {
  private callbacks: Web3Callbacks;
  private wallet: WalletInfo | null = null;
  private provider: EthereumProvider | null = null;
  private handlers: Array<[string, (...args: unknown[]) => void]> = [];

  constructor(callbacks: Web3Callbacks) {
    this.callbacks = callbacks;
  }

  /** Initialize Web3 detection and auto-tracking */
  init(): void {
    if (typeof window === 'undefined') return;

    // Detect existing provider
    if (window.ethereum) {
      this.setupProvider(window.ethereum);
    }

    // Watch for late-injected providers (e.g., MetaMask mobile)
    window.addEventListener('ethereum#initialized', () => {
      if (window.ethereum) this.setupProvider(window.ethereum);
    });
  }

  /** Manually record a wallet connection */
  connect(address: string, options?: Partial<WalletInfo>): void {
    this.wallet = {
      address: address.toLowerCase(),
      chainId: options?.chainId ?? 1,
      type: options?.type ?? this.detectWalletType(),
      ens: options?.ens,
      isConnected: true,
      connectedAt: new Date().toISOString(),
    };

    this.callbacks.onWalletEvent('connect', {
      address: this.wallet.address,
      chainId: this.wallet.chainId,
      walletType: this.wallet.type,
      ens: this.wallet.ens,
    });
  }

  /** Record wallet disconnect */
  disconnect(): void {
    if (!this.wallet) return;

    this.callbacks.onWalletEvent('disconnect', {
      address: this.wallet.address,
      chainId: this.wallet.chainId,
      walletType: this.wallet.type,
    });

    this.wallet = { ...this.wallet, isConnected: false };
  }

  /** Get current wallet info */
  getInfo(): WalletInfo | null {
    return this.wallet ? { ...this.wallet } : null;
  }

  /** Track a transaction */
  transaction(txHash: string, options?: TransactionOptions): void {
    this.callbacks.onTransaction(txHash, {
      txHash,
      chainId: options?.chainId ?? this.wallet?.chainId ?? 1,
      type: options?.type ?? 'custom',
      value: options?.value,
      from: options?.from ?? this.wallet?.address,
      to: options?.to,
      status: 'pending',
      ...(options?.metadata ?? {}),
    });

    // Auto-monitor transaction status if provider available
    if (this.provider) {
      this.monitorTransaction(txHash, options?.chainId ?? this.wallet?.chainId ?? 1);
    }
  }

  /** Destroy Web3 module */
  destroy(): void {
    if (this.provider) {
      this.handlers.forEach(([event, handler]) => {
        this.provider!.removeListener(event, handler);
      });
    }
    this.handlers = [];
    this.wallet = null;
    this.provider = null;
  }

  // ===========================================================================
  // PRIVATE
  // ===========================================================================

  private setupProvider(provider: EthereumProvider): void {
    this.provider = provider;

    // Auto-detect existing connection
    if (provider.selectedAddress) {
      this.connect(provider.selectedAddress, {
        chainId: parseInt(provider.chainId ?? '0x1', 16),
        type: this.detectWalletType(),
      });
    }

    // Listen for account changes
    const accountHandler = (accounts: unknown) => {
      const accts = accounts as string[];
      if (accts.length === 0) {
        this.disconnect();
      } else if (accts[0] !== this.wallet?.address) {
        this.connect(accts[0], {
          chainId: this.wallet?.chainId,
          type: this.detectWalletType(),
        });
      }
    };

    // Listen for chain changes
    const chainHandler = (chainId: unknown) => {
      const newChainId = parseInt(chainId as string, 16);
      if (this.wallet) {
        this.wallet.chainId = newChainId;
        this.callbacks.onWalletEvent('switch_chain', {
          address: this.wallet.address,
          chainId: newChainId,
          walletType: this.wallet.type,
        });
      }
    };

    provider.on('accountsChanged', accountHandler);
    provider.on('chainChanged', chainHandler);

    this.handlers.push(
      ['accountsChanged', accountHandler],
      ['chainChanged', chainHandler]
    );
  }

  private detectWalletType(): string {
    if (!this.provider) return 'unknown';
    if (this.provider.isMetaMask) return 'metamask';
    if (this.provider.isCoinbaseWallet) return 'coinbase';
    if (this.provider.isBraveWallet) return 'brave';
    return 'injected';
  }

  private async monitorTransaction(txHash: string, chainId: number): Promise<void> {
    if (!this.provider) return;

    const maxAttempts = 60;
    let attempts = 0;

    const check = async (): Promise<void> => {
      try {
        const receipt = (await this.provider!.request({
          method: 'eth_getTransactionReceipt',
          params: [txHash],
        })) as { status: string; gasUsed: string } | null;

        if (receipt) {
          const status = receipt.status === '0x1' ? 'confirmed' : 'failed';
          this.callbacks.onTransaction(txHash, {
            txHash,
            chainId,
            status,
            gasUsed: receipt.gasUsed,
          });
          return;
        }

        attempts++;
        if (attempts < maxAttempts) {
          setTimeout(check, 5000); // poll every 5 seconds
        }
      } catch {
        // Provider error, stop monitoring
      }
    };

    setTimeout(check, 3000); // Initial delay
  }
}
