/**
 * Risk360 operator workbench hooks (Kyber).
 *
 * Read the flag-gated risk360 projection plane DIRECTLY via the Kyber `api`
 * client (never the exploration fabric). The plane endpoints resolve to `null`
 * when they cannot serve the request (plane disabled / provider not registered /
 * kind unserved) so pages render a graceful empty state; every other failure
 * surfaces through `useQuery.error`.
 */

import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';
import {
  parseProjectionResult,
  type ProjectionResultModel,
} from '@kyber/features/projection-plane';

const STALE = 60_000;

/** Subject kinds served by the risk360 registry row (mirrors the backend). */
export const RISK360_SUBJECT_KINDS = ['entity', 'relationship', 'cluster', 'population'] as const;
export type Risk360SubjectKind = (typeof RISK360_SUBJECT_KINDS)[number];

function projectionKey(kind: Risk360SubjectKind | '', subjectId: string): string {
  return kind && subjectId.trim()
    ? `risk360:projection:${kind}:${subjectId.trim()}`
    : 'risk360:projection:disabled';
}

/** Run the risk360 projection over one subject when a kind + id are selected. */
export function useRisk360Projection(subjectKind: Risk360SubjectKind | '', subjectId: string) {
  const enabled = Boolean(subjectKind && subjectId.trim());
  return useQuery<ProjectionResultModel | null>({
    key: projectionKey(subjectKind, subjectId),
    fetcher: () =>
      api.risk360
        .projection({ subjectKind, subjectId: subjectId.trim() })
        .then(payload => parseProjectionResult(payload)),
    staleTime: STALE,
    enabled,
  });
}

/**
 * Selector over the risk360 projection result: the parsed section list (by id),
 * plus the claims / dependency state for the subject.
 */
export function useRisk360Sections(subjectKind: Risk360SubjectKind | '', subjectId: string) {
  const projection = useRisk360Projection(subjectKind, subjectId);
  return {
    ...projection,
    result: projection.data,
    sections: projection.data?.sections ?? [],
    claims: projection.data?.claims ?? [],
    dependencies: projection.data?.dependencyState ?? [],
  };
}

/** Plane probe: whether the risk360 provider is registered + contract-compatible. */
export function useRisk360Health() {
  return useQuery<unknown>({
    key: 'risk360:health',
    fetcher: () => api.risk360.health(),
    staleTime: STALE,
  });
}
