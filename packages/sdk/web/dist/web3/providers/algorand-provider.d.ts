import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface AlgorandWalletProvider {
    enable(opts?: {
        genesisId?: string;
    }): Promise<{
        accounts: string[];
    }>;
    signTxns?(txns: {
        txn: string;
    }[]): Promise<(string | null)[]>;
    on?(event: string, handler: (...args: unknown[]) => void): void;
    name?: string;
}
interface AlgoSignerAPI {
    accounts(opts: {
        ledger: string;
    }): Promise<{
        address: string;
    }[]>;
    sign(params: unknown): Promise<unknown>;
}
declare global {
    interface Window {
        algorand?: AlgorandWalletProvider;
        AlgoSigner?: AlgoSignerAPI;
    }
}
export declare class AlgorandProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private provider;
    private network;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txId: string): Promise<void>;
    private setupProvider;
    private setupAlgoSigner;
}
export {};
