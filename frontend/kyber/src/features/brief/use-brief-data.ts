import { useMissionData } from '@kyber/features/mission/use-mission-data';

/**
 * The command brief is a view over the same backend-owned mission payload.
 * Keeping a single live query path prevents this surface from inventing health,
 * graph, alert, or controller values when those APIs have not supplied them.
 */
export function useBriefData() {
  return useMissionData();
}
