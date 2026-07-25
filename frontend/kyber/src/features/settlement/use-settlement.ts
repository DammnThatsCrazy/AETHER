import { useCallback, useEffect, useState } from 'react';
import { settlementApi } from '@kyber/lib/api/settlement';
import type { Settlement } from '@kyber/lib/schemas/commerce';

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

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSettlements(await settlementApi.list());
    } catch (e) {
      setSettlements([]);
      setError(e instanceof Error ? e.message : 'failed to load settlements');
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshStuck = useCallback(
    async (timeoutSeconds = 300) => {
      try {
        const result = await settlementApi.listStuck(timeoutSeconds);
        setStuckSettlements(result.stuck_settlements);
      } catch (e) {
        setStuckSettlements([]);
        setError(e instanceof Error ? e.message : 'failed to load stuck settlements');
      }
    },
    []
  );

  useEffect(() => {
    void refresh();
    void refreshStuck();
  }, [refresh, refreshStuck]);

  const get = useCallback(async (settlementId: string): Promise<Settlement> => {
    try {
      const result = await settlementApi.get(settlementId);
      setSettlements((current) => [
        ...current.filter((item) => item.settlement_id !== result.settlement_id),
        result,
      ]);
      setError(null);
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load settlement');
      throw e;
    }
  }, []);

  const settle = useCallback(
    async (receiptId: string): Promise<Settlement> => {
      try {
        const result = await settlementApi.settle(receiptId);
        setSettlements((current) => [
          ...current.filter((item) => item.settlement_id !== result.settlement_id),
          result,
        ]);
        setError(null);
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to settle receipt');
        throw e;
      }
    },
    []
  );

  return { settlements, stuckSettlements, loading, error, refresh, get, settle, refreshStuck };
}
