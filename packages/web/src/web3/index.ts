// =============================================================================
// AETHER SDK — WEB3 MODULE (MULTI-VM ORCHESTRATOR)
// Coordinates 7 VM providers, 7 VM trackers, 14 DeFi trackers,
// wallet classification, and portfolio aggregation
// =============================================================================

import type {
  WalletInfo, TransactionOptions, VMType, ConnectedWallet,
  PortfolioSnapshot, WalletClassification, TokenBalance, NFTAsset,
  DeFiPosition, WhaleAlert, GasAnalytics,
} from '../types';

// Providers
import { EVMProvider } from './providers/evm-provider';
import { SVMProvider } from './providers/svm-provider';
import { BitcoinProvider } from './providers/bitcoin-provider';
import { MoveProvider } from './providers/move-provider';
import { NEARProvider } from './providers/near-provider';
import { TronProvider } from './providers/tron-provider';
import { CosmosProvider } from './providers/cosmos-provider';

// Trackers
import { EVMTracker } from './tracking/evm-tracker';
import { SVMTracker } from './tracking/svm-tracker';
import { BTCTracker } from './tracking/btc-tracker';
import { MoveTracker } from './tracking/move-tracker';
import { NEARTracker } from './tracking/near-tracker';
import { TronTracker } from './tracking/tron-tracker';
import { CosmosTracker } from './tracking/cosmos-tracker';

// DeFi
import { DexTracker } from './defi/dex-tracker';
import { identifyProtocol } from './defi/protocol-registry';

// Wallet
import { classifyWallet } from './wallet/wallet-classifier';

// Portfolio
import { PortfolioTracker } from './portfolio/portfolio-tracker';

// =============================================================================
// Callbacks interface
// =============================================================================

export interface Web3Callbacks {
  onWalletEvent: (action: string, data: Record<string, unknown>) => void;
  onTransaction: (txHash: string, data: Record<string, unknown>) => void;
  onTokenBalance?: (balance: TokenBalance) => void;
  onNFTDetected?: (nft: NFTAsset) => void;
  onGasAnalytics?: (gas: GasAnalytics) => void;
  onWhaleAlert?: (alert: WhaleAlert) => void;
  onDeFiInteraction?: (data: Record<string, unknown>) => void;
  onPortfolioUpdate?: (snapshot: PortfolioSnapshot) => void;
}

export interface Web3ModuleConfig {
  // VM enables
  walletTracking?: boolean;
  svmTracking?: boolean;
  bitcoinTracking?: boolean;
  moveTracking?: boolean;
  nearTracking?: boolean;
  tronTracking?: boolean;
  cosmosTracking?: boolean;
  // Feature enables
  tokenTracking?: boolean;
  nftDetection?: boolean;
  gasTracking?: boolean;
  whaleAlerts?: boolean;
  defiTracking?: boolean;
  portfolioTracking?: boolean;
  walletClassification?: boolean;
  perpetualsTracking?: boolean;
  bridgeTracking?: boolean;
  cexTracking?: boolean;
  // Thresholds
  whaleThresholdETH?: number;
  whaleThresholdBTC?: number;
}

// =============================================================================
// Main Web3Module class
// =============================================================================

export class Web3Module {
  private callbacks: Web3Callbacks;
  private config: Web3ModuleConfig;

  // Providers
  private evmProvider: EVMProvider | null = null;
  private svmProvider: SVMProvider | null = null;
  private btcProvider: BitcoinProvider | null = null;
  private moveProvider: MoveProvider | null = null;
  private nearProvider: NEARProvider | null = null;
  private tronProvider: TronProvider | null = null;
  private cosmosProvider: CosmosProvider | null = null;

  // Trackers
  private evmTracker: EVMTracker | null = null;
  private svmTracker: SVMTracker | null = null;
  private btcTracker: BTCTracker | null = null;
  private moveTracker: MoveTracker | null = null;
  private nearTracker: NEARTracker | null = null;
  private tronTracker: TronTracker | null = null;
  private cosmosTracker: CosmosTracker | null = null;

  // DeFi
  private dexTracker: DexTracker | null = null;

