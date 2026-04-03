// =============================================================================
// AETHER SDK — IDENTITY MANAGER
// =============================================================================

import type { Identity, IdentityData, UserTraits } from './WebSDKTypes(CoreTypeDefinitions)';
import { generateId, now, storage, cookies } from './SDKUtilityFunctions';

const ANON_ID_KEY = 'anon_id';
const IDENTITY_KEY = 'identity';
const ANON_COOKIE = '_aether_aid';

export class IdentityManager {
  private identity: Identity;

  constructor() {
    this.identity = this.loadOrCreateIdentity();
  }

  /** Get current identity */
  getIdentity(): Identity {
    return { ...this.identity };
  }

  /** Get anonymous ID */
  getAnonymousId(): string {
    return this.identity.anonymousId;
  }

  /** Get user ID (if identified) */
  getUserId(): string | undefined {
    return this.identity.userId;
  }

  /** Hydrate identity with known user data (merge anonymous → known) */
  hydrateIdentity(data: IdentityData): Identity {
    if (data.userId) {
      this.identity.userId = data.userId;
    }
    if (data.walletAddress) {
      this.identity.walletAddress = data.walletAddress;
      this.identity.walletType = data.walletType;
      this.identity.chainId = data.chainId;
      this.identity.ens = data.ens;
    }
    if (data.traits) {
      this.identity.traits = { ...this.identity.traits, ...data.traits };
    }
    this.identity.lastSeen = now();
    this.identity.sessionCount++;
    this.persist();
    return this.getIdentity();
  }

  /** Update user traits */
  setTraits(traits: UserTraits): void {
    this.identity.traits = { ...this.identity.traits, ...traits };
    this.persist();
  }

  /** Link a wallet address to this identity */
  linkWallet(address: string, type?: string, chainId?: number, ens?: string): void {
    this.identity.walletAddress = address;
    if (type) this.identity.walletType = type;
    if (chainId) this.identity.chainId = chainId;
    if (ens) this.identity.ens = ens;
    this.persist();
  }

  /** Unlink wallet from identity */
  unlinkWallet(): void {
    this.identity.walletAddress = undefined;
    this.identity.walletType = undefined;
    this.identity.chainId = undefined;
    this.identity.ens = undefined;
    this.persist();
  }

  /** Record a session touch */
  touch(): void {
    this.identity.lastSeen = now();
    this.persist();
  }

  /** Full reset — new anonymous identity, clear all data */
  reset(): Identity {
    storage.remove(IDENTITY_KEY);
    storage.remove(ANON_ID_KEY);
    cookies.remove(ANON_COOKIE);

    this.identity = this.createFreshIdentity();
    this.persist();
    return this.getIdentity();
  }

  /** Check if user is identified (has userId) */
  isIdentified(): boolean {
    return !!this.identity.userId;
  }

  /** Check if user has linked wallet */
  hasWallet(): boolean {
    return !!this.identity.walletAddress;
  }

  // ===========================================================================
  // PRIVATE
  // ===========================================================================

  private loadOrCreateIdentity(): Identity {
    // Try loading from storage
    const stored = storage.get<Identity>(IDENTITY_KEY);
    if (stored && stored.anonymousId) {
      stored.lastSeen = now();
      stored.sessionCount = (stored.sessionCount || 0) + 1;
      return stored;
    }

    // Try recovering anonymous ID from cookie (cross-subdomain persistence)
    const cookieAnonId = cookies.get(ANON_COOKIE);
    const storedAnonId = storage.get<string>(ANON_ID_KEY);
    const anonymousId = cookieAnonId || storedAnonId || generateId();

    return this.createFreshIdentity(anonymousId);
  }

  private createFreshIdentity(anonymousId?: string): Identity {
    const id = anonymousId || generateId();
    return {
      anonymousId: id,
      traits: {},
      firstSeen: now(),
      lastSeen: now(),
      sessionCount: 1,
    };
  }

  private persist(): void {
    storage.set(IDENTITY_KEY, this.identity);
    storage.set(ANON_ID_KEY, this.identity.anonymousId);
    // Also set cookie for cross-subdomain
    cookies.set(ANON_COOKIE, this.identity.anonymousId, 365);
  }
}
