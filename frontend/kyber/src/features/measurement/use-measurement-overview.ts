import { useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

interface MeasurementOverviewData {
  overview: AnyRecord;
  quality: AnyRecord;
  health: AnyRecord;
}

const EMPTY: MeasurementOverviewData = { overview: {}, quality: {}, health: {} };

export function useMeasurementOverview(window = '30d') {
  const [data, setData] = useState<MeasurementOverviewData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([
      api.measurement.overview(window),
      api.measurement.quality(window),
      api.measurement.health(),
    ])
      .then(([overview, quality, health]) => {
        if (!active) return;
        setData({ overview: (overview as AnyRecord) ?? {}, quality: (quality as AnyRecord) ?? {}, health: (health as AnyRecord) ?? {} });
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [window]);

  return { data, loading, error };
}
