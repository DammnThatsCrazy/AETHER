/**
 * Client-sync feed hook (M5c).
 *
 * Cursor-paged read over GET /v1/client-sync. Events accumulate across pages so
 * a single scroll can show several slices; `reset:true` from the backend clears
 * the local accumulation and starts fresh. Gated by the
 * `enableClientSyncConsumption` feature flag (D8, default OFF): with the flag
 * off the query never fetches, so no HTTP request can fire.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { queryCache, useQuery } from '@aether/ui';
import { useAuth } from '@aether-app/features/auth';
import { useGraphContext } from '@aether/ui/exploration';
import { api } from '@aether-app/lib/api/endpoints';
import type { ClientSyncResponse, SyncEvent } from '@aether/shared';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';

export function clientSyncQueryKey(tenantId: string, sessionScope: string, cursor: string | null): string {
  return [
    'client-sync',
    encodeURIComponent(tenantId),
    encodeURIComponent(sessionScope),
    cursor ? encodeURIComponent(cursor) : 'start',
  ].join(':');
}

export function useClientSync(limit = 200) {
  const { isAuthenticated, user } = useAuth();
  const context = useGraphContext();
  const tenantId = context.scope.tenant_id;
  const sessionScope = user?.id ?? 'anonymous';
  const enabled = isFeatureEnabled('enableClientSyncConsumption')
    && isAuthenticated
    && Boolean(tenantId)
    && Boolean(user?.id);
  const [events, setEvents] = useState<SyncEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [reset, setReset] = useState(false);
  const previousScope = useRef<{ tenantId: string; sessionScope: string } | null>(null);

  const { data, isLoading, error, refetch } = useQuery<ClientSyncResponse>({
    key: clientSyncQueryKey(tenantId, sessionScope, cursor),
    fetcher: () => api.clientSync(cursor ?? undefined, limit),
    enabled,
  });

  useEffect(() => {
    const previous = previousScope.current;
    if (previous !== null
      && (previous.tenantId !== tenantId || previous.sessionScope !== sessionScope)) {
      setEvents([]);
      setCursor(null);
      setReset(false);
      queryCache.invalidatePrefix(clientSyncQueryKey(previous.tenantId, previous.sessionScope, null).replace(/start$/, ''));
    }
    previousScope.current = { tenantId, sessionScope };
  }, [sessionScope, tenantId]);

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
