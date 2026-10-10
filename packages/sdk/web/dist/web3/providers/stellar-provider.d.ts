import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface FreighterAPI {
    getPublicKey(): Promise<string>;
    isConnected(): Promise<boolean>;
    getNetwork(): Promise<string>;
    getNetworkDetails(): Promise<{
        network: string;
        networkUrl: string;
        networkPassphrase: string;
    }>;
    signTransaction(xdr: string, opts?: {
        network?: string;
        networkPassphrase?: string;
    }): Promise<string>;
}
interface XBullAPI {
    connect(opts?: {
        canRequestPublicKey?: boolean;
    }): Promise<{
        message?: string;
    }>;
    getPublicKey(): Promise<string>;
}
declare global {
    interface Window {
        freighter?: FreighterAPI;
        xBullSDK?: XBullAPI;
        rabet?: {
            connect(): Promise<{
                publicKey: string;
                network: string;
            }>;
        };
    }
}
export declare class StellarProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private network;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txHash: string): Promise<void>;
    private setupFreighter;
    private setupXBull;
    private setupRabet;
}
export {};
