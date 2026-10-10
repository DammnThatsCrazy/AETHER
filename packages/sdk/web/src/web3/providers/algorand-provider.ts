// =============================================================================
// Aether SDK — ALGORAND PROVIDER
// Pera Wallet, Defly, Kibisis (window.algorand ARC-0027 standard), AlgoSigner
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface AlgorandWalletProvider {
  enable(opts?: { genesisId?: string }): Promise<{ accounts: string[] }>;
  signTxns?(txns: { txn: string }[]): Promise<(string | null)[]>;
  on?(event: string, handler: (...args: unknown[]) => void): void;
  name?: string;
}

interface AlgoSignerAPI {
  accounts(opts: { ledger: string }): Promise<{ address: string }[]>;
  sign(params: unknown): Promise<unknown>;
}

declare global {
  interface Window {
    algorand?: AlgorandWalletProvider;
    AlgoSigner?: AlgoSignerAPI;
  }
}

export class AlgorandProvider extends BaseVMProvider {
  readonly vm: VMType = 'algorand';
  readonly defaultChainId: string = 'algorand:mainnet';

  private provider: AlgorandWalletProvider | null = null;
  private network: string = 'algorand:mainnet';

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;
    // ARC-0027 standard (Kibisis, Pera browser extension, Defly)
    if (window.algorand) {
      this.provider = window.algorand;
      this.walletType = window.algorand.name?.toLowerCase() ?? 'algorand';
      this.setupProvider(window.algorand);
    } else if (window.AlgoSigner) {
      this.walletType = 'algosigner';
      this.setupAlgoSigner(window.AlgoSigner);
    }
  }

  destroy(): void {
    this.provider = null;
    super.destroy();
  }

  // ---------------------------------------------------------------------------
  // Protected — abstract implementations
  // ---------------------------------------------------------------------------

  protected detectWalletType(): string {
    if (typeof window === 'undefined') return 'algorand';
    if (window.AlgoSigner && !window.algorand) return 'algosigner';
    return this.provider?.name?.toLowerCase() ?? 'algorand';
  }

  protected async monitorTransaction(txId: string): Promise<void> {
    let attempts = 0;
    const check = async (): Promise<void> => {
      try {
        const response = await fetch(
          `https://mainnet-api.algonode.cloud/v2/transactions/pending/${txId}`,
        );
        if (response.ok) {
          const data = await response.json() as { confirmed_round?: number };
          if (data?.confirmed_round && data.confirmed_round > 0) {
            this.callbacks.onTransaction(txId, {
              txHash: txId, chainId: this.network, vm: 'algorand', status: 'confirmed',
              confirmedRound: data.confirmed_round,
            });
            return;
          }
        }
        if (++attempts < 30) setTimeout(check, 5000);
      } catch { /* API unavailable */ }
    };
    setTimeout(check, 3000);
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private async setupProvider(provider: AlgorandWalletProvider): Promise<void> {
    try {
      const { accounts } = await provider.enable({ genesisId: 'mainnet-v1.0' });
      if (accounts.length > 0) {
        this.connect(accounts[0], { type: this.walletType, chainId: this.network });
      }
    } catch { /* user rejected or not connected */ }
  }

  private async setupAlgoSigner(algoSigner: AlgoSignerAPI): Promise<void> {
    try {
      const accounts = await algoSigner.accounts({ ledger: 'MainNet' });
      if (accounts.length > 0) {
        this.connect(accounts[0].address, { type: 'algosigner', chainId: this.network });
      }
    } catch { /* user rejected */ }
  }
}
