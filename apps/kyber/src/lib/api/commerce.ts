/**
 * KYBER adapter: Agentic Commerce control plane.
 * Wraps /v1/x402/*, /v1/approvals/*, /v1/entitlements/*, /v1/diagnostics/commerce/*.
 *
 * Every response is validated via Zod at the network boundary. Errors are
 * surfaced through RestClientError which feeds KYBER's existing error-handling.
 */
import { z } from 'zod';
import { restClient } from '@kyber/lib/api';
import {
  approvalRequestSchema,
  entitlementSchema,
  evidenceBundleSchema,
  facilitatorSchema,
  lifecycleTraceSchema,
  paymentRequirementSchema,
  policyDecisionSchema,
  preflightResultSchema,
  protectedResourceSchema,
  stablecoinAssetSchema,
  type ApprovalPriority,
  type ApprovalStatus,
} from '@kyber/lib/schemas/commerce';

const envelope = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, meta: z.record(z.string(), z.unknown()).optional() });

// ─── Protected resources ────────────────────────────────────────────

export const commerceApi = {
  listResources: () =>
    restClient
      .get('/v1/x402/resources', envelope(z.array(protectedResourceSchema)))
      .then((r) => r.data),

  getResource: (resourceId: string) =>
    restClient
      .get(`/v1/x402/resources/${resourceId}`, envelope(protectedResourceSchema))
      .then((r) => r.data),

  seedResources: () =>
    restClient
      .post(
        '/v1/x402/resources/seed',
        envelope(z.object({ resources: z.number(), tenant_id: z.string() })),
        {}
      )
      .then((r) => r.data),

  // ─── Preflight / Challenge / Authorize / Verify / Grant ───────────

  preflight: (holderId: string, resourceId: string) =>
    restClient
      .post('/v1/x402/access/preflight', envelope(preflightResultSchema), {
        holder_id: holderId,
        resource_id: resourceId,
      })
      .then((r) => r.data),

  issueChallenge: (body: {
    resource_id: string;
    requester_id: string;
    requester_type?: string;
    chain?: string;
    asset_symbol?: string;
  }) =>
    restClient
      .post('/v1/x402/challenge', envelope(paymentRequirementSchema), body)
      .then((r) => r.data),

  requestApproval: (challengeId: string, priority: ApprovalPriority, reason: string) =>
    restClient
      .post(
        '/v1/x402/approval/request',
        envelope(
          z.object({
            approval: approvalRequestSchema,
            policy_decision: policyDecisionSchema,
          })
        ),
        { challenge_id: challengeId, priority, reason, context: {} }
      )
      .then((r) => r.data),

  authorizePayment: (approvalId: string, payer: string) =>
    restClient
      .post(
        '/v1/x402/authorize',
        envelope(z.record(z.string(), z.unknown())),
        { approval_id: approvalId, payer }
      )
      .then((r) => r.data),

  verifyAndSettle: (authorizationId: string, txHash: string) =>
    restClient
      .post(
        '/v1/x402/verify',
        envelope(
          z
            .object({
              verified: z.boolean(),
              receipt_id: z.string().optional(),
              settlement_id: z.string().optional(),
              settlement_state: z.string().optional(),
              entitlement_id: z.string().optional(),
              expires_at: z.string().optional(),
              error: z.string().optional(),
            })
            .passthrough()
        ),
        { authorization_id: authorizationId, tx_hash: txHash }
      )
      .then((r) => r.data),

  grantAccess: (entitlementId: string, requestUrl = '', requestMethod = 'GET') =>
    restClient
      .post(
        '/v1/x402/access/grant',
        envelope(z.record(z.string(), z.unknown())),
        { entitlement_id: entitlementId, request_url: requestUrl, request_method: requestMethod }
      )
      .then((r) => r.data),

  // ─── Explainability ──────────────────────────────────────────────

  explain: (challengeId: string) =>
    restClient
      .get(`/v1/x402/explain/${challengeId}`, envelope(lifecycleTraceSchema))
      .then((r) => r.data),

  // ─── Facilitators / Assets ───────────────────────────────────────

  listFacilitators: () =>
    restClient
      .get('/v1/x402/facilitators', envelope(z.array(facilitatorSchema)))
      .then((r) => r.data),

  listAssets: () =>
    restClient
      .get('/v1/x402/assets', envelope(z.array(stablecoinAssetSchema)))
      .then((r) => r.data),

  // ─── Policy ──────────────────────────────────────────────────────

  simulatePolicy: (body: {
    resource_id: string;
    requester_id: string;
    amount_usd: number;
    asset_symbol: string;
    chain: string;
  }) =>
    restClient
      .post('/v1/x402/policies/simulate', envelope(policyDecisionSchema), body)
      .then((r) => r.data),

  // ─── Pricing ─────────────────────────────────────────────────────

  quotePrice: (resourceId: string, plan?: string) =>
    restClient
      .get(
        plan
          ? `/v1/x402/pricing/${resourceId}?plan=${encodeURIComponent(plan)}`
          : `/v1/x402/pricing/${resourceId}`,
        envelope(
          z.object({
            resource_id: z.string(),
            unit_price_usd: z.number(),
            total_usd: z.number(),
            currency: z.string(),
            asset_symbol: z.string(),
          })
        )
      )
      .then((r) => r.data),
};

