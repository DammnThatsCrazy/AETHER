// =============================================================================
// AETHER SDK — COSMOS / SEI PROVIDER
// Keplr, Leap wallet detection
// =============================================================================

import type { WalletInfo } from '../../types';

export interface CosmosProviderCallbacks {
  onWalletEvent: (action: string, data: Record<string, unknown>) => void;
  onTransaction: (txHash: string, data: Record<string, unknown>) => void;
}

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

export class CosmosProvider {
  private callbacks: CosmosProviderCallbacks;
  private provider: KeplrProvider | null = null;
  private wallet: WalletInfo | null = null;
  private chainId: string = 'sei-pacific-1';
  private walletType: string = 'unknown';

  constructor(callbacks: CosmosProviderCallbacks) {
    this.callbacks = callbacks;
  }

  init(): void {
    if (typeof window === 'undefined') return;
    const provider = window.keplr ?? window.leap;
    if (provider) this.setupProvider(provider);
  }

  connect(address: string, options?: Partial<WalletInfo>): void {
    this.wallet = {
      address: address.toLowerCase(), chainId: this.chainId,
      type: options?.type ?? this.walletType, vm: 'cosmos',
      classification: 'hot', isConnected: true,
      connectedAt: new Date().toISOString(),
    };
    this.callbacks.onWalletEvent('connect', {
      address: this.wallet.address, chainId: this.chainId,
      walletType: this.wallet.type, vm: 'cosmos', classification: 'hot',
    });
  }

  disconnect(): void {
    if (!this.wallet) return;
    this.callbacks.onWalletEvent('disconnect', {
      address: this.wallet.address, chainId: this.chainId,
      walletType: this.wallet.type, vm: 'cosmos',
    });
    this.wallet = { ...this.wallet, isConnected: false };
  }

  getWallet(): WalletInfo | null {
    return this.wallet ? { ...this.wallet } : null;
  }

  transaction(txHash: string, data: Record<string, unknown>): void {
    this.callbacks.onTransaction(txHash, {
      txHash, chainId: this.chainId, vm: 'cosmos',
      status: 'pending', ...data,
    });
    this.monitorTransaction(txHash);
  }

  destroy(): void {
    this.wallet = null;
    this.provider = null;
  }

  private async setupProvider(provider: KeplrProvider): Promise<void> {
    this.provider = provider;
    this.walletType = window.keplr === provider ? 'keplr' : 'leap';
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

  private async monitorTransaction(txHash: string): Promise<void> {
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
}
