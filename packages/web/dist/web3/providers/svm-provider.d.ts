import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface SolanaProvider {
    isPhantom?: boolean;
    isSolflare?: boolean;
    isBackpack?: boolean;
    isGlow?: boolean;
    publicKey?: {
        toString(): string;
        toBase58(): string;
    };
    isConnected?: boolean;
    connect(opts?: {
        onlyIfTrusted?: boolean;
    }): Promise<{
        publicKey: {
            toString(): string;
        };
    }>;
    disconnect(): Promise<void>;
    signTransaction?(tx: unknown): Promise<unknown>;
    signAllTransactions?(txs: unknown[]): Promise<unknown[]>;
    signMessage?(message: Uint8Array): Promise<{
        signature: Uint8Array;
    }>;
    on(event: string, handler: (...args: unknown[]) => void): void;
    off?(event: string, handler: (...args: unknown[]) => void): void;
    removeListener?(event: string, handler: (...args: unknown[]) => void): void;
}
declare global {
    interface Window {
        solana?: SolanaProvider;
        phantom?: {
            solana?: SolanaProvider;
        };
        solflare?: SolanaProvider;
        backpack?: {
            solana?: SolanaProvider;
        };
        glow?: SolanaProvider;
    }
}
export declare class SVMProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private provider;
    private cluster;
    private handlers;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(signature: string): Promise<void>;
    private setupProvider;
    private getRpcUrl;
}
export {};
