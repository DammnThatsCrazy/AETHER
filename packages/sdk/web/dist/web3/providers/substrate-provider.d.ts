import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface InjectedAccount {
    address: string;
    name?: string;
    type?: string;
    genesisHash?: string | null;
}
interface InjectedAccounts {
    get(anyType?: boolean): Promise<InjectedAccount[]>;
    subscribe(cb: (accounts: InjectedAccount[]) => void): () => void;
}
interface InjectedExtension {
    name: string;
    version?: string;
    accounts: InjectedAccounts;
    enable(origin: string): Promise<{
        accounts: InjectedAccounts;
    }>;
}
declare global {
    interface Window {
        injectedWeb3?: Record<string, {
            version?: string;
            enable(origin: string): Promise<InjectedExtension>;
        }>;
        SubWallet?: unknown;
        talismanEth?: unknown;
    }
}
export declare class SubstrateProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private extension;
    private unsubscribe;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txHash: string): Promise<void>;
    private setupProvider;
}
export {};
