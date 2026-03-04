// =============================================================================
// AETHER SDK — EVM PROVIDER (EIP-6963 + Legacy window.ethereum)
// Multi-wallet detection: MetaMask, Coinbase, Brave, Rainbow, Rabby, Trust,
// Frame, Zerion, OKX, Ledger Live, Trezor, GridPlus
// =============================================================================

import type { WalletInfo, WalletClassification } from '../../types';

export interface EVMProviderCallbacks {
  onWalletEvent: (action: string, data: Record<string, unknown>) => void;
  onTransaction: (txHash: string, data: Record<string, unknown>) => void;
}

interface EIP6963ProviderDetail {
  info: { uuid: string; name: string; icon: string; rdns: string };
  provider: EthereumProvider;
}

interface EthereumProvider {
  isMetaMask?: boolean;
  isCoinbaseWallet?: boolean;
  isBraveWallet?: boolean;
  isRabby?: boolean;
  isRainbow?: boolean;
  isTrust?: boolean;
  isFrame?: boolean;
  isZerion?: boolean;
  isOKExWallet?: boolean;
  isLedgerConnect?: boolean;
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  on: (event: string, handler: (...args: unknown[]) => void) => void;
  removeListener: (event: string, handler: (...args: unknown[]) => void) => void;
  selectedAddress?: string;
  chainId?: string;
}

declare global {
  interface WindowEventMap {
    'eip6963:announceProvider': CustomEvent<EIP6963ProviderDetail>;
  }
  interface Window {
    ethereum?: EthereumProvider;
  }
}

export class EVMProvider {
  private callbacks: EVMProviderCallbacks;
  private providers: Map<string, { info: EIP6963ProviderDetail['info']; provider: EthereumProvider }> = new Map();
  private wallets: Map<string, WalletInfo> = new Map();
  private handlers: Array<[EthereumProvider, string, (...args: unknown[]) => void]> = [];
  private eip6963Handler: ((e: Event) => void) | null = null;

  constructor(callbacks: EVMProviderCallbacks) {
    this.callbacks = callbacks;
  }

  init(): void {
    if (typeof window === 'undefined') return;

    // EIP-6963: Modern multi-provider discovery
    this.eip6963Handler = (event: Event) => {
      const detail = (event as CustomEvent<EIP6963ProviderDetail>).detail;
      if (detail?.info && detail?.provider) {
        this.registerProvider(detail.info.rdns, detail.info, detail.provider);
      }
    };
    window.addEventListener('eip6963:announceProvider', this.eip6963Handler);
    window.dispatchEvent(new Event('eip6963:requestProvider'));

    // Legacy: window.ethereum fallback
    if (window.ethereum) {
      const type = this.detectWalletType(window.ethereum);
      this.registerProvider(type, { uuid: 'legacy', name: type, icon: '', rdns: type }, window.ethereum);
    }

    // Watch for late-injected providers
    window.addEventListener('ethereum#initialized', () => {
      if (window.ethereum && this.providers.size === 0) {
        const type = this.detectWalletType(window.ethereum);
        this.registerProvider(type, { uuid: 'legacy', name: type, icon: '', rdns: type }, window.ethereum);
      }
    });
  }

  connect(address: string, options?: Partial<WalletInfo>): void {
    const wallet: WalletInfo = {
      address: address.toLowerCase(),
      chainId: options?.chainId ?? 1,
      type: options?.type ?? 'injected',
      vm: 'evm',
      classification: options?.classification ?? this.classifyProvider(options?.type),
      ens: options?.ens,
      isConnected: true,
      connectedAt: new Date().toISOString(),
    };
    this.wallets.set(wallet.address, wallet);
    this.callbacks.onWalletEvent('connect', {
      address: wallet.address, chainId: wallet.chainId,
      walletType: wallet.type, vm: 'evm', classification: wallet.classification, ens: wallet.ens,
    });
  }

  disconnect(address?: string): void {
    if (address) {
      const wallet = this.wallets.get(address.toLowerCase());
      if (wallet) {
        this.callbacks.onWalletEvent('disconnect', {
          address: wallet.address, chainId: wallet.chainId, walletType: wallet.type, vm: 'evm',
        });
        wallet.isConnected = false;
      }
    } else {
      this.wallets.forEach((wallet) => {
        this.callbacks.onWalletEvent('disconnect', {
          address: wallet.address, chainId: wallet.chainId, walletType: wallet.type, vm: 'evm',
        });
        wallet.isConnected = false;
      });
    }
  }

