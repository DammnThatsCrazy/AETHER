import { useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

interface JourneyHealthData {
  overview: AnyRecord;
  sdkParity: AnyRecord;
  droppedEvents: AnyRecord;
}

const EMPTY: JourneyHealthData = {
  overview: {},
  sdkParity: {},
  droppedEvents: { items: [], count: 0 },
};

export function useJourneyHealth() {
  const [data, setData] = useState<JourneyHealthData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([
      api.journeyHealth.overview(),
      api.journeyHealth.sdkParity(),
      api.journeyHealth.droppedEvents(),
    ])
      .then(([overview, sdkParity, droppedEvents]) => {
        if (!active) return;
        setData({ overview: (overview as AnyRecord) ?? {}, sdkParity: (sdkParity as AnyRecord) ?? {}, droppedEvents: (droppedEvents as AnyRecord) ?? { items: [], count: 0 } });
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  return { data, loading, error };
}
