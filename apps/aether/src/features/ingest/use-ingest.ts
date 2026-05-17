import { useMutation } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export function useIngestEvent() {
  return useMutation({
    mutationFn: (event: { event_type: string; session_id: string; properties?: Record<string, unknown>; timestamp?: string; user_id?: string; device_id?: string }) =>
      api.ingest.event(event),
  });
}

export function useIngestBatch() {
  return useMutation({
    mutationFn: (events: unknown[]) => api.ingest.batch(events),
  });
}

export function useIngestFeed() {
  return useMutation({
    mutationFn: (feed: { source: string; entity_type: string; data: Record<string, unknown> }) =>
      api.ingest.feed(feed),
  });
}
