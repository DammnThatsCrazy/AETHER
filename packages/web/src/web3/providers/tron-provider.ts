// =============================================================================
// AETHER SDK — TRON (TVM) PROVIDER
// TronLink / TronWeb detection
// =============================================================================

import type { WalletInfo } from '../../types';

export interface TronProviderCallbacks {
  onWalletEvent: (action: string, data: Record<string, unknown>) => void;
  onTransaction: (txid: string, data: Record<string, unknown>) => void;
}

interface TronWebProvider {
  ready?: boolean;
  defaultAddress?: { base58: string; hex: string };
  fullNode?: { host: string };
  trx?: {
    getBalance(address: string): Promise<number>;
    getTransaction(txid: string): Promise<{ ret?: { contractRet: string }[] }>;
    getAccount(address: string): Promise<unknown>;
    sign(tx: unknown): Promise<unknown>;
    sendRawTransaction(signedTx: unknown): Promise<{ result: boolean; txid: string }>;
  };
  contract?(): { at(address: string): Promise<unknown> };
  on?(event: string, handler: (...args: unknown[]) => void): void;
}

declare global {
  interface Window {
    tronWeb?: TronWebProvider;
    tronLink?: { ready?: boolean; tronWeb?: TronWebProvider };
  }
}

export class TronProvider {
  private callbacks: TronProviderCallbacks;
  private tronWeb: TronWebProvider | null = null;
  private wallet: WalletInfo | null = null;
  private network: string = 'tron:mainnet';

  constructor(callbacks: TronProviderCallbacks) {
    this.callbacks = callbacks;
  }

  init(): void {
    if (typeof window === 'undefined') return;

    const tw = window.tronLink?.tronWeb ?? window.tronWeb;
    if (tw) this.setupProvider(tw);

    // TronLink injects async
    window.addEventListener('tronLink#initialized', () => {
      const tw2 = window.tronLink?.tronWeb ?? window.tronWeb;
      if (tw2 && !this.tronWeb) this.setupProvider(tw2);
    });
  }

  connect(address: string, options?: Partial<WalletInfo>): void {
    this.wallet = {
      address, chainId: this.network,
      type: options?.type ?? 'tronlink', vm: 'tvm',
      classification: 'hot', isConnected: true,
      connectedAt: new Date().toISOString(),
    };
    this.callbacks.onWalletEvent('connect', {
      address, chainId: this.network, walletType: 'tronlink',
      vm: 'tvm', classification: 'hot',
    });
  }

  disconnect(): void {
    if (!this.wallet) return;
    this.callbacks.onWalletEvent('disconnect', {
      address: this.wallet.address, chainId: this.network,
      walletType: this.wallet.type, vm: 'tvm',
    });
    this.wallet = { ...this.wallet, isConnected: false };
  }

  getWallet(): WalletInfo | null {
    return this.wallet ? { ...this.wallet } : null;
  }

  transaction(txid: string, data: Record<string, unknown>): void {
    this.callbacks.onTransaction(txid, {
      txHash: txid, chainId: this.network, vm: 'tvm',
      status: 'pending', ...data,
    });
    this.monitorTransaction(txid);
  }

  destroy(): void {
    this.wallet = null;
    this.tronWeb = null;
  }

  private setupProvider(tw: TronWebProvider): void {
    this.tronWeb = tw;
    this.detectNetwork(tw);
    if (tw.ready && tw.defaultAddress?.base58) {
      this.connect(tw.defaultAddress.base58);
    }

    // Poll for account changes (TronLink doesn't have reliable events)
    let lastAddress = tw.defaultAddress?.base58;
    setInterval(() => {
      const currentTW = window.tronLink?.tronWeb ?? window.tronWeb;
      const current = currentTW?.defaultAddress?.base58;
      if (current !== lastAddress) {
        if (current) {
          this.connect(current);
        } else {
          this.disconnect();
        }
        lastAddress = current;
      }
    }, 3000);
  }

  private detectNetwork(tw: TronWebProvider): void {
    const host = tw.fullNode?.host ?? '';
    if (host.includes('shasta')) this.network = 'tron:shasta';
    else if (host.includes('nile')) this.network = 'tron:nile';
    else this.network = 'tron:mainnet';
  }

  private async monitorTransaction(txid: string): Promise<void> {
    if (!this.tronWeb?.trx) return;
    let attempts = 0;
    const check = async (): Promise<void> => {
      try {
        const tx = await this.tronWeb!.trx!.getTransaction(txid);
        if (tx?.ret && tx.ret.length > 0) {
          const status = tx.ret[0].contractRet === 'SUCCESS' ? 'confirmed' : 'failed';
          this.callbacks.onTransaction(txid, {
            txHash: txid, chainId: this.network, vm: 'tvm', status,
          });
          return;
        }
        if (++attempts < 40) setTimeout(check, 5000);
      } catch { /* API error */ }
    };
    setTimeout(check, 3000);
  }
}
