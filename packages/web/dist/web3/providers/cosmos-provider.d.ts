import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface KeplrProvider {
    enable(chainId: string | string[]): Promise<void>;
    getKey(chainId: string): Promise<{
        bech32Address: string;
        name: string;
        algo: string;
        pubKey: Uint8Array;
    }>;
    signAmino?(chainId: string, signer: string, signDoc: unknown): Promise<unknown>;
    signDirect?(chainId: string, signer: string, signDoc: unknown): Promise<unknown>;
    experimentalSuggestChain?(chainInfo: unknown): Promise<void>;
}
export interface CosmosProviderConfig {
    supportedChains?: string[];
}
declare global {
    interface Window {
        keplr?: KeplrProvider;
        leap?: KeplrProvider;
        cosmostation?: {
            providers?: {
                keplr?: KeplrProvider;
            };
        };
        station?: KeplrProvider;
    }
}
export declare class CosmosProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private provider;
    private chainId;
    private supportedChains;
    constructor(callbacks: ProviderCallbacks, config?: CosmosProviderConfig);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txHash: string): Promise<void>;
    private setupProvider;
}
export {};
