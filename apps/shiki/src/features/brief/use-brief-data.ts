import { useState, useEffect } from 'react';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockMissionData } from '@shiki/fixtures/mission';

export function useBriefData() {
  const [data, setData] = useState<ReturnType<typeof getMockMissionData> | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isLocalMocked()) {
      setData(getMockMissionData());
      setIsLoading(false);
      return;
    }

    // In live mode, fetch from REST API
    setIsLoading(true);
    fetch('/api/v1/analytics/dashboard/summary')
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((json) => {
        // Map API response to mission data structure
        // For now, fall back to mock data shape until backend wiring is complete
        setData(getMockMissionData());
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load brief data');
        setIsLoading(false);
      });
  }, []);

  return { data, isLoading, error };
}
