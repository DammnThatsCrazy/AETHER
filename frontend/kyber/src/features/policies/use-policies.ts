import { useCallback, useEffect, useState } from 'react';
import { policiesApi, type PolicyRecord } from '@kyber/lib/api/policies';
import type { PolicyDecision } from '@kyber/lib/schemas/commerce';

export interface UsePoliciesResult {
  readonly policies: readonly PolicyRecord[];
  readonly loading: boolean;
  readonly error: string | null;
  refresh(): Promise<void>;
  create(body: { name: string; rule_type: string; outcome: string; conditions: Record<string, unknown> }): Promise<PolicyRecord>;
  update(policyId: string, body: Partial<{ name: string; conditions: Record<string, unknown>; active: boolean }>): Promise<PolicyRecord>;
  simulate(body: { resource_id: string; requester_id: string; amount_usd: number; asset_symbol: string; chain: string }): Promise<PolicyDecision>;
}

export function usePolicies(): UsePoliciesResult {
  const [policies, setPolicies] = useState<PolicyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await policiesApi.list();
      setPolicies(items);
    } catch (e) {
      setPolicies([]);
      setError(e instanceof Error ? e.message : 'failed to load policies');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(
    async (body: { name: string; rule_type: string; outcome: string; conditions: Record<string, unknown> }) => {
      setError(null);
      try {
        const result = await policiesApi.create(body);
        await refresh();
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to create policy');
        throw e;
      }
    },
    [refresh]
  );

  const update = useCallback(
    async (policyId: string, body: Partial<{ name: string; conditions: Record<string, unknown>; active: boolean }>) => {
      setError(null);
      try {
        const result = await policiesApi.update(policyId, body);
        await refresh();
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to update policy');
        throw e;
      }
    },
    [refresh]
  );

  const simulate = useCallback(
    async (body: { resource_id: string; requester_id: string; amount_usd: number; asset_symbol: string; chain: string }) =>
      policiesApi.simulate(body),
    []
  );

  return { policies, loading, error, refresh, create, update, simulate };
}
