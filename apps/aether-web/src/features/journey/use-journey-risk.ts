import { useCallback, useEffect, useState } from 'react';

export interface JourneyRiskSummary {
  journey_id: string;
  risk_score: number | null;
  risk_tier: string | null;
  fraud_status: string | null;
  fraud_disposition: string | null;
  risk_explanation: string | null;
  step_risk_counts: Record<string, number>;
  evaluated_at: string | null;
}

async function fetchJourneyRisk(journeyId: string): Promise<JourneyRiskSummary> {
  const res = await fetch(`/v1/journeys/${encodeURIComponent(journeyId)}/risk`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Journey risk request failed: ${res.status}`);
  const body = await res.json();
  return body.data ?? body;
}

export function useJourneyRisk(journeyId: string | null) {
  const [data, setData] = useState<JourneyRiskSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!journeyId) return;
    setLoading(true);
    setError(null);
    try {
      setData(await fetchJourneyRisk(journeyId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [journeyId]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  return { data, loading, error, reload: load };
}