  // Portfolio
  private portfolio: PortfolioTracker | null = null;

  // Wallet change listeners
  private walletChangeListeners: ((wallets: ConnectedWallet[]) => void)[] = [];

  constructor(callbacks: Web3Callbacks, config?: Web3ModuleConfig) {
    this.callbacks = callbacks;
    this.config = config ?? {};
  }

  // =========================================================================
  // INITIALIZATION
  // =========================================================================

  init(): void {
    const cfg = this.config;

    // Tracker callbacks (shared across VMs)
    const trackerCallbacks = {
      onTokenBalance: (b: TokenBalance) => this.callbacks.onTokenBalance?.(b),
      onNFTDetected: (n: NFTAsset) => this.callbacks.onNFTDetected?.(n),
      onGasAnalytics: (g: GasAnalytics) => this.callbacks.onGasAnalytics?.(g),
      onWhaleAlert: (a: WhaleAlert) => this.callbacks.onWhaleAlert?.(a),
      onDeFiInteraction: (d: Record<string, unknown>) => this.callbacks.onDeFiInteraction?.(d),
      onProgramInteraction: (d: Record<string, unknown>) => this.callbacks.onDeFiInteraction?.(d),
      onInscriptionDetected: (d: Record<string, unknown>) => this.callbacks.onDeFiInteraction?.(d),
      onUTXOUpdate: (d: Record<string, unknown>) => this.callbacks.onDeFiInteraction?.(d),
      onActionDetected: (d: Record<string, unknown>) => this.callbacks.onDeFiInteraction?.(d),
      onMoveCall: (d: Record<string, unknown>) => this.callbacks.onDeFiInteraction?.(d),
      onIBCTransfer: (d: Record<string, unknown>) => this.callbacks.onDeFiInteraction?.(d),
      onGovernanceAction: (d: Record<string, unknown>) => this.callbacks.onDeFiInteraction?.(d),
    };

    // EVM (always if walletTracking enabled)
    if (cfg.walletTracking !== false) {
      this.evmProvider = new EVMProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('evm', action, data),
        onTransaction: (hash, data) => this.handleTransaction('evm', hash, data),
      });
      this.evmProvider.init();

