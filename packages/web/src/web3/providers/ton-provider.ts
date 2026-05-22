// =============================================================================
// Aether SDK — TON PROVIDER
// TON Wallet extension, Tonkeeper, TonConnect 2.0 (Telegram WebApp) detection.
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface TONAccount {
  address: string;
  chain: string;           // '-239' = mainnet, '-3' = testnet
  walletStateInit?: string;
  publicKey?: string;
}

interface TONProvider {
  send(method: string, params?: unknown): Promise<unknown>;
  listen?(callback: (event: { event: string; payload?: unknown }) => void): void;
  account?: TONAccount;
}

declare global {
  interface Window {
    ton?: TONProvider;
    tonkeeper?: TONProvider;
    __tc_bridge?: TONProvider;
  }
}

export class TonProvider extends BaseVMProvider {
  readonly vm: VMType = 'ton';
  readonly defaultChainId: string = 'ton:mainnet';

  private provider: TONProvider | null = null;
  private network: string = 'ton:mainnet';

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;
    const provider = window.tonkeeper ?? window.ton ?? window.__tc_bridge;
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
    if (typeof window === 'undefined') return 'unknown';
    if (this.provider === window.tonkeeper) return 'tonkeeper';
    if (this.provider === window.__tc_bridge) return 'tonconnect';
    if (this.provider === window.ton) return 'ton_wallet';
    return 'ton';
  }

  protected async monitorTransaction(txHash: string): Promise<void> {
    if (!this.wallet) return;
    let attempts = 0;
    const address = this.wallet.address;
    const check = async (): Promise<void> => {
      try {
        const response = await fetch(
          `https://toncenter.com/api/v2/getTransactions?address=${address}&limit=5`,
        );
        if (response.ok) {
          const result = await response.json();
          const txs: { transaction_id?: { hash?: string } }[] = result?.result ?? [];
          const match = txs.find((t) => t.transaction_id?.hash === txHash);
          if (match) {
            this.callbacks.onTransaction(txHash, {
              txHash, chainId: this.network, vm: 'ton', status: 'confirmed',
            });
            return;
          }
        }
        if (++attempts < 30) setTimeout(check, 5000);
      } catch { /* API error */ }
    };
    setTimeout(check, 5000);
  }

  // ---------------------------------------------------------------------------
  // Private — VM-specific helpers
  // ---------------------------------------------------------------------------

  private async setupProvider(provider: TONProvider): Promise<void> {
    this.provider = provider;
    this.walletType = this.detectWalletType();

    // Attempt to get existing connected account
    try {
      const account = (await provider.send('ton_requestAccounts')) as TONAccount[] | null;
      const addr = Array.isArray(account) ? account[0]?.address : (account as TONAccount | null)?.address;
      const chain = Array.isArray(account) ? account[0]?.chain : (account as TONAccount | null)?.chain;
      if (addr) {
        this.network = chain === '-3' ? 'ton:testnet' : 'ton:mainnet';
        this.connect(addr, { type: this.walletType, chainId: this.network });
      }
    } catch { /* not connected */ }

    // Listen for account events
    try {
      provider.listen?.((event) => {
        if (event.event === 'connect') {
          const payload = event.payload as TONAccount | undefined;
          if (payload?.address) {
            this.network = payload.chain === '-3' ? 'ton:testnet' : 'ton:mainnet';
            this.connect(payload.address, { type: this.walletType, chainId: this.network });
          }
        } else if (event.event === 'disconnect') {
          this.disconnect();
        }
      });
    } catch { /* wallet doesn't support listen */ }
  }
}
