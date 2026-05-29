import { useState, useEffect, useCallback } from 'react';
import type {
  SDKFleetStatus,
  DriftIncident,
  SDKHealthScore,
  SDKRolloutStatus,
} from '@kyber/types/sdk-health';
import { api } from '@kyber/lib/api/endpoints';

const POLL_INTERVAL_MS = 30_000;

interface SDKHealthState {
  fleet: SDKFleetStatus | null;
  driftIncidents: DriftIncident[];
  selectedScore: SDKHealthScore | null;
  rolloutStatus: SDKRolloutStatus | null;
  isLoading: boolean;
  error: string | null;
}

export function useSdkHealth(sdkId?: string) {
  const [state, setState] = useState<SDKHealthState>({
    fleet: null,
    driftIncidents: [],
    selectedScore: null,
    rolloutStatus: null,
    isLoading: true,
    error: null,
  });

  const fetchAll = useCallback(async () => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));
    try {
      const [fleetResp, incidentsResp, rolloutResp] = await Promise.all([
        api.sdkHealth.fleet(),
        api.sdkHealth.driftIncidents(),
        api.sdkHealth.rolloutStatus(),
      ]);

      let selectedScore: SDKHealthScore | null = null;
      if (sdkId) {
        try {
          selectedScore = await api.sdkHealth.sdkScore(sdkId);
        } catch {
          // Non-fatal — SDK may not have checked in yet
        }
      }

      setState({
        fleet: fleetResp as SDKFleetStatus,
        driftIncidents: (incidentsResp as { incidents: DriftIncident[] }).incidents ?? [],
        selectedScore,
        rolloutStatus: rolloutResp as SDKRolloutStatus,
        isLoading: false,
        error: null,
      });
    } catch (err) {
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: err instanceof Error ? err.message : 'Failed to load SDK health data',
      }));
    }
  }, [sdkId]);

  // Initial fetch + polling
  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchAll]);

  return {
    ...state,
    refresh: fetchAll,
  };
}
