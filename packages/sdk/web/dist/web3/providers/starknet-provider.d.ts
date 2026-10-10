import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface StarknetAccount {
    address: string;
    signer?: {
        pk?: string;
    };
}
interface StarknetWallet {
    id?: string;
    name?: string;
    version?: string;
    isConnected?: boolean;
    account?: StarknetAccount;
    selectedAddress?: string;
    chainId?: string;
    enable(options?: {
        starknetVersion?: string;
    }): Promise<string[]>;
    request(call: {
        type: string;
        params?: unknown;
    }): Promise<unknown>;
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
export declare class StarknetProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private provider;
    private network;
    private announceHandler;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txHash: string): Promise<void>;
    private setupProvider;
}
export {};
