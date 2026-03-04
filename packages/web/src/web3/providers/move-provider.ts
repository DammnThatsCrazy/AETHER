// =============================================================================
// AETHER SDK — MOVE VM PROVIDER (SUI)
// SUI Wallet, Ethos, Martian, Surf detection
// =============================================================================

import type { WalletInfo } from '../../types';

export interface MoveProviderCallbacks {
  onWalletEvent: (action: string, data: Record<string, unknown>) => void;
  onTransaction: (digest: string, data: Record<string, unknown>) => void;
}

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

export class MoveProvider {
  private callbacks: MoveProviderCallbacks;
  private provider: SuiWalletProvider | null = null;
  private wallet: WalletInfo | null = null;
  private network: string = 'sui:mainnet';
  private walletType: string = 'unknown';

  constructor(callbacks: MoveProviderCallbacks) {
    this.callbacks = callbacks;
  }

  init(): void {
    if (typeof window === 'undefined') return;
    const provider = window.suiWallet ?? window.ethosWallet ?? window.martian?.sui ?? window.surfWallet;
    if (provider) this.setupProvider(provider);
  }

  connect(address: string, options?: Partial<WalletInfo>): void {
    this.wallet = {
      address: address.toLowerCase(), chainId: this.network,
      type: options?.type ?? this.walletType, vm: 'movevm',
      classification: 'hot', isConnected: true,
      connectedAt: new Date().toISOString(),
    };
    this.callbacks.onWalletEvent('connect', {
      address: this.wallet.address, chainId: this.network,
      walletType: this.wallet.type, vm: 'movevm', classification: 'hot',
    });
  }

  disconnect(): void {
    if (!this.wallet) return;
    this.callbacks.onWalletEvent('disconnect', {
      address: this.wallet.address, chainId: this.network,
      walletType: this.wallet.type, vm: 'movevm',
    });
    this.wallet = { ...this.wallet, isConnected: false };
  }

  getWallet(): WalletInfo | null {
    return this.wallet ? { ...this.wallet } : null;
  }

  transaction(digest: string, data: Record<string, unknown>): void {
    this.callbacks.onTransaction(digest, {
      txHash: digest, chainId: this.network, vm: 'movevm',
      status: 'pending', ...data,
    });
    this.monitorTransaction(digest);
  }

  destroy(): void {
    this.wallet = null;
    this.provider = null;
  }

  private async setupProvider(provider: SuiWalletProvider): Promise<void> {
    this.provider = provider;
    this.walletType = provider.name ?? 'sui_wallet';
    try {
      const accounts = await provider.getAccounts?.();
      if (accounts && accounts.length > 0) {
        this.connect(accounts[0].address, { type: this.walletType });
      }
    } catch { /* not connected */ }
  }

  private async monitorTransaction(digest: string): Promise<void> {
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
}
