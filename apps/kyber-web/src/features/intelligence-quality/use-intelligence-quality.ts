import { useCallback, useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

export interface IntelligenceQualityData {
  overview: AnyRecord;
  tenants: AnyRecord[];
  driftEvents: AnyRecord[];
  schemaDrift: AnyRecord;
  identity: AnyRecord;
  graph: AnyRecord;
  recommendations: AnyRecord;
  outcomes: AnyRecord;
  playbooks: AnyRecord;
  contamination: AnyRecord;
}

const EMPTY: IntelligenceQualityData = {
  overview: {},
  tenants: [],
  driftEvents: [],
  schemaDrift: {},
  identity: {},
  graph: {},
  recommendations: {},
  outcomes: {},
  playbooks: {},
  contamination: {},
};

export function useIntelligenceQuality() {
  const [data, setData] = useState<IntelligenceQualityData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      api.admin.kyber.intelligenceQualityOverview(),
      api.admin.kyber.intelligenceQualityTenants(),
      api.admin.kyber.intelligenceQualityDriftEvents(),
      api.admin.kyber.intelligenceQualitySchemaDrift(),
      api.admin.kyber.intelligenceQualityIdentity(),
      api.admin.kyber.intelligenceQualityGraph(),
      api.admin.kyber.intelligenceQualityRecommendations(),
      api.admin.kyber.intelligenceQualityOutcomes(),
      api.admin.kyber.intelligenceQualityPlaybooks(),
      api.admin.kyber.intelligenceQualityContamination(),
    ])
      .then(([overview, tenants, drift, schemaDrift, identity, graph, recommendations, outcomes, playbooks, contamination]) => {
        if (!active) return;
        setData({
          overview: (overview as AnyRecord) ?? {},
          tenants: ((tenants as AnyRecord)?.items ?? []) as AnyRecord[],
          driftEvents: ((drift as AnyRecord)?.items ?? []) as AnyRecord[],
          schemaDrift: (schemaDrift as AnyRecord) ?? {},
          identity: (identity as AnyRecord) ?? {},
          graph: (graph as AnyRecord) ?? {},
          recommendations: (recommendations as AnyRecord) ?? {},
          outcomes: (outcomes as AnyRecord) ?? {},
          playbooks: (playbooks as AnyRecord) ?? {},
          contamination: (contamination as AnyRecord) ?? {},
        });
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  useEffect(() => load(), [load]);

  return { data, loading, error, reload: load };
}
