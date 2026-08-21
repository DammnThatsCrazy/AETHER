/**
 * Client-sync feed hook (M5c).
 *
 * Cursor-paged read over GET /v1/client-sync. Events accumulate across pages so
 * a single scroll can show several slices; `reset:true` from the backend clears
 * the local accumulation and starts fresh. Gated by the
 * `enableClientSyncConsumption` feature flag (D8, default OFF): with the flag
 * off the query never fetches, so no HTTP request can fire.
 */
import { useCallback, useEffect, useState } from 'react';
import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import type { ClientSyncResponse, SyncEvent } from '@aether/shared';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';

export function useClientSync(limit = 200) {
  const enabled = isFeatureEnabled('enableClientSyncConsumption');
  const [events, setEvents] = useState<SyncEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [reset, setReset] = useState(false);

  const { data, isLoading, error, refetch } = useQuery<ClientSyncResponse>({
    key: cursor ? `client-sync-${cursor}` : 'client-sync-start',
    fetcher: () => api.clientSync(cursor ?? undefined, limit),
    enabled,
  });

  // Accumulate pages as they arrive; a backend `reset` replaces the slice.
  useEffect(() => {
    if (!data) return;
    if (data.reset) {
      setEvents(data.events);
      setReset(true);
    } else {
      setEvents(prev => [...prev, ...data.events]);
    }
  }, [data]);

  const loadMore = useCallback(() => {
    if (data?.has_more) setCursor(data.cursor);
  }, [data]);

  const reload = useCallback(() => {
    setEvents([]);
    setReset(false);
    setCursor(null);
    refetch();
  }, [refetch]);

  return {
    events,
    cursor,
    reset,
    has_more: data?.has_more ?? false,
    isLoading,
    error,
    reload,
    loadMore,
  };
}
