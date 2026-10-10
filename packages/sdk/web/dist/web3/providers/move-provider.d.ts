import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface SuiWalletProvider {
    hasPermissions?(): Promise<boolean>;
    requestPermissions?(): Promise<boolean>;
    getAccounts?(): Promise<{
        address: string;
    }[]>;
    signAndExecuteTransactionBlock?(input: unknown): Promise<{
        digest: string;
    }>;
    signMessage?(input: {
        message: Uint8Array;
    }): Promise<{
        signature: string;
    }>;
    on?(event: string, handler: (...args: unknown[]) => void): void;
    off?(event: string, handler: (...args: unknown[]) => void): void;
    features?: Record<string, unknown>;
    name?: string;
}
declare global {
    interface Window {
        suiWallet?: SuiWalletProvider;
        ethosWallet?: SuiWalletProvider;
        martian?: {
            aptos?: unknown;
            sui?: unknown;
        };
        surfWallet?: SuiWalletProvider;
        suiet?: SuiWalletProvider;
        nightly?: {
            aptos?: unknown;
            solana?: unknown;
            sui?: unknown;
        };
    }
}
export declare class MoveProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private provider;
    private network;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(digest: string): Promise<void>;
    private setupProvider;
}
export {};
