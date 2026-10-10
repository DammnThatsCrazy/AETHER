// =============================================================================
// Aether SDK — CARDANO PROVIDER (CIP-30)
// Nami, Eternl, Flint, Vespr, Yoroi, Lace, GeroWallet, NuFi wallet detection.
// Uses the CIP-30 standard: window.cardano.<walletName>.enable()
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface CIP30API {
  getUsedAddresses(paginate?: { page: number; limit: number }): Promise<string[]>;
  getUnusedAddresses(): Promise<string[]>;
  getChangeAddress(): Promise<string>;
  getNetworkId(): Promise<number>;
  getBalance(): Promise<string>;
  signTx?(tx: string, partialSign?: boolean): Promise<string>;
  signData?(address: string, payload: string): Promise<{ key: string; signature: string }>;
}

interface CIP30WalletHandle {
  enable(): Promise<CIP30API>;
  isEnabled(): Promise<boolean>;
  apiVersion: string;
  name: string;
  icon: string;
}

declare global {
  interface Window {
    cardano?: Record<string, CIP30WalletHandle>;
  }
}

const CIP30_WALLETS = [
  'nami', 'eternl', 'flint', 'vespr', 'yoroi', 'lace', 'gerowallet', 'nufi',
  'typhoncip30', 'begin', 'exodus', 'tokeo',
];

export class CardanoProvider extends BaseVMProvider {
  readonly vm: VMType = 'cardano';
  readonly defaultChainId: string = 'cardano:mainnet';

  private api: CIP30API | null = null;
  private walletHandle: CIP30WalletHandle | null = null;
  private network: string = 'cardano:mainnet';

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined' || !window.cardano) return;
    // Try wallets in priority order
    for (const name of CIP30_WALLETS) {
      const handle = window.cardano[name];
      if (handle) {
        this.walletHandle = handle;
        this.walletType = name;
        this.setupProvider(handle);
        return;
      }
    }
  }

  destroy(): void {
    this.api = null;
    this.walletHandle = null;
    super.destroy();
  }

  // ---------------------------------------------------------------------------
  // Protected — abstract implementations
  // ---------------------------------------------------------------------------

  protected detectWalletType(): string {
    return this.walletHandle?.name?.toLowerCase() ?? this.walletType ?? 'cardano';
  }

  protected async monitorTransaction(txHash: string): Promise<void> {
    let attempts = 0;
    const check = async (): Promise<void> => {
      try {
        const response = await fetch(
          `https://cardano-mainnet.blockfrost.io/api/v0/txs/${txHash}`,
          { headers: { project_id: '' } },
        );
        if (response.ok) {
          const tx = await response.json() as { block?: string };
          if (tx?.block) {
            this.callbacks.onTransaction(txHash, {
              txHash, chainId: this.network, vm: 'cardano', status: 'confirmed',
            });
            return;
          }
        }
        if (++attempts < 30) setTimeout(check, 10000);
      } catch { /* API unavailable */ }
    };
    setTimeout(check, 8000);
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private async setupProvider(handle: CIP30WalletHandle): Promise<void> {
    try {
      const enabled = await handle.isEnabled();
      if (!enabled) return;
      const api = await handle.enable();
      this.api = api;

      const networkId = await api.getNetworkId();
      this.network = networkId === 1 ? 'cardano:mainnet' : 'cardano:testnet';

      // CIP-30 addresses are CBOR-encoded; ship raw and let backend decode
      const usedAddresses = await api.getUsedAddresses({ page: 0, limit: 1 });
      const address = usedAddresses[0] ?? (await api.getChangeAddress());
      if (address) {
        this.connect(address, { type: this.walletType, chainId: this.network });
      }
    } catch { /* wallet not enabled or user rejected */ }
  }
}
