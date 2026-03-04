// =============================================================================
// AETHER SDK — IDENTITY MANAGER (MULTI-WALLET)
// Supports linking multiple wallets across EVM, SVM, BTC, SUI, NEAR, TRON, Cosmos
// =============================================================================

import type { Identity, IdentityData, UserTraits, ConnectedWallet, VMType } from '../types';
import { generateId, now, storage, cookies } from '../utils';

const ANON_ID_KEY = 'anon_id';
const IDENTITY_KEY = 'identity';
const ANON_COOKIE = '_aether_aid';

export class IdentityManager {
  private identity: Identity;

  constructor() {
    this.identity = this.loadOrCreateIdentity();
  }

  getIdentity(): Identity {
    return { ...this.identity, wallets: [...this.identity.wallets] };
  }

  getAnonymousId(): string {
    return this.identity.anonymousId;
  }

  getUserId(): string | undefined {
    return this.identity.userId;
  }

  /** Hydrate identity with known user data (merge anonymous -> known) */
  hydrateIdentity(data: IdentityData): Identity {
    if (data.userId) {
      this.identity.userId = data.userId;
    }

    // Legacy single-wallet support (backwards compatible)
    if (data.walletAddress) {
      this.identity.walletAddress = data.walletAddress;
      this.identity.walletType = data.walletType;
      this.identity.chainId = data.chainId;
      this.identity.ens = data.ens;
    }

    // Multi-wallet support
    if (data.wallets) {
      for (const w of data.wallets) {
        this.linkWalletMulti(w);
      }
    }

    if (data.traits) {
      this.identity.traits = { ...this.identity.traits, ...data.traits };
    }

    this.identity.lastSeen = now();
    this.identity.sessionCount++;
    this.persist();
    return this.getIdentity();
  }

  setTraits(traits: UserTraits): void {
    this.identity.traits = { ...this.identity.traits, ...traits };
    this.persist();
  }

  /** Link a single wallet (backwards compatible) */
  linkWallet(address: string, type?: string, chainId?: number, ens?: string): void {
    this.identity.walletAddress = address;
    if (type) this.identity.walletType = type;
    if (chainId) this.identity.chainId = chainId;
    if (ens) this.identity.ens = ens;

    // Also add to wallets array
    this.linkWalletMulti({
      address, vm: 'evm', chainId: chainId ?? 1,
      walletType: type ?? 'unknown', displayName: `EVM (${address.slice(0, 6)}...)`,
      classification: 'hot', connectedAt: now(), isConnected: true, isPrimary: true,
      ens,
    });

    this.persist();
  }

  /** Link a wallet from any VM */
  linkWalletMulti(wallet: ConnectedWallet): void {
    // Remove existing entry for same address + VM
    this.identity.wallets = this.identity.wallets.filter(
      (w) => !(w.address.toLowerCase() === wallet.address.toLowerCase() && w.vm === wallet.vm)
    );
    this.identity.wallets.push(wallet);

    // Update primary wallet reference for backwards compatibility
    if (wallet.isPrimary || this.identity.wallets.length === 1) {
      this.identity.walletAddress = wallet.address;
      this.identity.walletType = wallet.walletType;
      this.identity.chainId = typeof wallet.chainId === 'number' ? wallet.chainId : undefined;
      this.identity.ens = wallet.ens;
    }

    this.persist();
  }

  /** Unlink a specific wallet by address and VM */
  unlinkWallet(address?: string, vm?: VMType): void {
    if (address && vm) {
      this.identity.wallets = this.identity.wallets.filter(
        (w) => !(w.address.toLowerCase() === address.toLowerCase() && w.vm === vm)
      );
    } else if (address) {
      this.identity.wallets = this.identity.wallets.filter(
        (w) => w.address.toLowerCase() !== address.toLowerCase()
      );
    } else {
      // Unlink all
      this.identity.wallets = [];
      this.identity.walletAddress = undefined;
      this.identity.walletType = undefined;
      this.identity.chainId = undefined;
      this.identity.ens = undefined;
    }

    // Update primary reference
    if (this.identity.wallets.length > 0) {
      const primary = this.identity.wallets.find((w) => w.isPrimary) ?? this.identity.wallets[0];
      this.identity.walletAddress = primary.address;
      this.identity.walletType = primary.walletType;
    } else {
      this.identity.walletAddress = undefined;
      this.identity.walletType = undefined;
      this.identity.chainId = undefined;
      this.identity.ens = undefined;
    }

    this.persist();
  }

  /** Get all wallets */
  getWallets(): ConnectedWallet[] {
    return [...this.identity.wallets];
  }

  /** Get wallets filtered by VM */
  getWalletsByVM(vm: VMType): ConnectedWallet[] {
    return this.identity.wallets.filter((w) => w.vm === vm);
  }

  touch(): void {
    this.identity.lastSeen = now();
    this.persist();
  }

  reset(): Identity {
    storage.remove(IDENTITY_KEY);
    storage.remove(ANON_ID_KEY);
    cookies.remove(ANON_COOKIE);
    this.identity = this.createFreshIdentity();
    this.persist();
    return this.getIdentity();
  }

  isIdentified(): boolean {
    return !!this.identity.userId;
  }

  hasWallet(): boolean {
    return this.identity.wallets.length > 0 || !!this.identity.walletAddress;
  }

  getWalletCount(): number {
    return this.identity.wallets.length;
  }

  // ===========================================================================
  // PRIVATE
  // ===========================================================================

  private loadOrCreateIdentity(): Identity {
    const stored = storage.get<Identity>(IDENTITY_KEY);
    if (stored && stored.anonymousId) {
      stored.lastSeen = now();
      stored.sessionCount = (stored.sessionCount || 0) + 1;
      // Ensure wallets array exists (migration from v4)
      if (!stored.wallets) stored.wallets = [];
      return stored;
    }

    const cookieAnonId = cookies.get(ANON_COOKIE);
    const storedAnonId = storage.get<string>(ANON_ID_KEY);
    const anonymousId = cookieAnonId || storedAnonId || generateId();
    return this.createFreshIdentity(anonymousId);
  }

  private createFreshIdentity(anonymousId?: string): Identity {
    const id = anonymousId || generateId();
    return {
      anonymousId: id,
      wallets: [],
      traits: {},
      firstSeen: now(),
      lastSeen: now(),
      sessionCount: 1,
    };
  }

  private persist(): void {
    storage.set(IDENTITY_KEY, this.identity);
    storage.set(ANON_ID_KEY, this.identity.anonymousId);
    cookies.set(ANON_COOKIE, this.identity.anonymousId, 365);
  }
}
