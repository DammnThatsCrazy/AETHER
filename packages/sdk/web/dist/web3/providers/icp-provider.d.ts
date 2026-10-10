import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface PlugWallet {
    isConnected(): Promise<boolean>;
    requestConnect(opts?: {
        whitelist?: string[];
        host?: string;
    }): Promise<boolean>;
    getPrincipal(): Promise<{
        toString(): string;
    }>;
    accountId?: string;
    agent?: unknown;
}
interface NFIDWallet {
    requestConnect(opts?: {
        derivationOrigin?: string;
    }): Promise<{
        getPrincipal(): {
            toString(): string;
        };
    }>;
    isAuthenticated?: boolean;
}
declare global {
    interface Window {
        ic?: {
            plug?: PlugWallet;
            nfid?: NFIDWallet;
            stoic?: unknown;
        };
    }
}
export declare class ICPProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txId: string): Promise<void>;
    private setupPlug;
    private setupNFID;
}
export {};
