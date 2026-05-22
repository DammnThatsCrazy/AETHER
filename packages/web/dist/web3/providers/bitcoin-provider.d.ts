import type { WalletInfo } from '../../types';
import { BaseVMProvider, type VMType, type ProviderCallbacks } from './base-provider';
interface BTCProvider {
    requestAccounts(): Promise<string[]>;
    getAccounts(): Promise<string[]>;
    getBalance?(): Promise<{
        confirmed: number;
        unconfirmed: number;
        total: number;
    }>;
    getNetwork?(): Promise<string>;
    signPsbt?(psbtHex: string): Promise<string>;
    signMessage?(message: string): Promise<string>;
    on?(event: string, handler: (...args: unknown[]) => void): void;
    removeListener?(event: string, handler: (...args: unknown[]) => void): void;
}
declare global {
    interface Window {
        unisat?: BTCProvider;
        xverse?: {
            bitcoin?: BTCProvider;
        };
        LeatherProvider?: BTCProvider;
        okxwallet?: {
            bitcoin?: BTCProvider;
        };
    }
}
export declare class BitcoinProvider extends BaseVMProvider {
    readonly vm: VMType;
    readonly defaultChainId: string;
    private provider;
    private network;
    private handlers;
    constructor(callbacks: ProviderCallbacks);
    init(): void;
    /** Override connect to include addressType and preserve BTC address casing */
    connect(address: string, options?: Partial<WalletInfo>): void;
    destroy(): void;
    protected detectWalletType(): string;
    protected monitorTransaction(txid: string): Promise<void>;
    private setupProvider;
    private detectAddressType;
}
export {};
