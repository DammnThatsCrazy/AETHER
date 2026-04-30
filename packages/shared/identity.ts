// =============================================================================
// Aether SDK — Shared Identity Contract
// Inputs the SDK supplies to backend identity resolution:
//   anonymous_id, user_id, device_id, wallet_address, email, phone.
// See docs/source-of-truth/ENTITY_MODEL.md §Identity.
// =============================================================================

import type { VMType, WalletInfo } from './wallet';

/** Optional wallet hydration entry — supports multi-VM identity. */
export interface IdentityWallet extends WalletInfo {
  vm: VMType;
  address: string;
}

/** Data accepted by Aether.hydrateIdentity(). Every field is optional. */
export interface IdentityData {
  userId?: string;
  email?: string;
  phone?: string;
  /** Backwards-compatible single-wallet hydration (EVM). */
  walletAddress?: string;
  walletType?: string;
  chainId?: number;
  ens?: string;
  /** Multi-VM hydration — preferred for new integrations. */
  wallets?: IdentityWallet[];
  /** Arbitrary traits forwarded to backend profile service. */
  traits?: Record<string, unknown>;
  /** Optional OAuth / SSO identifiers. */
  oauthProvider?: string;
  oauthSubject?: string;
  /** Optional tenant / org binding for B2B + hybrid companies. */
  tenantId?: string;
  orgId?: string;
}

/** Resolved identity state the SDK exposes after hydrateIdentity. */
export interface Identity {
  anonymousId: string;
  userId?: string;
  email?: string;
  phone?: string;
  tenantId?: string;
  orgId?: string;
  traits: Record<string, unknown>;
  /** Primary wallet (backwards-compatible). */
  walletAddress?: string;
  /** Every wallet the SDK has observed this session. */
  wallets: IdentityWallet[];
}
