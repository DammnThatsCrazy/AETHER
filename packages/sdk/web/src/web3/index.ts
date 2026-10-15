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
import { AptosProvider } from './providers/aptos-provider';
import { TonProvider } from './providers/ton-provider';
import { StarknetProvider } from './providers/starknet-provider';
import { CardanoProvider } from './providers/cardano-provider';
import { SubstrateProvider } from './providers/substrate-provider';
import { AlgorandProvider } from './providers/algorand-provider';
import { HederaProvider } from './providers/hedera-provider';
import { StellarProvider } from './providers/stellar-provider';
import { ICPProvider } from './providers/icp-provider';

// Trackers (slim — raw data only)
import { EVMTracker } from './tracking/evm-tracker';
import { SVMTracker } from './tracking/svm-tracker';
import { BTCTracker } from './tracking/btc-tracker';
import { MoveTracker } from './tracking/move-tracker';
import { NEARTracker } from './tracking/near-tracker';
import { TronTracker } from './tracking/tron-tracker';
import { CosmosTracker } from './tracking/cosmos-tracker';
import { AptosTracker } from './tracking/aptos-tracker';
import { TonTracker } from './tracking/ton-tracker';
import { StarknetTracker } from './tracking/starknet-tracker';
import { CardanoTracker } from './tracking/cardano-tracker';
import { SubstrateTracker } from './tracking/substrate-tracker';
import { AlgorandTracker } from './tracking/algorand-tracker';
import { HederaTracker } from './tracking/hedera-tracker';
import { StellarTracker } from './tracking/stellar-tracker';
import { ICPTracker } from './tracking/icp-tracker';

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
  aptosTracking?: boolean;
  tonTracking?: boolean;
  starknetTracking?: boolean;
  cardanoTracking?: boolean;
  substrateTracking?: boolean;
  algorandTracking?: boolean;
  hederaTracking?: boolean;
  stellarTracking?: boolean;
  icpTracking?: boolean;
  cosmosChains?: string[];
  approvalScan?: boolean;
  domainResolution?: boolean;
  networkContext?: boolean;
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
  private aptosProvider: AptosProvider | null = null;
  private tonProvider: TonProvider | null = null;
  private starknetProvider: StarknetProvider | null = null;
  private cardanoProvider: CardanoProvider | null = null;
  private substrateProvider: SubstrateProvider | null = null;
  private algorandProvider: AlgorandProvider | null = null;
  private hederaProvider: HederaProvider | null = null;
  private stellarProvider: StellarProvider | null = null;
  private icpProvider: ICPProvider | null = null;

  // Trackers (slim)
  private evmTracker: EVMTracker | null = null;
  private svmTracker: SVMTracker | null = null;
  private btcTracker: BTCTracker | null = null;
  private moveTracker: MoveTracker | null = null;
  private nearTracker: NEARTracker | null = null;
  private tronTracker: TronTracker | null = null;
  private cosmosTracker: CosmosTracker | null = null;
  private aptosTracker: AptosTracker | null = null;
  private tonTracker: TonTracker | null = null;
  private starknetTracker: StarknetTracker | null = null;
  private cardanoTracker: CardanoTracker | null = null;
  private substrateTracker: SubstrateTracker | null = null;
  private algorandTracker: AlgorandTracker | null = null;
  private hederaTracker: HederaTracker | null = null;
  private stellarTracker: StellarTracker | null = null;
  private icpTracker: ICPTracker | null = null;

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
      }, {
        approvalScan: cfg.approvalScan,
        domainResolution: cfg.domainResolution,
        networkContext: cfg.networkContext,
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

    // Cosmos / multi-chain
    if (cfg.cosmosTracking) {
      this.cosmosProvider = new CosmosProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('cosmos', action, data),
        onTransaction: (hash, data) => this.handleTransaction('cosmos', hash, data),
      }, { supportedChains: cfg.cosmosChains });
      this.cosmosProvider.init();
      this.cosmosTracker = new CosmosTracker(trackerCallbacks);
    }

    // Aptos
    if (cfg.aptosTracking) {
      this.aptosProvider = new AptosProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('aptos', action, data),
        onTransaction: (hash, data) => this.handleTransaction('aptos', hash, data),
      });
      this.aptosProvider.init();
      this.aptosTracker = new AptosTracker(trackerCallbacks);
    }

    // TON
    if (cfg.tonTracking) {
      this.tonProvider = new TonProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('ton', action, data),
        onTransaction: (hash, data) => this.handleTransaction('ton', hash, data),
      });
      this.tonProvider.init();
      this.tonTracker = new TonTracker(trackerCallbacks);
    }

    // Starknet
    if (cfg.starknetTracking) {
      this.starknetProvider = new StarknetProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('starknet', action, data),
        onTransaction: (hash, data) => this.handleTransaction('starknet', hash, data),
      });
      this.starknetProvider.init();
      this.starknetTracker = new StarknetTracker(trackerCallbacks);
    }

    // Cardano
    if (cfg.cardanoTracking) {
      this.cardanoProvider = new CardanoProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('cardano', action, data),
        onTransaction: (hash, data) => this.handleTransaction('cardano', hash, data),
      });
      this.cardanoProvider.init();
      this.cardanoTracker = new CardanoTracker(trackerCallbacks);
    }

    // Polkadot / Substrate
    if (cfg.substrateTracking) {
      this.substrateProvider = new SubstrateProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('substrate', action, data),
        onTransaction: (hash, data) => this.handleTransaction('substrate', hash, data),
      });
      this.substrateProvider.init();
      this.substrateTracker = new SubstrateTracker(trackerCallbacks);
    }

    // Algorand
    if (cfg.algorandTracking) {
      this.algorandProvider = new AlgorandProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('algorand', action, data),
        onTransaction: (txId, data) => this.handleTransaction('algorand', txId, data),
      });
      this.algorandProvider.init();
      this.algorandTracker = new AlgorandTracker(trackerCallbacks);
    }

    // Hedera
    if (cfg.hederaTracking) {
      this.hederaProvider = new HederaProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('hedera', action, data),
        onTransaction: (txId, data) => this.handleTransaction('hedera', txId, data),
      });
      this.hederaProvider.init();
      this.hederaTracker = new HederaTracker(trackerCallbacks);
    }

    // Stellar
    if (cfg.stellarTracking) {
      this.stellarProvider = new StellarProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('stellar', action, data),
        onTransaction: (hash, data) => this.handleTransaction('stellar', hash, data),
      });
      this.stellarProvider.init();
      this.stellarTracker = new StellarTracker(trackerCallbacks);
    }

    // ICP
    if (cfg.icpTracking) {
      this.icpProvider = new ICPProvider({
        onWalletEvent: (action, data) => this.handleWalletEvent('icp', action, data),
        onTransaction: (blockIndex, data) => this.handleTransaction('icp', blockIndex, data),
      });
      this.icpProvider.init();
      this.icpTracker = new ICPTracker(trackerCallbacks);
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

  connectAptos(address: string, options?: Partial<WalletInfo>): void {
    this.aptosProvider?.connect(address, options);
  }

  connectTON(address: string, options?: Partial<WalletInfo>): void {
    this.tonProvider?.connect(address, options);
  }

  connectStarknet(address: string, options?: Partial<WalletInfo>): void {
    this.starknetProvider?.connect(address, options);
  }

  connectCardano(address: string, options?: Partial<WalletInfo>): void {
    this.cardanoProvider?.connect(address, options);
  }

  connectSubstrate(address: string, options?: Partial<WalletInfo>): void {
    this.substrateProvider?.connect(address, options);
  }

  connectAlgorand(address: string, options?: Partial<WalletInfo>): void {
    this.algorandProvider?.connect(address, options);
  }

  connectHedera(address: string, options?: Partial<WalletInfo>): void {
    this.hederaProvider?.connect(address, options);
  }

  connectStellar(address: string, options?: Partial<WalletInfo>): void {
    this.stellarProvider?.connect(address, options);
  }

  connectICP(principal: string, options?: Partial<WalletInfo>): void {
    this.icpProvider?.connect(principal, options);
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
      this.aptosProvider?.disconnect();
      this.tonProvider?.disconnect();
      this.starknetProvider?.disconnect();
      this.cardanoProvider?.disconnect();
      this.substrateProvider?.disconnect();
      this.algorandProvider?.disconnect();
      this.hederaProvider?.disconnect();
      this.stellarProvider?.disconnect();
      this.icpProvider?.disconnect();
    } else {
      this.evmProvider?.disconnect();
      this.svmProvider?.disconnect();
      this.btcProvider?.disconnect();
      this.moveProvider?.disconnect();
      this.nearProvider?.disconnect();
      this.tronProvider?.disconnect();
      this.cosmosProvider?.disconnect();
      this.aptosProvider?.disconnect();
      this.tonProvider?.disconnect();
      this.starknetProvider?.disconnect();
      this.cardanoProvider?.disconnect();
      this.substrateProvider?.disconnect();
      this.algorandProvider?.disconnect();
      this.hederaProvider?.disconnect();
      this.stellarProvider?.disconnect();
      this.icpProvider?.disconnect();
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
      ?? this.aptosProvider?.getWallet()
      ?? this.tonProvider?.getWallet()
      ?? this.starknetProvider?.getWallet()
      ?? this.cardanoProvider?.getWallet()
      ?? this.substrateProvider?.getWallet()
      ?? this.algorandProvider?.getWallet()
      ?? this.hederaProvider?.getWallet()
      ?? this.stellarProvider?.getWallet()
      ?? this.icpProvider?.getWallet()
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
      case 'aptos': this.aptosProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'ton': this.tonProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'starknet': this.starknetProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'cardano': this.cardanoProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'substrate': this.substrateProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'algorand': this.algorandProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'hedera': this.hederaProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'stellar': this.stellarProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
      case 'icp': this.icpProvider?.transaction(txHash, options as Record<string, unknown> ?? {}); break;
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
    this.aptosProvider?.destroy();
    this.tonProvider?.destroy();
    this.starknetProvider?.destroy();
    this.cardanoProvider?.destroy();
    this.substrateProvider?.destroy();
    this.algorandProvider?.destroy();
    this.hederaProvider?.destroy();
    this.stellarProvider?.destroy();
    this.icpProvider?.destroy();

    this.evmTracker?.destroy();
    this.svmTracker?.destroy();
    this.btcTracker?.destroy();
    this.moveTracker?.destroy();
    this.nearTracker?.destroy();
    this.tronTracker?.destroy();
    this.cosmosTracker?.destroy();
    this.aptosTracker?.destroy();
    this.tonTracker?.destroy();
    this.starknetTracker?.destroy();
    this.cardanoTracker?.destroy();
    this.substrateTracker?.destroy();
    this.algorandTracker?.destroy();
    this.hederaTracker?.destroy();
    this.stellarTracker?.destroy();
    this.icpTracker?.destroy();

    this.walletChangeListeners = [];

    this.evmProvider = null;
    this.svmProvider = null;
    this.btcProvider = null;
    this.moveProvider = null;
    this.nearProvider = null;
    this.tronProvider = null;
    this.cosmosProvider = null;
    this.aptosProvider = null;
    this.tonProvider = null;
    this.starknetProvider = null;
    this.cardanoProvider = null;
    this.substrateProvider = null;
    this.algorandProvider = null;
    this.hederaProvider = null;
    this.stellarProvider = null;
    this.icpProvider = null;
    this.evmTracker = null;
    this.svmTracker = null;
    this.btcTracker = null;
    this.moveTracker = null;
    this.nearTracker = null;
    this.tronTracker = null;
    this.cosmosTracker = null;
    this.aptosTracker = null;
    this.tonTracker = null;
    this.starknetTracker = null;
    this.cardanoTracker = null;
    this.substrateTracker = null;
    this.algorandTracker = null;
    this.hederaTracker = null;
    this.stellarTracker = null;
    this.icpTracker = null;
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
