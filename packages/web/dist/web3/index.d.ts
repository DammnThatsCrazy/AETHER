import type { WalletInfo, TransactionOptions, ConnectedWallet } from '../types';
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
export declare class Web3Module {
    private callbacks;
    private config;
    private evmProvider;
    private svmProvider;
    private btcProvider;
    private moveProvider;
    private nearProvider;
    private tronProvider;
    private cosmosProvider;
    private evmTracker;
    private svmTracker;
    private btcTracker;
    private moveTracker;
    private nearTracker;
    private tronTracker;
    private cosmosTracker;
    private walletChangeListeners;
    constructor(callbacks: Web3Callbacks, config?: Web3ModuleConfig);
    init(): void;
    connect(address: string, options?: Partial<WalletInfo>): void;
    connectSVM(address: string, options?: Partial<WalletInfo>): void;
    connectBTC(address: string, options?: Partial<WalletInfo>): void;
    connectSUI(address: string, options?: Partial<WalletInfo>): void;
    connectNEAR(accountId: string, options?: Partial<WalletInfo>): void;
    connectTRON(address: string, options?: Partial<WalletInfo>): void;
    connectCosmos(address: string, options?: Partial<WalletInfo>): void;
    disconnect(address?: string): void;
    getInfo(): WalletInfo | null;
    transaction(txHash: string, options?: TransactionOptions): void;
    onWalletChange(callback: (wallets: ConnectedWallet[]) => void): () => void;
    destroy(): void;
    private handleWalletEvent;
    private handleTransaction;
}
