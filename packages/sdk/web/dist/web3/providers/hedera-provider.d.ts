import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface HederaWallet {
    pairingData?: {
        accountIds: string[];
        network: string;
    };
    sendRequest?(message: unknown): Promise<unknown>;
}
interface BladeWallet {
    getAccountId(): Promise<string>;
    getAccountInfo(accountId: string): Promise<unknown>;
    sendRequest?(method: string, params?: unknown): Promise<unknown>;
}
declare global {
    interface Window {
        hashpack?: HederaWallet;
        bladeWallet?: BladeWallet;
    }
}
export declare class HederaProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private network;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txId: string): Promise<void>;
    private setupHashPack;
    private setupBlade;
}
export {};
