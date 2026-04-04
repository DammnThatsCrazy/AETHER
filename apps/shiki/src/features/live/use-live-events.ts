import { useState, useEffect, useCallback, useRef } from 'react';
import type { LiveEvent, EventFilter } from '@shiki/types';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockEvents } from '@shiki/fixtures/events';
import { useWebSocket } from '@shiki/hooks';

export function useLiveEvents() {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  const [filter, setFilter] = useState<EventFilter>({});
  const isPausedRef = useRef(isPaused);
  isPausedRef.current = isPaused;

  // In mocked mode, load fixtures and simulate stream
  useEffect(() => {
    if (!isLocalMocked()) return;
    const mockEvents = getMockEvents();
    setEvents(mockEvents.slice(0, 10));

    let idx = 10;
    const interval = setInterval(() => {
      if (isPausedRef.current) return;
      const nextEvent = mockEvents[idx % mockEvents.length];
      if (nextEvent) {
        const refreshed: LiveEvent = {
          ...nextEvent,
          id: `${nextEvent.id}-${Date.now()}`,
          timestamp: new Date().toISOString(),
        };
        setEvents(prev => [refreshed, ...prev].slice(0, 200));
      }
      idx++;
    }, 2500);

    return () => clearInterval(interval);
  }, []);

  // In live mode, use WebSocket
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
    enabled: !isLocalMocked(),
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
    totalCount: events.length,
  };
}
