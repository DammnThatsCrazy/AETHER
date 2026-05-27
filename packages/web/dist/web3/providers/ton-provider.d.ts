import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface TONAccount {
    address: string;
    chain: string;
    walletStateInit?: string;
    publicKey?: string;
}
interface TONProvider {
    send(method: string, params?: unknown): Promise<unknown>;
    listen?(callback: (event: {
        event: string;
        payload?: unknown;
    }) => void): void;
    account?: TONAccount;
}
declare global {
    interface Window {
        ton?: TONProvider;
        tonkeeper?: TONProvider;
        __tc_bridge?: TONProvider;
    }
}
export declare class TonProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private provider;
    private network;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txHash: string): Promise<void>;
    private setupProvider;
}
export {};
