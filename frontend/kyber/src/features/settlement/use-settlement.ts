import { useCallback, useEffect, useState } from 'react';
import { isLocalMocked } from '@kyber/lib/env';
import { settlementApi } from '@kyber/lib/api/settlement';
import type { Settlement } from '@kyber/lib/schemas/commerce';
import { fixtureSettlementList, fixtureStuckSettlements } from '@kyber/fixtures/settlement';

export interface StuckSettlement {
  settlement_id: string;
  state: string;
  created_at: string;
  age_seconds: number;
  resource_id?: string | null | undefined;
  amount?: number | null | undefined;
}

export interface UseSettlementResult {
  readonly settlements: readonly Settlement[];
  readonly stuckSettlements: readonly StuckSettlement[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly mode: 'mocked' | 'live';
  refresh(): Promise<void>;
  get(settlementId: string): Promise<Settlement>;
  settle(receiptId: string): Promise<Settlement>;
  refreshStuck(timeoutSeconds?: number): Promise<void>;
}

export function useSettlement(): UseSettlementResult {
  const [settlements, setSettlements] = useState<Settlement[]>([]);
  const [stuckSettlements, setStuckSettlements] = useState<StuckSettlement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mode: 'mocked' | 'live' = isLocalMocked() ? 'mocked' : 'live';

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (mode === 'mocked') {
        setSettlements([...fixtureSettlementList]);
      }
      // live mode: no list endpoint — populated by refresh of specific IDs from trace context
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load settlements');
    } finally {
      setLoading(false);
    }
  }, [mode]);

  const refreshStuck = useCallback(
    async (timeoutSeconds = 300) => {
      try {
        if (mode === 'mocked') {
          setStuckSettlements([...fixtureStuckSettlements]);
          return;
        }
        const result = await settlementApi.listStuck(timeoutSeconds);
        setStuckSettlements(result.stuck_settlements);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to load stuck settlements');
      }
    },
    [mode]
  );

  useEffect(() => {
    void refresh();
    void refreshStuck();
  }, [refresh, refreshStuck]);

  const get = useCallback(
    async (settlementId: string): Promise<Settlement> => {
      if (mode === 'mocked') {
        const found = fixtureSettlementList.find((s) => s.settlement_id === settlementId);
        if (found) return found;
        return fixtureSettlementList[0]!;
      }
      return settlementApi.get(settlementId);
    },
    [mode]
  );

  const settle = useCallback(
    async (receiptId: string): Promise<Settlement> => {
      if (mode === 'mocked') {
        const next: Settlement = { ...fixtureSettlementList[0]!, receipt_id: receiptId, state: 'settled' };
        setSettlements((prev) => [...prev, next]);
        return next;
      }
      const result = await settlementApi.settle(receiptId);
      await refresh();
      return result;
    },
    [mode, refresh]
  );

  return { settlements, stuckSettlements, loading, error, mode, refresh, get, settle, refreshStuck };
}