// ─── Approvals ──────────────────────────────────────────────────────

export const approvalsApi = {
  list: (filters?: { status?: ApprovalStatus; assigned_to?: string }) => {
    const qs = new URLSearchParams();
    if (filters?.status) qs.set('status', filters.status);
    if (filters?.assigned_to) qs.set('assigned_to', filters.assigned_to);
    const suffix = qs.toString() ? `?${qs}` : '';
    return restClient
      .get(`/v1/approvals${suffix}`, envelope(z.array(approvalRequestSchema)))
      .then((r) => r.data);
  },

  get: (approvalId: string) =>
    restClient
      .get(`/v1/approvals/${approvalId}`, envelope(approvalRequestSchema))
      .then((r) => r.data),

  assign: (approvalId: string, assigneeId: string, assignedBy: string) =>
    restClient
      .post(
        `/v1/approvals/${approvalId}/assign`,
        envelope(approvalRequestSchema),
        { assignee_id: assigneeId, assigned_by: assignedBy }
      )
      .then((r) => r.data),

  decide: (
    approvalId: string,
    action: 'approve' | 'reject' | 'escalate',
    decidedBy: string,
    reason: string,
    isOverride = false
  ) =>
    restClient
      .post(
        `/v1/approvals/${approvalId}/decide`,
        envelope(approvalRequestSchema),
        { action, decided_by: decidedBy, reason, is_override: isOverride }
      )
      .then((r) => r.data),

  revoke: (approvalId: string, revokedBy: string, reason: string) =>
    restClient
      .post(
        `/v1/approvals/${approvalId}/revoke`,
        envelope(approvalRequestSchema),
        { revoked_by: revokedBy, reason }
      )
      .then((r) => r.data),

  evidence: (approvalId: string) =>
    restClient
      .get(`/v1/approvals/${approvalId}/evidence`, envelope(evidenceBundleSchema))
      .then((r) => r.data),

  replay: (approvalId: string) =>
    restClient
      .post(
        `/v1/approvals/${approvalId}/replay`,
        envelope(
          z.object({
            approval: approvalRequestSchema,
            replay_decision: policyDecisionSchema.nullable(),
            mode: z.string(),
          })
        ),
        {}
      )
      .then((r) => r.data),
};

// ─── Entitlements ───────────────────────────────────────────────────

export const entitlementsApi = {
  listForHolder: (holderId: string, activeOnly = true) =>
    restClient
      .get(
        `/v1/entitlements?holder_id=${encodeURIComponent(holderId)}&active_only=${activeOnly}`,
        envelope(z.array(entitlementSchema))
      )
      .then((r) => r.data),

  get: (entitlementId: string) =>
    restClient
      .get(`/v1/entitlements/${entitlementId}`, envelope(entitlementSchema))
      .then((r) => r.data),

  revoke: (entitlementId: string, reason: string, revokedBy: string) =>
    restClient
      .post(
        `/v1/entitlements/${entitlementId}/revoke?reason=${encodeURIComponent(reason)}&revoked_by=${encodeURIComponent(revokedBy)}`,
        envelope(entitlementSchema),
        {}
      )
      .then((r) => r.data),
};

// ─── Diagnostics ────────────────────────────────────────────────────

export const commerceDiagnosticsApi = {
  health: () =>
    restClient
      .get('/v1/diagnostics/commerce/health', envelope(z.record(z.string(), z.unknown())))
      .then((r) => r.data),

  stuckApprovals: () =>
    restClient
      .get(
        '/v1/diagnostics/commerce/stuck-approvals',
        envelope(
          z.object({
            swept: z.number(),
            expired: z.array(approvalRequestSchema),
          })
        )
      )
      .then((r) => r.data),
};
