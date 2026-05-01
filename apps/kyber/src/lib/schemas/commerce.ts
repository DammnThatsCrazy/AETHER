/**
 * KYBER Zod schemas for Agentic Commerce.
 * These validate every response from /v1/x402/* and /v1/approvals/* adapters.
 * Wire format mirrors backend Pydantic models in services/x402/commerce_models.py.
 */
import { z } from 'zod';

export const approvalStatusSchema = z.enum([
  'pending',
  'assigned',
  'approved',
  'rejected',
  'escalated',
  'expired',
  'revoked',
]);

export const approvalPrioritySchema = z.enum(['low', 'normal', 'high', 'critical']);

export const settlementStateSchema = z.enum([
  'pending',
  'verifying',
  'settled',
  'failed',
  'disputed',
]);

export const entitlementStatusSchema = z.enum(['active', 'expired', 'revoked']);

export const policyOutcomeSchema = z.enum([
  'allow',
  'deny',
  'require_approval',
  'reduce_scope',
]);

export const resourceClassSchema = z.enum([
  'api',
  'agent_tool',
  'priced_endpoint',
  'service_plan',
  'internal_capability',
]);

export const protectedResourceSchema = z.object({
  resource_id: z.string(),
  tenant_id: z.string(),
  name: z.string(),
  resource_class: resourceClassSchema,
  path_pattern: z.string(),
  owner_service: z.string(),
  description: z.string(),
  price_usd: z.number(),
  accepted_assets: z.array(z.string()),
  accepted_chains: z.array(z.string()),
  approval_required: z.boolean(),
  entitlement_ttl_seconds: z.number(),
  active: z.boolean(),
  registered_at: z.string(),
}).passthrough();

export const paymentRequirementSchema = z.object({
  challenge_id: z.string(),
  tenant_id: z.string(),
  resource_id: z.string(),
  amount_usd: z.number(),
  asset_symbol: z.string(),
  chain: z.string(),
  recipient: z.string(),
  protocol_version: z.string(),
  memo: z.string().nullable().optional(),
  expires_at: z.string(),
  payment_identifier: z.string(),
  requester_id: z.string(),
  requester_type: z.string(),
  siwx_nonce: z.string().nullable().optional(),
  issued_at: z.string(),
}).passthrough();

export const policyDecisionSchema = z.object({
  decision_id: z.string(),
  tenant_id: z.string(),
  challenge_id: z.string(),
  outcome: policyOutcomeSchema,
  active_rules: z.array(z.string()),
  denial_reason: z.string().nullable().optional(),
  requires_approval: z.boolean(),
  rationale: z.string(),
  decided_at: z.string(),
}).passthrough();

export const approvalRequestSchema = z.object({
  approval_id: z.string(),
  tenant_id: z.string(),
  challenge_id: z.string(),
  resource_id: z.string(),
  requester_id: z.string(),
  requester_type: z.string(),
  amount_usd: z.number(),
  asset_symbol: z.string(),
  chain: z.string(),
  facilitator_id: z.string().nullable().optional(),
  priority: approvalPrioritySchema,
  reason: z.string(),
  context: z.record(z.string(), z.unknown()),
  policy_decision_id: z.string().nullable().optional(),
  status: approvalStatusSchema,
  assigned_to: z.string().nullable().optional(),
  escalation_chain: z.array(z.string()),
  evidence_bundle_id: z.string().nullable().optional(),
  created_at: z.string(),
  expires_at: z.string(),
  decided_at: z.string().nullable().optional(),
  decided_by: z.string().nullable().optional(),
  decision_reason: z.string().nullable().optional(),
  is_override: z.boolean(),
}).passthrough();

export const settlementSchema = z.object({
  settlement_id: z.string(),
  tenant_id: z.string(),
  receipt_id: z.string(),
  challenge_id: z.string(),
  state: settlementStateSchema,
  tx_hash: z.string(),
  chain: z.string(),
  amount_usd: z.number(),
  facilitator_id: z.string(),
  attempts: z.number(),
  settled_at: z.string().nullable().optional(),
  failure_reason: z.string().nullable().optional(),
}).passthrough();

