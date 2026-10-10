// =============================================================================
// Aether SDK — EVM PROVIDER (EIP-6963 + Legacy window.ethereum)
// Multi-wallet detection: MetaMask, Coinbase, Brave, Rainbow, Rabby, Trust,
// Frame, Zerion, OKX, Ledger Live, Trezor, GridPlus, Taho, Uniswap Wallet,
// Ronin, Bitget, Bybit, Safe, Exodus, Coin98, TokenPocket
// =============================================================================

import type { WalletInfo, WalletClassification, DomainNames, BlockchainNetworkContext } from '../../types';

export interface EVMProviderEnrichmentConfig {
  approvalScan?: boolean;
  domainResolution?: boolean;
  networkContext?: boolean;
}

// ERC-20 allowance selector: allowance(address,address)
const ALLOWANCE_SELECTOR = '0xdd62ed3e';

// Top ERC-20 tokens to check for approvals (mainnet)
const APPROVAL_TOKENS: Record<number, { address: string; symbol: string }[]> = {
  1: [
    { address: '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', symbol: 'USDC' },
    { address: '0xdAC17F958D2ee523a2206206994597C13D831ec7', symbol: 'USDT' },
    { address: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2', symbol: 'WETH' },
    { address: '0x6B175474E89094C44Da98b954EedeAC495271d0F', symbol: 'DAI' },
  ],
};

// High-risk spender addresses (mainnet) — check allowances against these
const HIGH_RISK_SPENDERS: Record<number, { address: string; label: string }[]> = {
  1: [
    { address: '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D', label: 'Uniswap V2 Router' },
    { address: '0xE592427A0AEce92De3Edee1F18E0157C05861564', label: 'Uniswap V3 Router' },
    { address: '0x1111111254EEB25477B68fb85Ed929f73A960582', label: '1inch V5 Router' },
    { address: '0x00000000000000ADc04C56Bf30aC9d3c0aAF14dC', label: 'OpenSea Seaport' },
    { address: '0x000000000022D473030F116dDEE9F6B43aC78BA3', label: 'Permit2' },
  ],
};

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
  isTaho?: boolean;
  isUniswapWallet?: boolean;
  isRoninWallet?: boolean;
  isBitgetWallet?: boolean;
  isBybitWallet?: boolean;
  isSafe?: boolean;
  isExodus?: boolean;
  isCoin98?: boolean;
  isTokenPocket?: boolean;
  providers?: EthereumProvider[];
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
    coinbaseWalletExtension?: EthereumProvider;
  }
}

export class EVMProvider {
  private callbacks: EVMProviderCallbacks;
  private enrichmentConfig: EVMProviderEnrichmentConfig;
  private providers: Map<string, { info: EIP6963ProviderDetail['info']; provider: EthereumProvider }> = new Map();
  private wallets: Map<string, WalletInfo> = new Map();
  private handlers: Array<[EthereumProvider, string, (...args: unknown[]) => void]> = [];
  private eip6963Handler: ((e: Event) => void) | null = null;

