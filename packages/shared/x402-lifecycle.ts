// =============================================================================
// Aether SDK — x402 Lifecycle Payload Types
// Canonical payload shapes for the full x402 payment lifecycle.
// See docs/source-of-truth/EVENT_REGISTRY.md and backend
// services/x402/lifecycle_mapper.py for downstream processing.
// =============================================================================

/** Common fields present on every x402 lifecycle payload. */
export interface X402LifecycleBase {
  /** Tenant that owns the payer agent. Required for all lifecycle events. */
  tenantId: string;
  /** Identifier of the requesting agent. Required. */
  agentId: string;
  /** Resource being accessed. */
  resourceId?: string;
  /** Service / provider endpoint. */
  serviceId?: string;
  /** Provider name (e.g. "openai", "anthropic"). */
  provider?: string;
  /** Protocol used (e.g. "x402", "usdc_base"). */
  protocol?: string;
  /** Amount as string to preserve precision. */
  amount?: string;
  /** Currency code (e.g. "USDC", "ETH"). */
  currency?: string;
  /** Capability being purchased. */
  capabilityRequested?: string;
  /** ISO 8601 timestamp. */
  timestamp?: string;
  /** Opaque metadata passthrough. */
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface X402ResourceRequestedPayload extends X402LifecycleBase {
  endpoint?: string;
  requestedAt?: string;
}

export interface X402PaymentRequiredPayload extends X402LifecycleBase {
  paymentTerms?: Record<string, unknown>;
  expiresAt?: string;
}

export interface X402QuoteReceivedPayload extends X402LifecycleBase {
  quoteId?: string;
  quotedAmount?: string;
  quotedCurrency?: string;
  facilitatorId?: string;
  validUntil?: string;
}

export interface X402AuthorizationRequestedPayload extends X402LifecycleBase {
  authorizationId: string;
  paymentIntentId?: string;
  requestedBy?: string;
}

export interface X402AuthorizationResolvedPayload extends X402LifecycleBase {
  authorizationId: string;
  paymentIntentId?: string;
  /** 'authorized' | 'authorization_denied' */
  resolution: string;
  resolvedBy?: string;
  denialReason?: string;
}

export interface X402PaymentIntentCreatedPayload extends X402LifecycleBase {
  paymentIntentId: string;
  quoteId?: string;
  authorizationId?: string;
  facilitatorId?: string;
  endpoint?: string;
  retryCount?: number;
}

export interface X402PaymentSubmittedPayload extends X402LifecycleBase {
  paymentIntentId: string;
  settlementEventId?: string;
  facilitatorId?: string;
  txHash?: string;
}

export interface X402PaymentSettledPayload extends X402LifecycleBase {
  paymentIntentId: string;
  settlementEventId: string;
  txHash?: string;
  facilitatorId?: string;
  settledAt?: string;
  executionId?: string;
}

export interface X402PaymentFailedPayload extends X402LifecycleBase {
  paymentIntentId: string;
  settlementEventId?: string;
  failureReason?: string;
  retryCount?: number;
}

export interface X402PaymentTimeoutPayload extends X402LifecycleBase {
  paymentIntentId: string;
  settlementEventId?: string;
  timeoutReason?: string;
}

export interface X402ReceiptVerifiedPayload extends X402LifecycleBase {
  receiptId: string;
  paymentIntentId?: string;
  settlementEventId?: string;
  verifiedAt?: string;
}

export interface X402AccessGrantedPayload extends X402LifecycleBase {
  paymentIntentId?: string;
  settlementEventId?: string;
  accessToken?: string;
  expiresAt?: string;
  executionId?: string;
}

export interface X402AccessDeniedPayload extends X402LifecycleBase {
  paymentIntentId?: string;
  denialReason?: string;
}

export interface X402RefundOrReversalPayload extends X402LifecycleBase {
  paymentIntentId?: string;
  settlementEventId: string;
  /** 'reversed' | 'refunded' */
  reversalType: string;
  refundAmount?: string;
  reversalReason?: string;
}
