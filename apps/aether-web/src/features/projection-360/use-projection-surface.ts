/**
 * Hook over the typed exploration transport for a projection surface.
 *
 * Mirrors the exploration-fabric precedent (features/campaigns/
 * use-campaign-exploration.ts): the shared provider supplies the tenant-scoped
 * base context + authenticated exploration client; this hook re-targets the
 * context to the requested projection surface (outcome360 / economic360 /
 * infrastructure360) and optionally focuses the projection subject, then reads
 * the server-computed projection summary through queryLatest. The client never
 * computes anything — it only names the typed envelope the server returned.
 */

import { useMemo } from 'react';
import { useQuery } from '@aether/ui';
import {
  encodeExplorationContext,
  useExplorationClient,
  useExplorationContext,
} from '@aether/ui/exploration';
import type {
  ExplorationAnchor,
  ExplorationContextV1,
} from '@aether/shared/exploration-contract';
import type { ProjectionId } from '@aether/shared/intelligence-projection';
import {
  type ProjectionSurfaceEnvelope,
  type ProjectionSurfaceSummary,
} from './projection-360-types';

/**
 * Re-target a tenant-scoped exploration context at a projection surface.
 * The surface id is the registered exploration surface (= the projection id for
 * the three implemented 360s). An optional anchor focuses the projection
 * subject (e.g. a campaign); the selection is otherwise preserved untouched.
 */
export function projectionSurfaceContext(
  base: ExplorationContextV1,
  surface: ProjectionId,
  focus?: ExplorationAnchor | null,
): ExplorationContextV1 {
  const selection =
    base.selection != null
      ? { ...base.selection, ...(focus ? { focused: focus } : {}) }
      : focus
        ? { focused: focus }
        : null;
  return {
    ...base,
    scope: { ...base.scope, surface },
    ...(selection ? { selection } : {}),
  };
}

/**
 * Read the server-computed projection summary for a projection surface.
 *
 * @param surface  the registered projection surface (outcome360 / economic360 /
 *                 infrastructure360)
 * @param focus    optional subject anchor the projection is asked about
 *                 (e.g. { kind: 'campaign', id })
 */
export function useProjectionSurface(
  surface: ProjectionId,
  focus?: ExplorationAnchor | null,
  options?: { readonly enabled?: boolean },
) {
  const client = useExplorationClient();
  const base = useExplorationContext();
  const context = useMemo(() => projectionSurfaceContext(base, surface, focus), [base, surface, focus]);
  const contextKey = encodeExplorationContext(context);
  const enabled = options?.enabled ?? true;
  const result = useQuery<ProjectionSurfaceEnvelope>({
    key: `projection:${surface}:${contextKey}:first`,
    fetcher: () => client.queryLatest<ProjectionSurfaceSummary>(
      { context, limit: 50 },
      { key: `aether:${surface}` },
    ),
    staleTime: 30_000,
    // Honesty gate (M10): when the client registry says the surface has no
    // evidence-backed data yet, disable the query entirely — the surface never
    // asks for (or renders) content it cannot evidence.
    enabled,
  });
  return { ...result, client, context };
}
