// =============================================================================
// Aether SDK — STARKNET PROVIDER
// ArgentX, Braavos wallet detection via window.starknet_* and wallet:event:announce.
// All Starknet accounts are smart contract accounts (no EOAs).
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

interface StarknetAccount {
  address: string;
  signer?: { pk?: string };
}

interface StarknetWallet {
  id?: string;
  name?: string;
  version?: string;
  isConnected?: boolean;
  account?: StarknetAccount;
  selectedAddress?: string;
  chainId?: string;
  enable(options?: { starknetVersion?: string }): Promise<string[]>;
  request(call: { type: string; params?: unknown }): Promise<unknown>;
  on(event: string, handler: (...args: unknown[]) => void): void;
  off?(event: string, handler: (...args: unknown[]) => void): void;
}

interface StarknetWalletAnnounce {
  wallet: StarknetWallet;
}

declare global {
  interface WindowEventMap {
    'wallet:event:announce': CustomEvent<StarknetWalletAnnounce>;
  }
  interface Window {
    starknet_argentX?: StarknetWallet;
    starknet_braavos?: StarknetWallet;
    starknet?: StarknetWallet;
  }
}

export class StarknetProvider extends BaseVMProvider {
  readonly vm: VMType = 'starknet';
  readonly defaultChainId: string = 'SN_MAIN';

  private provider: StarknetWallet | null = null;
  private network: string = 'SN_MAIN';
  private announceHandler: ((e: Event) => void) | null = null;

  constructor(callbacks: ProviderCallbacks) {
    super(callbacks);
  }

  init(): void {
    if (typeof window === 'undefined') return;

    // wallet:event:announce discovery (Starknet's equivalent of EIP-6963)
    this.announceHandler = (event: Event) => {
      const detail = (event as CustomEvent<StarknetWalletAnnounce>).detail;
      if (detail?.wallet && !this.provider) {
        this.setupProvider(detail.wallet);
      }
    };
    window.addEventListener('wallet:event:announce', this.announceHandler);
    window.dispatchEvent(new Event('wallet:event:request'));

    // Fallback: direct window property injection (ArgentX, Braavos)
    const provider = window.starknet_argentX ?? window.starknet_braavos ?? window.starknet;
    if (provider && !this.provider) {
      this.setupProvider(provider);
    }
  }

  destroy(): void {
    if (this.announceHandler) {
      window.removeEventListener('wallet:event:announce', this.announceHandler);
      this.announceHandler = null;
    }
    this.provider = null;
    super.destroy();
  }

  // ---------------------------------------------------------------------------
  // Protected — abstract implementations
  // ---------------------------------------------------------------------------

  protected detectWalletType(): string {
    if (typeof window === 'undefined') return 'unknown';
    if (this.provider === window.starknet_argentX) return 'argent_x';
    if (this.provider === window.starknet_braavos) return 'braavos';
    return this.provider?.id ?? this.provider?.name ?? 'starknet';
  }

  protected async monitorTransaction(txHash: string): Promise<void> {
    let attempts = 0;
    const gatewayBase = this.network === 'SN_MAIN'
      ? 'https://alpha-mainnet.starknet.io'
      : 'https://alpha-sepolia.starknet.io';
    const check = async (): Promise<void> => {
      try {
        const response = await fetch(
          `${gatewayBase}/feeder_gateway/get_transaction?transactionHash=${txHash}`,
        );
        if (response.ok) {
          const tx = await response.json();
          const execStatus = tx?.execution_status;
          const finStatus = tx?.finality_status;
          if (execStatus === 'SUCCEEDED' || finStatus === 'ACCEPTED_ON_L2' || finStatus === 'ACCEPTED_ON_L1') {
            this.callbacks.onTransaction(txHash, {
              txHash, chainId: this.network, vm: 'starknet', status: 'confirmed',
              actualFee: tx.actual_fee,
            });
            return;
          }
          if (execStatus === 'REVERTED') {
            this.callbacks.onTransaction(txHash, {
              txHash, chainId: this.network, vm: 'starknet', status: 'failed',
            });
            return;
          }
        }
        if (++attempts < 30) setTimeout(check, 4000);
      } catch { /* gateway error */ }
    };
    setTimeout(check, 3000);
  }

  // ---------------------------------------------------------------------------
  // Private — VM-specific helpers
  // ---------------------------------------------------------------------------

  private async setupProvider(wallet: StarknetWallet): Promise<void> {
    if (this.provider) return;
    this.provider = wallet;
    this.walletType = this.detectWalletType();

    // Auto-detect existing connection
    if (wallet.isConnected && wallet.selectedAddress) {
      this.network = wallet.chainId ?? 'SN_MAIN';
      // All Starknet accounts are smart contract wallets
      this.connect(wallet.selectedAddress, { type: this.walletType, classification: 'smart', chainId: this.network });
    }

    // Account and network change events
    try {
      wallet.on('accountsChanged', (...args: unknown[]) => {
        const accounts = args[0] as string[] | undefined;
        if (!accounts || accounts.length === 0) {
          this.disconnect();
        } else {
          this.connect(accounts[0], { type: this.walletType, classification: 'smart', chainId: this.network });
        }
      });
      wallet.on('networkChanged', (...args: unknown[]) => {
        const networkId = args[0] as string | undefined;
        if (networkId) this.network = networkId;
      });
    } catch { /* wallet may not support events */ }
  }
}
