import type { Identity, IdentityData, UserTraits, ConnectedWallet, VMType } from '../types';
export declare class IdentityManager {
    private identity;
    constructor();
    getIdentity(): Identity;
    getAnonymousId(): string;
    getUserId(): string | undefined;
    /** Hydrate identity with known user data (merge anonymous -> known) */
    hydrateIdentity(data: IdentityData): Identity;
    setTraits(traits: UserTraits): void;
    /** Link a single wallet (backwards compatible) */
    linkWallet(address: string, type?: string, chainId?: number, ens?: string): void;
    /** Link a wallet from any VM */
    linkWalletMulti(wallet: ConnectedWallet): void;
    /** Unlink a specific wallet by address and VM */
    unlinkWallet(address?: string, vm?: VMType): void;
    /** Get all wallets */
    getWallets(): ConnectedWallet[];
    /** Get wallets filtered by VM */
    getWalletsByVM(vm: VMType): ConnectedWallet[];
    touch(): void;
    reset(): Identity;
    isIdentified(): boolean;
    hasWallet(): boolean;
    getWalletCount(): number;
    private loadOrCreateIdentity;
    private createFreshIdentity;
    private persist;
}
