import type { WalletInfo } from '../../types';
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
    }
}
export declare class EVMProvider {
    private callbacks;
    private providers;
    private wallets;
    private handlers;
    private eip6963Handler;
    constructor(callbacks: EVMProviderCallbacks);
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
}
export {};