export const entitlementSchema = z.object({
  entitlement_id: z.string(),
  tenant_id: z.string(),
  holder_id: z.string(),
  holder_type: z.string(),
  resource_id: z.string(),
  scope: z.string(),
  status: entitlementStatusSchema,
  settlement_id: z.string(),
  issued_at: z.string(),
  expires_at: z.string(),
  reuse_count: z.number(),
  last_reused_at: z.string().nullable().optional(),
  revoked_at: z.string().nullable().optional(),
  revoked_by: z.string().nullable().optional(),
  revoke_reason: z.string().nullable().optional(),
  siwx_binding: z.string().nullable().optional(),
}).passthrough();

export const lifecycleTraceSchema = z.object({
  challenge_id: z.string(),
  tenant_id: z.string(),
  requirement: paymentRequirementSchema.nullable().optional(),
  policy_decision: policyDecisionSchema.nullable().optional(),
  approval: approvalRequestSchema.nullable().optional(),
  authorization: z.record(z.string(), z.unknown()).nullable().optional(),
  receipt: z.record(z.string(), z.unknown()).nullable().optional(),
  settlement: settlementSchema.nullable().optional(),
  entitlement: entitlementSchema.nullable().optional(),
  grant: z.record(z.string(), z.unknown()).nullable().optional(),
  fulfillment: z.record(z.string(), z.unknown()).nullable().optional(),
  graph_writes: z.array(z.record(z.string(), z.unknown())),
  events_emitted: z.array(z.string()),
}).passthrough();

export const preflightResultSchema = z.object({
  can_access: z.boolean(),
  reason: z.string(),
  resource_id: z.string(),
  holder_id: z.string(),
  existing_entitlement_id: z.string().nullable().optional(),
  price_quote_usd: z.number().nullable().optional(),
  accepted_assets: z.array(z.string()),
  accepted_chains: z.array(z.string()),
  approval_required: z.boolean(),
  challenge_url: z.string().nullable().optional(),
}).passthrough();

export const facilitatorSchema = z.object({
  facilitator_id: z.string(),
  name: z.string(),
  endpoint_url: z.string(),
  mode: z.string(),
  supported_assets: z.array(z.string()),
  supported_chains: z.array(z.string()),
  health_status: z.string(),
  avg_latency_ms: z.number(),
  success_rate: z.number(),
  active: z.boolean(),
}).passthrough();

export const stablecoinAssetSchema = z.object({
  asset_id: z.string(),
  symbol: z.string(),
  chain: z.string(),
  network: z.string(),
  issuer: z.string(),
  contract_address: z.string(),
  decimals: z.number(),
  settlement_scheme: z.string(),
  active: z.boolean(),
  risk_score: z.number(),
}).passthrough();

export const evidenceBundleSchema = z.object({
  approval: approvalRequestSchema,
  policy_decision: policyDecisionSchema.nullable(),
  requirement: paymentRequirementSchema.nullable(),
}).passthrough();

export type ProtectedResource = z.infer<typeof protectedResourceSchema>;
export type PaymentRequirement = z.infer<typeof paymentRequirementSchema>;
export type PolicyDecision = z.infer<typeof policyDecisionSchema>;
export type ApprovalRequest = z.infer<typeof approvalRequestSchema>;
export type Settlement = z.infer<typeof settlementSchema>;
export type Entitlement = z.infer<typeof entitlementSchema>;
export type LifecycleTrace = z.infer<typeof lifecycleTraceSchema>;
export type PreflightResult = z.infer<typeof preflightResultSchema>;
export type Facilitator = z.infer<typeof facilitatorSchema>;
export type StablecoinAsset = z.infer<typeof stablecoinAssetSchema>;
export type EvidenceBundle = z.infer<typeof evidenceBundleSchema>;
export type ApprovalStatus = z.infer<typeof approvalStatusSchema>;
export type ApprovalPriority = z.infer<typeof approvalPrioritySchema>;
export type SettlementState = z.infer<typeof settlementStateSchema>;
export type EntitlementStatus = z.infer<typeof entitlementStatusSchema>;
export type PolicyOutcome = z.infer<typeof policyOutcomeSchema>;
export type ResourceClass = z.infer<typeof resourceClassSchema>;
