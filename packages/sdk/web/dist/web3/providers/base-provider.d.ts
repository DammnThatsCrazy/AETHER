import type { WalletInfo } from '../../types';
export type VMType = 'evm' | 'svm' | 'bitcoin' | 'movevm' | 'near' | 'tvm' | 'cosmos' | 'aptos' | 'ton' | 'starknet' | 'cardano' | 'substrate' | 'algorand' | 'hedera' | 'stellar' | 'icp';
export interface ProviderCallbacks {
    onWalletEvent: (action: string, data: Record<string, unknown>) => void;
    onTransaction: (txId: string, data: Record<string, unknown>) => void;
}
export declare abstract class BaseVMProvider {
    protected callbacks: ProviderCallbacks;
    protected wallet: WalletInfo | null;
    protected walletType: string;
    abstract readonly vm: VMType;
    abstract readonly defaultChainId: string | number;
    constructor(callbacks: ProviderCallbacks);
    abstract init(): void;
    protected abstract detectWalletType(): string;
    protected abstract monitorTransaction(txId: string): Promise<void>;
    connect(address: string, options?: Partial<WalletInfo>): void;
    disconnect(): void;
    getWallet(): WalletInfo | null;
    transaction(txId: string, data: Record<string, unknown>): void;
    destroy(): void;
}
