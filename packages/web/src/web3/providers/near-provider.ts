// =============================================================================
// AETHER SDK — NEAR PROTOCOL PROVIDER
// NEAR Wallet, MyNearWallet, Meteor wallet detection
// =============================================================================

import type { WalletInfo } from '../../types';

export interface NEARProviderCallbacks {
  onWalletEvent: (action: string, data: Record<string, unknown>) => void;
  onTransaction: (txHash: string, data: Record<string, unknown>) => void;
}

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

export class NEARProvider {
  private callbacks: NEARProviderCallbacks;
  private provider: NEARWalletProvider | null = null;
  private wallet: WalletInfo | null = null;
  private network: string = 'near:mainnet';
  private walletType: string = 'unknown';

  constructor(callbacks: NEARProviderCallbacks) {
    this.callbacks = callbacks;
  }

  init(): void {
    if (typeof window === 'undefined') return;
    const provider = window.near ?? window.myNearWallet ?? window.meteorWallet;
    if (provider) this.setupProvider(provider);
  }

  connect(accountId: string, options?: Partial<WalletInfo>): void {
    this.wallet = {
      address: accountId.toLowerCase(), chainId: this.network,
      type: options?.type ?? this.walletType, vm: 'near',
      classification: 'hot', isConnected: true,
      connectedAt: new Date().toISOString(),
    };
    this.callbacks.onWalletEvent('connect', {
      address: this.wallet.address, chainId: this.network,
      walletType: this.wallet.type, vm: 'near', classification: 'hot',
      nearAccountId: accountId,
    });
  }

  disconnect(): void {
    if (!this.wallet) return;
    this.callbacks.onWalletEvent('disconnect', {
      address: this.wallet.address, chainId: this.network,
      walletType: this.wallet.type, vm: 'near',
    });
    this.wallet = { ...this.wallet, isConnected: false };
  }

  getWallet(): WalletInfo | null {
    return this.wallet ? { ...this.wallet } : null;
  }

  transaction(txHash: string, data: Record<string, unknown>): void {
    this.callbacks.onTransaction(txHash, {
      txHash, chainId: this.network, vm: 'near', status: 'pending', ...data,
    });
    this.monitorTransaction(txHash);
  }

  destroy(): void {
    this.wallet = null;
    this.provider = null;
  }

  private setupProvider(provider: NEARWalletProvider): void {
    this.provider = provider;
    this.walletType = this.detectWalletType();
    if (provider.isSignedIn?.() && provider.getAccountId) {
      this.connect(provider.getAccountId(), { type: this.walletType });
    }
  }

  private detectWalletType(): string {
    if (typeof window === 'undefined') return 'unknown';
    if (window.meteorWallet) return 'meteor';
    if (window.myNearWallet) return 'mynearwallet';
    if (window.near) return 'near_wallet';
    return 'near';
  }

  private async monitorTransaction(txHash: string): Promise<void> {
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
}
