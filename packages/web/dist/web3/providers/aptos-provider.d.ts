import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface AptosAccount {
    address: string;
    publicKey?: string;
}
interface AptosWalletProvider {
    connect(): Promise<AptosAccount>;
    disconnect(): Promise<void>;
    account(): Promise<AptosAccount>;
    isConnected(): Promise<boolean>;
    signAndSubmitTransaction?(payload: unknown): Promise<{
        hash: string;
    }>;
    signMessage?(payload: unknown): Promise<unknown>;
    onAccountChange?(callback: (account: AptosAccount | null) => void): void;
    onNetworkChange?(callback: (network: {
        name: string;
        chainId?: string;
    }) => void): void;
    network?: string;
    name?: string;
}
declare global {
    interface Window {
        petra?: AptosWalletProvider;
        pontem?: AptosWalletProvider;
        fewcha?: AptosWalletProvider;
        rise?: AptosWalletProvider;
        martian?: {
            aptos?: unknown;
            sui?: unknown;
        };
        nightly?: {
            aptos?: unknown;
            solana?: unknown;
            sui?: unknown;
        };
    }
}
export declare class AptosProvider extends BaseVMProvider {
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
