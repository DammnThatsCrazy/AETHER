import { describe, it, expect } from 'vitest';
import {
  approvalRequestSchema,
  approvalPrioritySchema,
  approvalStatusSchema,
  entitlementSchema,
  facilitatorSchema,
  lifecycleTraceSchema,
  paymentRequirementSchema,
  policyDecisionSchema,
  preflightResultSchema,
  protectedResourceSchema,
  settlementSchema,
  stablecoinAssetSchema,
} from '@kyber/lib/schemas/commerce';
import {
  fixtureApprovalApproved,
  fixtureApprovalPending,
  fixtureAssets,
  fixtureEntitlement,
  fixtureFacilitators,
  fixtureLifecycleTrace,
  fixturePaymentRequirement,
  fixturePolicyDecision,
  fixtureResources,
  fixtureSettlement,
} from '@kyber/fixtures/commerce';

describe('approvalPrioritySchema', () => {
  it('accepts all 4 priorities', () => {
    expect(approvalPrioritySchema.parse('low')).toBe('low');
    expect(approvalPrioritySchema.parse('normal')).toBe('normal');
    expect(approvalPrioritySchema.parse('high')).toBe('high');
    expect(approvalPrioritySchema.parse('critical')).toBe('critical');
  });
  it('rejects invalid priority', () => {
    expect(() => approvalPrioritySchema.parse('urgent')).toThrow();
  });
});

describe('approvalStatusSchema', () => {
  it('accepts all 7 statuses', () => {
    const statuses = ['pending', 'assigned', 'approved', 'rejected', 'escalated', 'expired', 'revoked'];
    for (const s of statuses) {
      expect(approvalStatusSchema.parse(s)).toBe(s);
    }
  });
});

describe('protectedResourceSchema', () => {
  it('accepts every fixture resource', () => {
    for (const r of fixtureResources) {
      expect(() => protectedResourceSchema.parse(r)).not.toThrow();
    }
  });
  it('rejects missing required fields', () => {
    expect(() =>
      protectedResourceSchema.parse({ resource_id: 'x' })
    ).toThrow();
  });
});

describe('paymentRequirementSchema', () => {
  it('accepts fixture', () => {
    expect(() => paymentRequirementSchema.parse(fixturePaymentRequirement)).not.toThrow();
  });
});

describe('policyDecisionSchema', () => {
  it('accepts fixture with mandatory_approval rule', () => {
    const parsed = policyDecisionSchema.parse(fixturePolicyDecision);
    expect(parsed.requires_approval).toBe(true);
    expect(parsed.active_rules).toContain('mandatory_approval_all_spend_classes');
  });
});

describe('approvalRequestSchema', () => {
  it('accepts pending fixture', () => {
    expect(() => approvalRequestSchema.parse(fixtureApprovalPending)).not.toThrow();
  });
  it('accepts approved fixture', () => {
    expect(() => approvalRequestSchema.parse(fixtureApprovalApproved)).not.toThrow();
  });
});

describe('settlementSchema', () => {
  it('accepts fixture', () => {
    const parsed = settlementSchema.parse(fixtureSettlement);
    expect(parsed.state).toBe('settled');
  });
});

describe('entitlementSchema', () => {
  it('accepts fixture with reuse_count', () => {
    const parsed = entitlementSchema.parse(fixtureEntitlement);
    expect(parsed.status).toBe('active');
    expect(parsed.reuse_count).toBe(3);
  });
});

describe('facilitatorSchema', () => {
  it('accepts all fixtures', () => {
    for (const f of fixtureFacilitators) {
      expect(() => facilitatorSchema.parse(f)).not.toThrow();
    }
  });
});

describe('stablecoinAssetSchema', () => {
  it('accepts Base and Solana USDC fixtures', () => {
    for (const a of fixtureAssets) {
      const parsed = stablecoinAssetSchema.parse(a);
      expect(parsed.symbol).toBe('USDC');
    }
  });
});

describe('lifecycleTraceSchema', () => {
  it('accepts full trace fixture', () => {
    const parsed = lifecycleTraceSchema.parse(fixtureLifecycleTrace);
    expect(parsed.requirement).not.toBeNull();
    expect(parsed.approval).not.toBeNull();
    expect(parsed.entitlement).not.toBeNull();
    expect(parsed.graph_writes.length).toBeGreaterThan(0);
  });
});

describe('preflightResultSchema', () => {
  it('accepts can_access=true result', () => {
    const r = preflightResultSchema.parse({
      can_access: true,
      reason: 'active_entitlement',
      resource_id: 'r1',
      holder_id: 'a1',
      existing_entitlement_id: 'ent_1',
      accepted_assets: ['USDC'],
      accepted_chains: ['eip155:8453'],
      approval_required: true,
    });
    expect(r.can_access).toBe(true);
  });
  it('accepts can_access=false with challenge_url', () => {
    const r = preflightResultSchema.parse({
      can_access: false,
      reason: 'payment_required',
      resource_id: 'r1',
      holder_id: 'a1',
      price_quote_usd: 0.1,
      accepted_assets: ['USDC'],
      accepted_chains: ['eip155:8453'],
      approval_required: true,
      challenge_url: '/v1/x402/challenge?resource_id=r1',
    });
    expect(r.challenge_url).toBeDefined();
  });
});
