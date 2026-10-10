import { useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

export interface ReliabilityData {
  overview: AnyRecord;
  services: AnyRecord[];
  pipelines: AnyRecord[];
  queues: AnyRecord[];
  slos: AnyRecord[];
  incidents: AnyRecord[];
  runbooks: AnyRecord[];
  postmortems: AnyRecord[];
}

const EMPTY: ReliabilityData = {
  overview: {},
  services: [],
  pipelines: [],
  queues: [],
  slos: [],
  incidents: [],
  runbooks: [],
  postmortems: [],
};

export function useReliability() {
  const [data, setData] = useState<ReliabilityData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([
      api.admin.kyber.reliabilityOverview(),
      api.admin.kyber.reliabilityServices(),
      api.admin.kyber.reliabilityPipelines(),
      api.admin.kyber.reliabilityQueues(),
      api.admin.kyber.reliabilitySlos(),
      api.admin.kyber.incidents(),
      api.admin.kyber.runbooks(),
      api.admin.kyber.postmortems(),
    ])
      .then(([overview, services, pipelines, queues, slos, incidents, runbooks, postmortems]) => {
        if (!active) return;
        setData({
          overview: (overview as AnyRecord) ?? {},
          services: ((services as AnyRecord)?.items ?? []) as AnyRecord[],
          pipelines: ((pipelines as AnyRecord)?.items ?? []) as AnyRecord[],
          queues: ((queues as AnyRecord)?.items ?? []) as AnyRecord[],
          slos: ((slos as AnyRecord)?.items ?? []) as AnyRecord[],
          incidents: ((incidents as AnyRecord)?.items ?? []) as AnyRecord[],
          runbooks: ((runbooks as AnyRecord)?.items ?? []) as AnyRecord[],
          postmortems: ((postmortems as AnyRecord)?.items ?? []) as AnyRecord[],
        });
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return { data, loading, error };
}