  getWallets(): WalletInfo[] {
    return Array.from(this.wallets.values()).filter((w) => w.isConnected);
  }

  getPrimaryWallet(): WalletInfo | null {
    const connected = this.getWallets();
    return connected.length > 0 ? { ...connected[0] } : null;
  }

  transaction(txHash: string, data: Record<string, unknown>): void {
    this.callbacks.onTransaction(txHash, { ...data, vm: 'evm' });
    const provider = this.getActiveProvider();
    if (provider) {
      this.monitorTransaction(provider, txHash, (data.chainId as number) ?? 1);
    }
  }

  destroy(): void {
    this.handlers.forEach(([provider, event, handler]) => {
      provider.removeListener(event, handler);
    });
    this.handlers = [];
    if (this.eip6963Handler) {
      window.removeEventListener('eip6963:announceProvider', this.eip6963Handler);
    }
    this.wallets.clear();
    this.providers.clear();
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private registerProvider(id: string, info: EIP6963ProviderDetail['info'], provider: EthereumProvider): void {
    if (this.providers.has(id)) return;
    this.providers.set(id, { info, provider });

    // Auto-detect existing connection
    if (provider.selectedAddress) {
      this.connect(provider.selectedAddress, {
        chainId: parseInt(provider.chainId ?? '0x1', 16),
        type: this.detectWalletType(provider),
      });
    }

    // Account changes
    const accountHandler = (accounts: unknown) => {
      const accts = accounts as string[];
      if (accts.length === 0) {
        this.disconnect();
      } else {
        const addr = accts[0].toLowerCase();
        if (!this.wallets.has(addr) || !this.wallets.get(addr)!.isConnected) {
          this.connect(accts[0], { chainId: this.wallets.values().next().value?.chainId, type: this.detectWalletType(provider) });
        }
      }
    };

    // Chain changes
    const chainHandler = (chainId: unknown) => {
      const newChainId = parseInt(chainId as string, 16);
      this.wallets.forEach((wallet) => {
        wallet.chainId = newChainId;
      });
      const primary = this.getPrimaryWallet();
      if (primary) {
        this.callbacks.onWalletEvent('switch_chain', {
          address: primary.address, chainId: newChainId, walletType: primary.type, vm: 'evm',
        });
      }
    };

    provider.on('accountsChanged', accountHandler);
    provider.on('chainChanged', chainHandler);
    this.handlers.push([provider, 'accountsChanged', accountHandler], [provider, 'chainChanged', chainHandler]);
  }

  private detectWalletType(provider: EthereumProvider): string {
    if (provider.isMetaMask) return 'metamask';
    if (provider.isCoinbaseWallet) return 'coinbase';
    if (provider.isBraveWallet) return 'brave';
    if (provider.isRabby) return 'rabby';
    if (provider.isRainbow) return 'rainbow';
    if (provider.isTrust) return 'trust';
    if (provider.isFrame) return 'frame';
    if (provider.isZerion) return 'zerion';
    if (provider.isOKExWallet) return 'okx';
    if (provider.isLedgerConnect) return 'ledger';
    return 'injected';
  }

  private classifyProvider(type?: string): WalletClassification {
    if (!type) return 'hot';
    if (['ledger', 'trezor', 'gridplus', 'keystone'].includes(type)) return 'cold';
    return 'hot';
  }

  private getActiveProvider(): EthereumProvider | null {
    const first = this.providers.values().next().value;
    return first?.provider ?? null;
  }

  private async monitorTransaction(provider: EthereumProvider, txHash: string, chainId: number): Promise<void> {
    let attempts = 0;
    const maxAttempts = 60;
    const check = async (): Promise<void> => {
      try {
        const receipt = (await provider.request({
          method: 'eth_getTransactionReceipt', params: [txHash],
        })) as { status: string; gasUsed: string } | null;
        if (receipt) {
          const status = receipt.status === '0x1' ? 'confirmed' : 'failed';
          this.callbacks.onTransaction(txHash, { txHash, chainId, status, gasUsed: receipt.gasUsed, vm: 'evm' });
          return;
        }
        if (++attempts < maxAttempts) setTimeout(check, 5000);
      } catch { /* provider error */ }
    };
    setTimeout(check, 3000);
  }
}
