/**
 * Fraud360 operator consolidation hooks (Kyber).
 *
 * Read the flag-gated fraud360 domain-synthesis projection plane DIRECTLY via
 * the Kyber `api` client (never the exploration fabric). The plane endpoints
 * resolve to `null` when they cannot serve the request (plane disabled /
 * provider not registered / kind unserved) so pages render a graceful empty
 * state; every other failure surfaces through `useQuery.error`.
 */

import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';
import {
  parseProjectionResult,
  type ProjectionResultModel,
} from '@kyber/features/projection-plane';

const STALE = 60_000;

/** Subject kinds served by the fraud360 registry row (mirrors the backend). */
export const FRAUD360_SUBJECT_KINDS = ['entity', 'relationship', 'agent'] as const;
export type Fraud360SubjectKind = (typeof FRAUD360_SUBJECT_KINDS)[number];

function projectionKey(kind: Fraud360SubjectKind | '', subjectId: string): string {
  return kind && subjectId.trim()
    ? `fraud360:projection:${kind}:${subjectId.trim()}`
    : 'fraud360:projection:disabled';
}

/** Run the fraud360 projection over one subject when a kind + id are selected. */
export function useFraud360Projection(subjectKind: Fraud360SubjectKind | '', subjectId: string) {
  const enabled = Boolean(subjectKind && subjectId.trim());
  return useQuery<ProjectionResultModel | null>({
    key: projectionKey(subjectKind, subjectId),
    fetcher: () =>
      api.fraud360
        .projection({ subjectKind, subjectId: subjectId.trim() })
        .then(payload => parseProjectionResult(payload)),
    staleTime: STALE,
    enabled,
  });
}

/**
 * Selector over the fraud360 projection result: the parsed section list (by id),
 * plus the claims / dependency state for the subject.
 */
export function useFraud360Sections(subjectKind: Fraud360SubjectKind | '', subjectId: string) {
  const projection = useFraud360Projection(subjectKind, subjectId);
  return {
    ...projection,
    result: projection.data,
    sections: projection.data?.sections ?? [],
    claims: projection.data?.claims ?? [],
    dependencies: projection.data?.dependencyState ?? [],
  };
}

/** Plane probe: whether the fraud360 provider is registered + contract-compatible. */
export function useFraud360Health() {
  return useQuery<unknown>({
    key: 'fraud360:health',
    fetcher: () => api.fraud360.health(),
    staleTime: STALE,
  });
}
