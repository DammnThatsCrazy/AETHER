import { useState, useEffect } from 'react';
import type { SystemHealth } from '@shiki/types';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockSystemHealth } from '@shiki/fixtures/health';

export function useDiagnosticsData() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isLocalMocked()) {
      setHealth(getMockSystemHealth());
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    fetch('/api/v1/diagnostics/health')
      .then(r => r.json())
      .then(() => {
        setHealth(getMockSystemHealth());
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load health');
        setIsLoading(false);
      });
  }, []);

  const suppressError = (fingerprint: string) => {
    if (!health) return;
    setHealth({
      ...health,
      errorFingerprints: health.errorFingerprints.map(ef =>
        ef.fingerprint === fingerprint ? { ...ef, suppressed: true } : ef
      ),
    });
  };

  return { health, isLoading, error, suppressError };
}
