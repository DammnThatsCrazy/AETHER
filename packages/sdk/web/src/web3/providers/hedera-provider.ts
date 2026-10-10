// =============================================================================
// Aether SDK — HEDERA PROVIDER
// HashPack wallet detection (window.hashpack / HIP-338 standard).
// Blade wallet detection (window.bladeWallet).
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface HederaWallet {
  pairingData?: { accountIds: string[]; network: string };
  sendRequest?(message: unknown): Promise<unknown>;
}

interface BladeWallet {
  getAccountId(): Promise<string>;
  getAccountInfo(accountId: string): Promise<unknown>;
  sendRequest?(method: string, params?: unknown): Promise<unknown>;
}

declare global {
  interface Window {
    hashpack?: HederaWallet;
    bladeWallet?: BladeWallet;
  }
}

export class HederaProvider extends BaseVMProvider {
  readonly vm: VMType = 'hedera';
  readonly defaultChainId: string = 'hedera:mainnet';

  private network: string = 'hedera:mainnet';

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;
    if (window.hashpack) {
      this.walletType = 'hashpack';
      this.setupHashPack(window.hashpack);
    } else if (window.bladeWallet) {
      this.walletType = 'blade';
      this.setupBlade(window.bladeWallet);
    }
  }

  destroy(): void {
    super.destroy();
  }

  // ---------------------------------------------------------------------------
  // Protected — abstract implementations
  // ---------------------------------------------------------------------------

  protected detectWalletType(): string {
    if (typeof window === 'undefined') return 'hedera';
    if (window.hashpack) return 'hashpack';
    if (window.bladeWallet) return 'blade';
    return 'hedera';
  }

  protected async monitorTransaction(txId: string): Promise<void> {
    // Hedera transaction IDs: accountId@seconds.nanos
    let attempts = 0;
    const normalizedId = txId.replace('@', '-').replace('.', '-');
    const check = async (): Promise<void> => {
      try {
        const response = await fetch(
          `https://mainnet-public.mirrornode.hedera.com/api/v1/transactions/${normalizedId}`,
        );
        if (response.ok) {
          const data = await response.json() as { transactions?: { result?: string }[] };
          const tx = data?.transactions?.[0];
          if (tx?.result === 'SUCCESS') {
            this.callbacks.onTransaction(txId, {
              txHash: txId, chainId: this.network, vm: 'hedera', status: 'confirmed',
            });
            return;
          }
        }
        if (++attempts < 20) setTimeout(check, 5000);
      } catch { /* API unavailable */ }
    };
    setTimeout(check, 4000);
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private setupHashPack(wallet: HederaWallet): void {
    const pairing = wallet.pairingData;
    if (pairing?.accountIds?.length) {
      this.network = pairing.network === 'mainnet' ? 'hedera:mainnet' : 'hedera:testnet';
      this.connect(pairing.accountIds[0], { type: 'hashpack', chainId: this.network });
    }
  }

  private async setupBlade(wallet: BladeWallet): Promise<void> {
    try {
      const accountId = await wallet.getAccountId();
      if (accountId) {
        this.connect(accountId, { type: 'blade', chainId: this.network });
      }
    } catch { /* not connected */ }
  }
}
