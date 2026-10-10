import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface CIP30API {
    getUsedAddresses(paginate?: {
        page: number;
        limit: number;
    }): Promise<string[]>;
    getUnusedAddresses(): Promise<string[]>;
    getChangeAddress(): Promise<string>;
    getNetworkId(): Promise<number>;
    getBalance(): Promise<string>;
    signTx?(tx: string, partialSign?: boolean): Promise<string>;
    signData?(address: string, payload: string): Promise<{
        key: string;
        signature: string;
    }>;
}
interface CIP30WalletHandle {
    enable(): Promise<CIP30API>;
    isEnabled(): Promise<boolean>;
    apiVersion: string;
    name: string;
    icon: string;
}
declare global {
    interface Window {
        cardano?: Record<string, CIP30WalletHandle>;
    }
}
export declare class CardanoProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private api;
    private walletHandle;
    private network;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txHash: string): Promise<void>;
    private setupProvider;
}
export {};
