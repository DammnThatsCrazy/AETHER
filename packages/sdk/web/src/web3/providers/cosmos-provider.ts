// =============================================================================
// Aether SDK — COSMOS PROVIDER
// Keplr, Leap, Cosmostation, Station wallet detection.
// Supports multiple Cosmos chains via config.cosmosChains.
// Default chain list: SEI, Cosmos Hub, Osmosis, Injective, dYdX, Celestia, Akash.
// =============================================================================

import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';

const DEFAULT_COSMOS_CHAINS = [
  'pacific-1',        // SEI
  'cosmoshub-4',      // Cosmos Hub
  'osmosis-1',        // Osmosis
  'injective-1',      // Injective
  'dydx-mainnet-1',   // dYdX
  'celestia',         // Celestia
  'akashnet-2',       // Akash
];

const COSMOS_RPC_MAP: Record<string, string> = {
  'pacific-1':      'https://sei-rpc.polkachu.com',
  'cosmoshub-4':    'https://cosmos-rpc.polkachu.com',
  'osmosis-1':      'https://osmosis-rpc.polkachu.com',
  'injective-1':    'https://injective-rpc.polkachu.com',
  'dydx-mainnet-1': 'https://dydx-rpc.polkachu.com',
  'celestia':       'https://celestia-rpc.polkachu.com',
  'akashnet-2':     'https://akash-rpc.polkachu.com',
};

interface KeplrProvider {
  enable(chainId: string | string[]): Promise<void>;
  getKey(chainId: string): Promise<{ bech32Address: string; name: string; algo: string; pubKey: Uint8Array }>;
  signAmino?(chainId: string, signer: string, signDoc: unknown): Promise<unknown>;
  signDirect?(chainId: string, signer: string, signDoc: unknown): Promise<unknown>;
  experimentalSuggestChain?(chainInfo: unknown): Promise<void>;
}

export interface CosmosProviderConfig {
  supportedChains?: string[];
}

declare global {
  interface Window {
    keplr?: KeplrProvider;
    leap?: KeplrProvider;
    cosmostation?: { providers?: { keplr?: KeplrProvider } };
    station?: KeplrProvider;
  }
}

export class CosmosProvider extends BaseVMProvider {
  readonly vm: VMType = 'cosmos';
  readonly defaultChainId: string = 'pacific-1';

  private provider: KeplrProvider | null = null;
  private chainId: string = 'pacific-1';
  private supportedChains: string[];

  constructor(callbacks: ProviderCallbacks, config?: CosmosProviderConfig) {
    super(callbacks);
    this.supportedChains = config?.supportedChains ?? DEFAULT_COSMOS_CHAINS;
  }

  init(): void {
    if (typeof window === 'undefined') return;
    const provider = window.keplr ?? window.leap ?? window.cosmostation?.providers?.keplr ?? window.station;
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
    if (window.keplr) return 'keplr';
    if (window.leap) return 'leap';
    if (window.cosmostation) return 'cosmostation';
    if (window.station) return 'station';
    return 'cosmos';
  }

  protected async monitorTransaction(txHash: string): Promise<void> {
    let attempts = 0;
    const rpc = COSMOS_RPC_MAP[this.chainId] ?? 'https://cosmos-rpc.polkachu.com';
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

  // ---------------------------------------------------------------------------
  // Private — VM-specific helpers
  // ---------------------------------------------------------------------------

  private async setupProvider(provider: KeplrProvider): Promise<void> {
    this.provider = provider;
    this.walletType = this.detectWalletType();

    // Enable all supported chains at once, then fetch addresses per chain
    try {
      await provider.enable(this.supportedChains);
    } catch { /* user may decline some chains */ }

    for (const chainId of this.supportedChains) {
      try {
        const key = await provider.getKey(chainId);
        this.chainId = chainId;
        this.callbacks.onWalletEvent('connect', {
          address: key.bech32Address,
          chainId,
          walletType: this.walletType,
          vm: 'cosmos',
          classification: 'hot',
        });
        // Track primary wallet as the first chain
        if (chainId === this.supportedChains[0]) {
          this.wallet = {
            address: key.bech32Address,
            chainId,
            type: this.walletType,
            vm: 'cosmos',
            classification: 'hot',
            isConnected: true,
            connectedAt: new Date().toISOString(),
          };
        }
      } catch { /* chain not enabled or not supported by wallet */ }
    }

    // Keystore change — re-fetch all chain addresses
    window.addEventListener('keplr_keystorechange', async () => {
      if (!this.provider) return;
      for (const chainId of this.supportedChains) {
        try {
          const key = await this.provider.getKey(chainId);
          this.callbacks.onWalletEvent('connect', {
            address: key.bech32Address,
            chainId,
            walletType: this.walletType,
            vm: 'cosmos',
            classification: 'hot',
          });
        } catch { /* chain not available */ }
      }
    });
  }
}
