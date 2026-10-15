import type { WalletInfo } from '../../types';
export interface EVMProviderEnrichmentConfig {
    approvalScan?: boolean;
    domainResolution?: boolean;
    networkContext?: boolean;
}
export interface EVMProviderCallbacks {
    onWalletEvent: (action: string, data: Record<string, unknown>) => void;
    onTransaction: (txHash: string, data: Record<string, unknown>) => void;
}
interface EIP6963ProviderDetail {
    info: {
        uuid: string;
        name: string;
        icon: string;
        rdns: string;
    };
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
    request: (args: {
        method: string;
        params?: unknown[];
    }) => Promise<unknown>;
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
export declare class EVMProvider {
    private callbacks;
    private enrichmentConfig;
    private providers;
    private wallets;
    private handlers;
    private eip6963Handler;
    constructor(callbacks: EVMProviderCallbacks, enrichmentConfig?: EVMProviderEnrichmentConfig);
    init(): void;
    connect(address: string, options?: Partial<WalletInfo>): void;
    disconnect(address?: string): void;
    getWallets(): WalletInfo[];
    getPrimaryWallet(): WalletInfo | null;
    transaction(txHash: string, data: Record<string, unknown>): void;
    destroy(): void;
    private registerProvider;
    private detectWalletType;
    private classifyProvider;
    private getActiveProvider;
    private monitorTransaction;
    private captureNetworkContext;
    private scanTokenApprovals;
    private resolveAllDomainNames;
    private computeEnsReverseNode;
}
export {};
