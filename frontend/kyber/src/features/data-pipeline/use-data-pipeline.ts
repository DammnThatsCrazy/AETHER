import { useState, useEffect, useCallback } from 'react';
import { api } from '@kyber/lib/api/endpoints';

const POLL_INTERVAL_MS = 30_000;

interface DataPipelineState {
  lag: unknown | null;
  isLoading: boolean;
  error: string | null;
}

export function useDataPipeline() {
  const [state, setState] = useState<DataPipelineState>({
    lag: null,
    isLoading: true,
    error: null,
  });

  const fetchLag = useCallback(async () => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));
    try {
      const lag = await api.sdkHealth.pipelineLag();
      setState({ lag, isLoading: false, error: null });
    } catch (err) {
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: err instanceof Error ? err.message : 'Failed to load pipeline lag data',
      }));
    }
  }, []);

  useEffect(() => {
    fetchLag();
    const interval = setInterval(fetchLag, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchLag]);

  return {
    ...state,
    refresh: fetchLag,
  };
}
