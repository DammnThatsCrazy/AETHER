import { useCallback, useEffect, useState } from 'react';
import { entitlementsApi } from '@kyber/lib/api/commerce';
import type { Entitlement } from '@kyber/lib/schemas/commerce';

export interface UseEntitlementsResult {
  readonly entitlements: readonly Entitlement[];
  readonly loading: boolean;
  readonly error: string | null;
  refresh(): Promise<void>;
  revoke(entitlementId: string, reason: string, revokedBy: string): Promise<Entitlement>;
}

export function useEntitlements(holderId: string | null): UseEntitlementsResult {
  const [entitlements, setEntitlements] = useState<Entitlement[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!holderId) {
      setEntitlements([]);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const items = await entitlementsApi.listForHolder(holderId, true);
      setEntitlements(items);
    } catch (e) {
      setEntitlements([]);
      setError(e instanceof Error ? e.message : 'failed to load entitlements');
    } finally {
      setLoading(false);
    }
  }, [holderId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const revoke = useCallback(
    async (entitlementId: string, reason: string, revokedBy: string) => {
      setError(null);
      try {
        const result = await entitlementsApi.revoke(entitlementId, reason, revokedBy);
        await refresh();
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to revoke entitlement');
        throw e;
      }
    },
    [refresh]
  );

  return { entitlements, loading, error, refresh, revoke };
}
