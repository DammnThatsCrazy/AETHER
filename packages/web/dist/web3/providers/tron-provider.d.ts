import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface TronWebProvider {
    ready?: boolean;
    defaultAddress?: {
        base58: string;
        hex: string;
    };
    fullNode?: {
        host: string;
    };
    trx?: {
        getBalance(address: string): Promise<number>;
        getTransaction(txid: string): Promise<{
            ret?: {
                contractRet: string;
            }[];
        }>;
        getAccount(address: string): Promise<unknown>;
        sign(tx: unknown): Promise<unknown>;
        sendRawTransaction(signedTx: unknown): Promise<{
            result: boolean;
            txid: string;
        }>;
    };
    contract?(): {
        at(address: string): Promise<unknown>;
    };
    on?(event: string, handler: (...args: unknown[]) => void): void;
}
declare global {
    interface Window {
        tronWeb?: TronWebProvider;
        tronLink?: {
            ready?: boolean;
            tronWeb?: TronWebProvider;
        };
    }
}
export declare class TronProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private tronWeb;
    private network;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txid: string): Promise<void>;
    private setupProvider;
    private detectNetwork;
}
export {};
