// =============================================================================
// Aether SDK — BASE VM PROVIDER
// Shared abstract base for all non-EVM VM providers
// =============================================================================

import type { WalletInfo } from '../../types';

export type VMType = 'evm' | 'svm' | 'bitcoin' | 'movevm' | 'near' | 'tvm' | 'cosmos';

export interface ProviderCallbacks {
  onWalletEvent: (action: string, data: Record<string, unknown>) => void;
  onTransaction: (txId: string, data: Record<string, unknown>) => void;
}

export abstract class BaseVMProvider {
  protected callbacks: ProviderCallbacks;
  protected wallet: WalletInfo | null = null;
  protected walletType: string = 'unknown';

  abstract readonly vm: VMType;
  abstract readonly defaultChainId: string | number;

  constructor(callbacks: ProviderCallbacks) {
    this.callbacks = callbacks;
  }

  abstract init(): void;
  protected abstract detectWalletType(): string;
  protected abstract monitorTransaction(txId: string): Promise<void>;

  connect(address: string, options?: Partial<WalletInfo>): void {
    this.wallet = {
      address: this.vm === 'bitcoin' ? address : address.toLowerCase(),
      chainId: options?.chainId ?? this.defaultChainId,
      type: options?.type ?? this.walletType,
      vm: this.vm,
      classification: 'hot',
      isConnected: true,
      connectedAt: new Date().toISOString(),
    };
    this.callbacks.onWalletEvent('connect', {
      address: this.wallet.address,
      chainId: this.wallet.chainId,
      walletType: this.wallet.type,
      vm: this.vm,
      classification: 'hot',
    });
  }

  disconnect(): void {
    if (!this.wallet) return;
    this.callbacks.onWalletEvent('disconnect', {
      address: this.wallet.address,
      chainId: this.wallet.chainId,
      walletType: this.wallet.type,
      vm: this.vm,
    });
    this.wallet = { ...this.wallet, isConnected: false };
  }

  getWallet(): WalletInfo | null {
    return this.wallet ? { ...this.wallet } : null;
  }

  transaction(txId: string, data: Record<string, unknown>): void {
    this.callbacks.onTransaction(txId, {
      txHash: txId,
      chainId: this.wallet?.chainId ?? this.defaultChainId,
      vm: this.vm,
      status: 'pending',
      ...data,
    });
    this.monitorTransaction(txId);
  }

  destroy(): void {
    this.wallet = null;
  }
}
