import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface NEARWalletProvider {
    accountId?: string;
    isSignedIn?(): boolean;
    getAccountId?(): string;
    signIn?(opts?: {
        contractId?: string;
    }): Promise<void>;
    signOut?(): Promise<void>;
    signAndSendTransaction?(params: unknown): Promise<{
        transaction: {
            hash: string;
        };
    }>;
    on?(event: string, handler: (...args: unknown[]) => void): void;
}
declare global {
    interface Window {
        near?: NEARWalletProvider;
        myNearWallet?: NEARWalletProvider;
        meteorWallet?: NEARWalletProvider;
    }
}
export declare class NEARProvider extends BaseVMProvider {
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