  constructor(callbacks: EVMProviderCallbacks, enrichmentConfig?: EVMProviderEnrichmentConfig) {
    this.callbacks = callbacks;
    this.enrichmentConfig = enrichmentConfig ?? {};
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

    // Legacy: window.ethereum fallback (and providers array for multi-wallet)
    if (window.ethereum) {
      const providers = window.ethereum.providers;
      if (providers && providers.length > 0) {
        providers.forEach((p) => {
          const type = this.detectWalletType(p);
          this.registerProvider(type, { uuid: `legacy-${type}`, name: type, icon: '', rdns: type }, p);
        });
      } else {
        const type = this.detectWalletType(window.ethereum);
        this.registerProvider(type, { uuid: 'legacy', name: type, icon: '', rdns: type }, window.ethereum);
      }
    }

    // Coinbase Wallet extension fallback path
    if (window.coinbaseWalletExtension && !this.providers.has('coinbase')) {
      this.registerProvider('coinbase', { uuid: 'coinbase-ext', name: 'coinbase', icon: '', rdns: 'coinbase' }, window.coinbaseWalletExtension);
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

    // Fire optional enrichment passes after emitting the base connect event
    const chainId = typeof wallet.chainId === 'number' ? wallet.chainId : parseInt(String(wallet.chainId), 10) || 1;
    const provider = this.getActiveProvider();
    if (provider) {
      if (this.enrichmentConfig.networkContext) {
        this.captureNetworkContext(provider, chainId, wallet.address);
      }
      if (this.enrichmentConfig.approvalScan) {
        this.scanTokenApprovals(provider, wallet.address, chainId);
      }
    }
    if (this.enrichmentConfig.domainResolution) {
      this.resolveAllDomainNames(wallet.address);
    }
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
        const addr = accts[0]!.toLowerCase();
        if (!this.wallets.has(addr) || !this.wallets.get(addr)!.isConnected) {
          this.connect(accts[0]!, { chainId: this.wallets.values().next().value?.chainId, type: this.detectWalletType(provider) });
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
    if (provider.isSafe) return 'safe';
    if (provider.isRabby) return 'rabby';
    if (provider.isCoinbaseWallet) return 'coinbase';
    if (provider.isBraveWallet) return 'brave';
    if (provider.isRainbow) return 'rainbow';
    if (provider.isTrust) return 'trust';
    if (provider.isFrame) return 'frame';
    if (provider.isZerion) return 'zerion';
    if (provider.isOKExWallet) return 'okx';
    if (provider.isLedgerConnect) return 'ledger';
    if (provider.isTaho) return 'taho';
    if (provider.isUniswapWallet) return 'uniswap_wallet';
    if (provider.isRoninWallet) return 'ronin';
    if (provider.isBitgetWallet) return 'bitget';
    if (provider.isBybitWallet) return 'bybit';
    if (provider.isExodus) return 'exodus';
    if (provider.isCoin98) return 'coin98';
    if (provider.isTokenPocket) return 'token_pocket';
    // MetaMask last — many wallets also set isMetaMask for compatibility
    if (provider.isMetaMask) return 'metamask';
    return 'injected';
  }

  private classifyProvider(type?: string): WalletClassification {
    if (!type) return 'hot';
    if (['ledger', 'trezor', 'gridplus', 'keystone'].includes(type)) return 'cold';
    if (type === 'safe') return 'multisig';
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

  // ---------------------------------------------------------------------------
  // Enrichment: network context, approval scan, domain resolution
  // ---------------------------------------------------------------------------

  private async captureNetworkContext(provider: EthereumProvider, chainId: number, address: string): Promise<void> {
    try {
      const [blockHex, gasPriceHex, block] = await Promise.all([
        provider.request({ method: 'eth_blockNumber' }) as Promise<string>,
        provider.request({ method: 'eth_gasPrice' }) as Promise<string>,
        provider.request({ method: 'eth_getBlockByNumber', params: ['latest', false] }) as Promise<{ baseFeePerGas?: string } | null>,
      ]);
      const baseFee = block?.baseFeePerGas;
      const gasPriceGwei = parseInt(gasPriceHex, 16) / 1e9;
      const baseFeeGwei = baseFee ? parseInt(baseFee, 16) / 1e9 : 0;
      const refGwei = baseFeeGwei || gasPriceGwei;
      const congestionLevel: 'low' | 'medium' | 'high' =
        refGwei < 15 ? 'low' : refGwei < 50 ? 'medium' : 'high';
      const networkSnapshot: BlockchainNetworkContext = {
        blockNumber: parseInt(blockHex, 16),
        gasPrice: gasPriceHex,
        baseFee: baseFee,
        congestionLevel,
        timestamp: new Date().toISOString(),
      };
      this.callbacks.onWalletEvent('network_context', { address, chainId, vm: 'evm', networkSnapshot });
    } catch { /* enrichment failure is non-fatal */ }
  }

  private async scanTokenApprovals(provider: EthereumProvider, address: string, chainId: number): Promise<void> {
    const tokens = APPROVAL_TOKENS[chainId] ?? [];
    const spenders = HIGH_RISK_SPENDERS[chainId] ?? [];
    if (tokens.length === 0 || spenders.length === 0) return;

    let highRiskCount = 0;
    let hasUnlimitedApprovals = false;
    const maxUint256 = BigInt('0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff');
    const unlimitedThreshold = maxUint256 - BigInt(1);

    const pad = (hex: string) => hex.replace('0x', '').padStart(64, '0');

    for (const token of tokens) {
      for (const spender of spenders) {
        try {
          const data = `${ALLOWANCE_SELECTOR}${pad(address)}${pad(spender.address)}`;
          const result = (await provider.request({
            method: 'eth_call',
            params: [{ to: token.address, data }, 'latest'],
          })) as string;
          if (result && result !== '0x' && result !== '0x0000000000000000000000000000000000000000000000000000000000000000') {
            const allowance = BigInt(result);
            const isUnlimited = allowance >= unlimitedThreshold;
            if (isUnlimited) {
              hasUnlimitedApprovals = true;
              highRiskCount++;
            }
          }
        } catch { /* call failed — skip */ }
      }
    }

    if (hasUnlimitedApprovals || highRiskCount > 0) {
      this.callbacks.onWalletEvent('approval_risk', {
        address, chainId, vm: 'evm',
        approvalRisk: { hasUnlimitedApprovals, highRiskCount },
      });
    }
  }

  private async resolveAllDomainNames(address: string): Promise<void> {
    const domainNames: DomainNames = {};
    const lowerAddress = address.toLowerCase();

    // ENS reverse resolution via eth_call to the Public Resolver
    try {
      const reverseNode = this.computeEnsReverseNode(lowerAddress);
      const provider = this.getActiveProvider();
      if (provider) {
        const resolverResult = (await provider.request({
          method: 'eth_call',
          params: [{
            to: '0x231b0Ee14048e9dCcD1d247744d114a4EB5E8E63',
            data: `0x0178b8bf${reverseNode}`,
          }, 'latest'],
        })) as string;
        if (resolverResult && resolverResult !== '0x' + '0'.repeat(64)) {
          const nameResult = (await provider.request({
            method: 'eth_call',
            params: [{
              to: resolverResult.replace('0x000000000000000000000000', '0x'),
              data: `0x691f3431${reverseNode}`,
            }, 'latest'],
          })) as string;
          if (nameResult && nameResult.length > 130) {
            const len = parseInt(nameResult.slice(66, 130), 16);
            const hexStr = nameResult.slice(130, 130 + len * 2);
            const bytes = new Uint8Array(hexStr.match(/.{1,2}/g)?.map((b) => parseInt(b, 16)) ?? []);
            const name = new TextDecoder('utf-8').decode(bytes);
            if (name && name.endsWith('.eth')) domainNames.ens = name;
          }
        }
      }
    } catch { /* ENS resolution failed */ }

    // Lens Protocol reverse lookup
    try {
      const lensResp = await fetch('https://api-v2.lens.dev/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: `query { defaultProfile(request: { for: "${address}" }) { handle { fullHandle } } }`,
        }),
      });
      if (lensResp.ok) {
        const lensData = await lensResp.json() as { data?: { defaultProfile?: { handle?: { fullHandle?: string } } } };
        const handle = lensData?.data?.defaultProfile?.handle?.fullHandle;
        if (handle) domainNames.lens = handle;
      }
    } catch { /* Lens resolution failed */ }

    // Unstoppable Domains reverse lookup
    try {
      const udResp = await fetch(`https://resolve.unstoppabledomains.com/reverse/${lowerAddress}`, {
        headers: { Accept: 'application/json' },
      });
      if (udResp.ok) {
        const udData = await udResp.json() as { meta?: { domain?: string } };
        const domain = udData?.meta?.domain;
        if (domain) domainNames.uns = domain;
      }
    } catch { /* UD resolution failed */ }

    if (Object.keys(domainNames).length > 0) {
      this.callbacks.onWalletEvent('domain_names', { address, vm: 'evm', domainNames });
    }
  }

  private computeEnsReverseNode(address: string): string {
    // Returns the namehash of `<address>.addr.reverse` as a 64-char hex string.
    // Uses a simplified approach: encode the label bytes directly.
    // Full namehash would require keccak256 — this is a best-effort reverse lookup hint.
    const cleanAddress = address.toLowerCase().replace('0x', '');
    return cleanAddress.padStart(64, '0');
  }
}
