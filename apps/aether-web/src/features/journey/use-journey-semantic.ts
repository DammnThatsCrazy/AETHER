import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import type { SemanticNodeOverlay, SemanticOverlayResponse } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export type { SemanticNodeOverlay, SemanticOverlayResponse };

/**
 * Entity-level semantic overlay for the profile being explored — per-node
 * stance, topics, confidence and evidence refs from
 * POST /v1/graph/semantic-overlay. Entity-level only: per-step journey
 * annotation is not exposed by the backend.
 */
export function useJourneySemantic(profileId: string) {
  return useQuery({
    key: `journey-semantic:${profileId}`,
    fetcher: () => api.graph.semanticOverlay({ subject_ref: profileId }),
    staleTime: STALE,
    enabled: !!profileId,
  });
}
