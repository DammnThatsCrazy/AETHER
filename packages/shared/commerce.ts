// =============================================================================
// Aether SDK — Shared Commerce / Access Contract
// Unifies Web2 (fiat/stripe/invoice), Web3 (onchain), and x402 flows under a
// single "business event + optional rail" model.
// See docs/source-of-truth/ENTITY_MODEL.md §Commerce.
// =============================================================================

import type { Rail, ActorKind } from './provenance';
import type { EntityRef } from './entities';

/** Payment lifecycle status. */
export type PaymentStatus =
  | 'initiated'
  | 'pending'
  | 'authorized'
  | 'captured'
  | 'completed'
  | 'failed'
  | 'refunded'
  | 'disputed';

/** Approval workflow outcome. */
export type ApprovalStatus = 'requested' | 'approved' | 'rejected' | 'escalated' | 'expired';

/** Entitlement lifecycle. */
export type EntitlementStatus = 'granted' | 'revoked' | 'expired' | 'suspended';

/** Canonical payment properties (rail-agnostic). */
export interface PaymentProperties {
  paymentId: string;
  amount: number;
  currency: string;
  status: PaymentStatus;
  rail: Rail;
  payer?: EntityRef;
  payee?: EntityRef;
  subject?: EntityRef; // what the payment purchases (resource / subscription / plan)
  /** Rail-specific external id: stripe_charge_id | tx_hash | invoice_number | x402_id */
  external_ref?: string;
  [key: string]: unknown;
}

/** Canonical approval-request / decision properties. */
export interface ApprovalProperties {
  approvalId: string;
  status: ApprovalStatus;
  requester?: EntityRef;
  requester_kind?: ActorKind;
  subject?: EntityRef;
  reason?: string;
  [key: string]: unknown;
}

/** Canonical entitlement-grant / revoke properties. */
export interface EntitlementProperties {
  entitlementId: string;
  status: EntitlementStatus;
  holder?: EntityRef;
  resource?: EntityRef;
  expiresAt?: string;
  [key: string]: unknown;
}

/** Canonical access-grant / deny properties. */
export interface AccessProperties {
  resource: EntityRef;
  granted: boolean;
  reason?: string;
  actor?: EntityRef;
  [key: string]: unknown;
}
