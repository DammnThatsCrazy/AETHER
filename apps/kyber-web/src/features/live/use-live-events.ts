import { useState, useEffect, useCallback, useRef } from 'react';
import type { LiveEvent, EventFilter } from '@kyber/types';
import { useWebSocket } from '@kyber/hooks';
import { api } from '@kyber/lib/api/endpoints';

export function useLiveEvents() {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  const [filter, setFilter] = useState<EventFilter>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isPausedRef = useRef(isPaused);
  isPausedRef.current = isPaused;

  // Load the initial authoritative event page from the API.
  useEffect(() => {
    setIsLoading(true);
    setError(null);
    api.analytics.queryEvents({ limit: 50 })
      .then((resp) => {
        const eventsData = resp as { data: unknown[]; pagination?: { total: number; limit: number; has_more: boolean } };
        const seeded = (eventsData.data ?? []).filter(
          (e): e is LiveEvent => typeof e === 'object' && e !== null && 'id' in e,
        );
        setEvents(seeded.slice(0, 200));
        setIsLoading(false);
      })
      .catch((err) => {
        setEvents([]);
        setError(err instanceof Error ? err.message : 'Failed to load live events');
        setIsLoading(false);
      });
  }, []);

  const handleMessage = useCallback((data: unknown) => {
    if (isPausedRef.current) return;
    const event = data as LiveEvent;
    if (event && typeof event === 'object' && 'id' in event) {
      setEvents(prev => [event, ...prev].slice(0, 200));
    }
  }, []);

  const { status: wsStatus } = useWebSocket({
    path: '/ws/v1/analytics/events',
    onMessage: handleMessage,
    enabled: true,
  });

  const filteredEvents = events.filter(e => {
    if (filter.types && filter.types.length > 0 && !filter.types.includes(e.type)) return false;
    if (filter.severities && filter.severities.length > 0 && !filter.severities.includes(e.severity)) return false;
    if (filter.controllers && filter.controllers.length > 0 && e.controller && !filter.controllers.includes(e.controller)) return false;
    if (filter.search && !e.title.toLowerCase().includes(filter.search.toLowerCase()) && !e.description.toLowerCase().includes(filter.search.toLowerCase())) return false;
    if (filter.pinnedOnly && !e.pinned) return false;
    return true;
  });

  const pinnedEvents = events.filter(e => e.pinned);

  return {
    events: filteredEvents,
    allEvents: events,
    pinnedEvents,
    isPaused,
    setIsPaused,
    filter,
    setFilter,
    wsStatus,
    isLoading,
    error,
    totalCount: events.length,
  };
}