      this.evmTracker = new EVMTracker(trackerCallbacks, {
        whaleThresholdETH: cfg.whaleThresholdETH,
        enableTokenTracking: cfg.tokenTracking,
        enableNFTDetection: cfg.nftDetection,
        enableGasAnalytics: cfg.gasTracking,
        enableWhaleAlerts: cfg.whaleAlerts,
      });
    }

    // Solana (SVM)
    if (cfg.svmTracking) {
      this.svmProvider = new SVMProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('svm', action, data),
        onTransaction: (sig, data) => this.handleTransaction('svm', sig, data),
      });
      this.svmProvider.init();
      this.svmTracker = new SVMTracker(trackerCallbacks);
    }

    // Bitcoin
    if (cfg.bitcoinTracking) {
      this.btcProvider = new BitcoinProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('bitcoin', action, data),
        onTransaction: (txid, data) => this.handleTransaction('bitcoin', txid, data),
      });
      this.btcProvider.init();
      this.btcTracker = new BTCTracker(trackerCallbacks, { whaleThresholdBTC: cfg.whaleThresholdBTC });
    }

    // SUI (Move VM)
    if (cfg.moveTracking) {
      this.moveProvider = new MoveProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('movevm', action, data),
        onTransaction: (digest, data) => this.handleTransaction('movevm', digest, data),
      });
      this.moveProvider.init();
      this.moveTracker = new MoveTracker(trackerCallbacks);
    }

    // NEAR
    if (cfg.nearTracking) {
      this.nearProvider = new NEARProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('near', action, data),
        onTransaction: (hash, data) => this.handleTransaction('near', hash, data),
      });
      this.nearProvider.init();
      this.nearTracker = new NEARTracker(trackerCallbacks);
    }

    // TRON
    if (cfg.tronTracking) {
      this.tronProvider = new TronProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('tvm', action, data),
        onTransaction: (txid, data) => this.handleTransaction('tvm', txid, data),
      });
      this.tronProvider.init();
      this.tronTracker = new TronTracker(trackerCallbacks);
    }

    // Cosmos / SEI
    if (cfg.cosmosTracking) {
      this.cosmosProvider = new CosmosProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('cosmos', action, data),
        onTransaction: (hash, data) => this.handleTransaction('cosmos', hash, data),
      });
      this.cosmosProvider.init();
      this.cosmosTracker = new CosmosTracker(trackerCallbacks);
    }

    // DeFi tracking
    if (cfg.defiTracking) {
      this.dexTracker = new DexTracker({
        onSwap: (d) => this.callbacks.onDeFiInteraction?.(d),
        onLiquidityChange: (d) => this.callbacks.onDeFiInteraction?.(d),
        onPoolInteraction: (d) => this.callbacks.onDeFiInteraction?.(d),
      });
    }

    // Portfolio tracking
    if (cfg.portfolioTracking) {
      this.portfolio = new PortfolioTracker({
        onPortfolioUpdate: (s) => this.callbacks.onPortfolioUpdate?.(s),
        onWalletAdded: () => this.notifyWalletChange(),
        onWalletRemoved: () => this.notifyWalletChange(),
      });
    }
  }

  // =========================================================================
  // PUBLIC API — Backwards compatible + new multi-VM methods
  // =========================================================================

  /** Connect an EVM wallet (backwards compatible) */
  connect(address: string, options?: Partial<WalletInfo>): void {
    if (this.evmProvider) {
      this.evmProvider.connect(address, options);
    }
  }

  /** Connect a Solana wallet */
  connectSVM(address: string, options?: Partial<WalletInfo>): void {
    this.svmProvider?.connect(address, options);
  }

  /** Connect a Bitcoin wallet */
  connectBTC(address: string, options?: Partial<WalletInfo>): void {
    this.btcProvider?.connect(address, options);
  }

  /** Connect a SUI wallet */
  connectSUI(address: string, options?: Partial<WalletInfo>): void {
    this.moveProvider?.connect(address, options);
  }

  /** Connect a NEAR wallet */
  connectNEAR(accountId: string, options?: Partial<WalletInfo>): void {
    this.nearProvider?.connect(accountId, options);
  }

  /** Connect a TRON wallet */
  connectTRON(address: string, options?: Partial<WalletInfo>): void {
    this.tronProvider?.connect(address, options);
  }

  /** Connect a Cosmos/SEI wallet */
  connectCosmos(address: string, options?: Partial<WalletInfo>): void {
    this.cosmosProvider?.connect(address, options);
  }

  /** Disconnect a wallet (or all wallets if no address) */
  disconnect(address?: string): void {
    if (address) {
      // Try to find which provider owns this address
      this.evmProvider?.disconnect(address);
      this.svmProvider?.disconnect();
      this.btcProvider?.disconnect();
      this.moveProvider?.disconnect();
      this.nearProvider?.disconnect();
      this.tronProvider?.disconnect();
      this.cosmosProvider?.disconnect();
    } else {
      this.evmProvider?.disconnect();
      this.svmProvider?.disconnect();
      this.btcProvider?.disconnect();
      this.moveProvider?.disconnect();
      this.nearProvider?.disconnect();
      this.tronProvider?.disconnect();
      this.cosmosProvider?.disconnect();
    }
  }

  /** Get primary wallet info (backwards compatible) */
  getInfo(): WalletInfo | null {
    return this.evmProvider?.getPrimaryWallet()
      ?? this.svmProvider?.getWallet()
      ?? this.btcProvider?.getWallet()
      ?? this.moveProvider?.getWallet()
      ?? this.nearProvider?.getWallet()
      ?? this.tronProvider?.getWallet()
      ?? this.cosmosProvider?.getWallet()
      ?? null;
  }

  /** Get all connected wallets across all VMs */
  getWallets(): ConnectedWallet[] {
    return this.portfolio?.getWallets() ?? [];
  }

  /** Get wallets filtered by VM */
  getWalletsByVM(vm: VMType): ConnectedWallet[] {
    return this.portfolio?.getWalletsByVM(vm) ?? [];
  }

  /** Track a transaction */
  transaction(txHash: string, options?: TransactionOptions): void {
    const vm = options?.vm ?? 'evm';
    switch (vm) {
      case 'evm': this.evmProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'svm': this.svmProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'bitcoin': this.btcProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'movevm': this.moveProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'near': this.nearProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'tvm': this.tronProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'cosmos': this.cosmosProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
    }
  }

  /** Get cross-chain portfolio */
  getPortfolio(): PortfolioSnapshot | null {
    return this.portfolio?.getPortfolio() ?? null;
  }

  /** Register wallet change callback */
  onWalletChange(callback: (wallets: ConnectedWallet[]) => void): () => void {
    this.walletChangeListeners.push(callback);
    return () => {
      this.walletChangeListeners = this.walletChangeListeners.filter((l) => l !== callback);
    };
  }

  /** Classify a wallet address */
  classifyWalletAddress(address: string, vm: VMType, chainId?: number | string): WalletClassification {
    return classifyWallet(address, vm, chainId ?? 1);
  }

  /** Identify a DeFi protocol by contract address */
  identifyDeFiProtocol(chainId: number | string, contractAddress: string) {
    return identifyProtocol(chainId, contractAddress);
  }

  /** Destroy all providers and trackers */
  destroy(): void {
    this.evmProvider?.destroy();
    this.svmProvider?.destroy();
    this.btcProvider?.destroy();
    this.moveProvider?.destroy();
    this.nearProvider?.destroy();
    this.tronProvider?.destroy();
    this.cosmosProvider?.destroy();

    this.evmTracker?.destroy();
    this.svmTracker?.destroy();
    this.btcTracker?.destroy();
    this.moveTracker?.destroy();
    this.nearTracker?.destroy();
    this.tronTracker?.destroy();
    this.cosmosTracker?.destroy();

    this.dexTracker?.destroy();
    this.portfolio?.destroy();

    this.walletChangeListeners = [];

    this.evmProvider = null;
    this.svmProvider = null;
    this.btcProvider = null;
    this.moveProvider = null;
    this.nearProvider = null;
    this.tronProvider = null;
    this.cosmosProvider = null;
    this.evmTracker = null;
    this.svmTracker = null;
    this.btcTracker = null;
    this.moveTracker = null;
    this.nearTracker = null;
    this.tronTracker = null;
    this.cosmosTracker = null;
    this.dexTracker = null;
    this.portfolio = null;
  }

  // =========================================================================
  // PRIVATE — Event routing
  // =========================================================================

  private handleWalletEvent(vm: VMType, action: string, data: Record<string, unknown>): void {
    // Add VM tag and classification
    const enriched = {
      ...data,
      vm,
      classification: this.config.walletClassification
        ? classifyWallet(data.address as string, vm, data.chainId as number | string)
        : undefined,
    };

    this.callbacks.onWalletEvent(action, enriched);

    // Update portfolio
    if (this.portfolio && action === 'connect' && data.address) {
      this.portfolio.addWallet(
        PortfolioTracker.createWallet(
          data.address as string, vm,
          data.chainId as number | string ?? 1,
          data.walletType as string ?? 'unknown',
          enriched.classification ?? 'hot',
          { ens: data.ens as string, isPrimary: this.portfolio.getWallets().length === 0 }
        )
      );
    } else if (this.portfolio && action === 'disconnect' && data.address) {
      this.portfolio.removeWallet(data.address as string, vm);
    }
  }

  private handleTransaction(vm: VMType, txHash: string, data: Record<string, unknown>): void {
    // Enrich with VM tag
    const enriched = { ...data, vm };
    this.callbacks.onTransaction(txHash, enriched);

    // Route to DeFi tracker for classification
    if (this.dexTracker && data.to) {
      this.dexTracker.detectSwap({
        hash: txHash, to: data.to as string,
        chainId: data.chainId as number | string ?? 1,
        vm, input: data.input as string, value: data.value as string,
      });
    }
  }

  private notifyWalletChange(): void {
    const wallets = this.getWallets();
    this.walletChangeListeners.forEach((l) => { try { l(wallets); } catch { /* */ } });
  }
}
