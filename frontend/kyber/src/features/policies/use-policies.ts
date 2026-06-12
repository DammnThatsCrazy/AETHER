import { useCallback, useEffect, useState } from 'react';
import { isLocalMocked } from '@kyber/lib/env';
import { policiesApi, type PolicyRecord } from '@kyber/lib/api/policies';
import type { PolicyDecision } from '@kyber/lib/schemas/commerce';
import { fixturePolicyDecision } from '@kyber/fixtures/commerce';

const fixturePolicyRecords: PolicyRecord[] = [
  {
    policy_id: 'pol_fx_mandatory_approval',
    tenant_id: 'tenant_kyber_mock',
    name: 'Mandatory Approval — All Spend Classes',
    rule_type: 'approval_gate',
    outcome: 'require_approval',
    conditions: { spend_class: '*', day1_ga: true },
    active: true,
    created_at: '2026-04-04T00:00:00Z',
  },
  {
    policy_id: 'pol_fx_asset_compat',
    tenant_id: 'tenant_kyber_mock',
    name: 'Asset Compatibility Check',
    rule_type: 'asset_filter',
    outcome: 'deny',
    conditions: { blocked_assets: [] },
    active: true,
    created_at: '2026-04-04T00:00:00Z',
  },
];

export interface UsePoliciesResult {
  readonly policies: readonly PolicyRecord[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly mode: 'mocked' | 'live';
  refresh(): Promise<void>;
  create(body: { name: string; rule_type: string; outcome: string; conditions: Record<string, unknown> }): Promise<PolicyRecord>;
  update(policyId: string, body: Partial<{ name: string; conditions: Record<string, unknown>; active: boolean }>): Promise<PolicyRecord>;
  simulate(body: { resource_id: string; requester_id: string; amount_usd: number; asset_symbol: string; chain: string }): Promise<PolicyDecision>;
}

export function usePolicies(): UsePoliciesResult {
  const [policies, setPolicies] = useState<PolicyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mode: 'mocked' | 'live' = isLocalMocked() ? 'mocked' : 'live';

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (mode === 'mocked') {
        setPolicies([...fixturePolicyRecords]);
      } else {
        const items = await policiesApi.list();
        setPolicies(items);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load policies');
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(
    async (body: { name: string; rule_type: string; outcome: string; conditions: Record<string, unknown> }) => {
      if (mode === 'mocked') {
        const next: PolicyRecord = {
          ...fixturePolicyRecords[0]!,
          policy_id: `pol_fx_new_${Date.now()}`,
          name: body.name,
          rule_type: body.rule_type,
          outcome: body.outcome,
          conditions: body.conditions,
          active: true,
          created_at: new Date().toISOString(),
        };
        setPolicies((prev) => [...prev, next]);
        return next;
      }
      const result = await policiesApi.create(body);
      await refresh();
      return result;
    },
    [mode, refresh]
  );

  const update = useCallback(
    async (policyId: string, body: Partial<{ name: string; conditions: Record<string, unknown>; active: boolean }>) => {
      if (mode === 'mocked') {
        const base = fixturePolicyRecords.find((p) => p.policy_id === policyId) ?? fixturePolicyRecords[0]!;
        const next: PolicyRecord = { ...base, policy_id: policyId, ...body, active: body.active ?? base.active };
        setPolicies((prev) => prev.map((p) => (p.policy_id === policyId ? next : p)));
        return next;
      }
      const result = await policiesApi.update(policyId, body);
      await refresh();
      return result;
    },
    [mode, refresh]
  );

  const simulate = useCallback(
    async (body: { resource_id: string; requester_id: string; amount_usd: number; asset_symbol: string; chain: string }) => {
      if (mode === 'mocked') return fixturePolicyDecision;
      return policiesApi.simulate(body);
    },
    [mode]
  );

  return { policies, loading, error, mode, refresh, create, update, simulate };
}
