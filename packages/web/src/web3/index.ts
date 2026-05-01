// =============================================================================
// Aether SDK — WEB3 MODULE (Tier 2 Thin Client)
// Simplified orchestrator: wallet detection (7 VM providers),
// connect/disconnect events, raw transaction shipping to backend.
// No DeFi classification, no portfolio aggregation, no wallet classification.
// =============================================================================

import type {
  WalletInfo, TransactionOptions, VMType, ConnectedWallet,
} from '../types';

// Providers
import { EVMProvider } from './providers/evm-provider';
import { SVMProvider } from './providers/svm-provider';
import { BitcoinProvider } from './providers/bitcoin-provider';
import { MoveProvider } from './providers/move-provider';
import { NEARProvider } from './providers/near-provider';
import { TronProvider } from './providers/tron-provider';
import { CosmosProvider } from './providers/cosmos-provider';

// Trackers (slim — raw data only)
import { EVMTracker } from './tracking/evm-tracker';
import { SVMTracker } from './tracking/svm-tracker';
import { BTCTracker } from './tracking/btc-tracker';
import { MoveTracker } from './tracking/move-tracker';
import { NEARTracker } from './tracking/near-tracker';
import { TronTracker } from './tracking/tron-tracker';
import { CosmosTracker } from './tracking/cosmos-tracker';

// =============================================================================
// Callbacks interface
// =============================================================================

export interface Web3Callbacks {
  onWalletEvent: (action: string, data: Record<string, unknown>) => void;
  onTransaction: (txHash: string, data: Record<string, unknown>) => void;
}

export interface Web3ModuleConfig {
  walletTracking?: boolean;
  svmTracking?: boolean;
  bitcoinTracking?: boolean;
  moveTracking?: boolean;
  nearTracking?: boolean;
  tronTracking?: boolean;
  cosmosTracking?: boolean;
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

  // Trackers (slim)
  private evmTracker: EVMTracker | null = null;
  private svmTracker: SVMTracker | null = null;
  private btcTracker: BTCTracker | null = null;
  private moveTracker: MoveTracker | null = null;
  private nearTracker: NEARTracker | null = null;
  private tronTracker: TronTracker | null = null;
  private cosmosTracker: CosmosTracker | null = null;

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

    const trackerCallbacks = {
      onTransaction: (txHash: string, data: Record<string, unknown>) =>
        this.callbacks.onTransaction(txHash, data),
    };

    // EVM
    if (cfg.walletTracking !== false) {
      this.evmProvider = new EVMProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('evm', action, data),
        onTransaction: (hash, data) => this.handleTransaction('evm', hash, data),
      });
      this.evmProvider.init();
      this.evmTracker = new EVMTracker(trackerCallbacks);
    }

    // Solana
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
      this.btcTracker = new BTCTracker(trackerCallbacks);
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
  }

  // =========================================================================
  // PUBLIC API
  // =========================================================================

  connect(address: string, options?: Partial<WalletInfo>): void {
    this.evmProvider?.connect(address, options);
  }

  connectSVM(address: string, options?: Partial<WalletInfo>): void {
    this.svmProvider?.connect(address, options);
  }

  connectBTC(address: string, options?: Partial<WalletInfo>): void {
    this.btcProvider?.connect(address, options);
  }

  connectSUI(address: string, options?: Partial<WalletInfo>): void {
    this.moveProvider?.connect(address, options);
  }

  connectNEAR(accountId: string, options?: Partial<WalletInfo>): void {
    this.nearProvider?.connect(accountId, options);
  }

  connectTRON(address: string, options?: Partial<WalletInfo>): void {
    this.tronProvider?.connect(address, options);
  }

  connectCosmos(address: string, options?: Partial<WalletInfo>): void {
    this.cosmosProvider?.connect(address, options);
  }

  disconnect(address?: string): void {
    if (address) {
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

  onWalletChange(callback: (wallets: ConnectedWallet[]) => void): () => void {
    this.walletChangeListeners.push(callback);
    return () => {
      this.walletChangeListeners = this.walletChangeListeners.filter((l) => l !== callback);
    };
  }

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
  }

  // =========================================================================
  // PRIVATE — Event routing (raw data, no enrichment)
  // =========================================================================

  private handleWalletEvent(vm: VMType, action: string, data: Record<string, unknown>): void {
    this.callbacks.onWalletEvent(action, { ...data, vm });
  }

  private handleTransaction(vm: VMType, txHash: string, data: Record<string, unknown>): void {
    this.callbacks.onTransaction(txHash, { ...data, vm });
  }
}
