import { useCallback, useEffect, useState } from 'react';
import { isLocalMocked } from '@kyber/lib/env';
import { entitlementsApi } from '@kyber/lib/api/commerce';
import type { Entitlement } from '@kyber/lib/schemas/commerce';
import { fixtureEntitlement } from '@kyber/fixtures/commerce';

export interface UseEntitlementsResult {
  readonly entitlements: readonly Entitlement[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly mode: 'mocked' | 'live';
  refresh(): Promise<void>;
  revoke(entitlementId: string, reason: string, revokedBy: string): Promise<Entitlement>;
}

export function useEntitlements(holderId: string | null): UseEntitlementsResult {
  const [entitlements, setEntitlements] = useState<Entitlement[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mode: 'mocked' | 'live' = isLocalMocked() ? 'mocked' : 'live';

  const refresh = useCallback(async () => {
    if (!holderId) {
      setEntitlements([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      if (mode === 'mocked') {
        setEntitlements([fixtureEntitlement]);
      } else {
        const items = await entitlementsApi.listForHolder(holderId, true);
        setEntitlements(items);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load entitlements');
    } finally {
      setLoading(false);
    }
  }, [holderId, mode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const revoke = useCallback(
    async (entitlementId: string, reason: string, revokedBy: string) => {
      if (mode === 'mocked') {
        const next = { ...fixtureEntitlement, entitlement_id: entitlementId, status: 'revoked' as const, revoke_reason: reason, revoked_by: revokedBy };
        setEntitlements((prev) => prev.filter((e) => e.entitlement_id !== entitlementId));
        return next;
      }
      const result = await entitlementsApi.revoke(entitlementId, reason, revokedBy);
      await refresh();
      return result;
    },
    [mode, refresh]
  );

  return { entitlements, loading, error, mode, refresh, revoke };
}
