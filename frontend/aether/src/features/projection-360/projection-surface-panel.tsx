/**
 * Gated projection-surface panel — fetches the server-computed summary through
 * the typed exploration transport and renders it. "Gated": a loading / error /
 * unavailable envelope each render their own honest state; the surface never
 * fabricates content to fill a gap.
 */

import { ErrorState, LoadingState } from '@aether/ui';
import type { ExplorationAnchor } from '@aether/shared/exploration-contract';
import type { ProjectionId } from '@aether/shared/intelligence-projection';
import { projectionDisplayName } from './projection-360-types';
import { ProjectionSurfaceSummary } from './projection-surface-summary';
import { useProjectionSurface } from './use-projection-surface';

export interface ProjectionSurfacePanelProps {
  /** The registered projection surface (outcome360 / economic360 / infrastructure360). */
  readonly surface: ProjectionId;
  /** Optional subject anchor the projection is asked about (e.g. a campaign). */
  readonly focus?: ExplorationAnchor | null;
}

/**
 * Mount a projection surface's server state. `focus` is the tenant-scoped
 * subject the projection runs over — pages pass their own route entity.
 */
export function ProjectionSurfacePanel({ surface, focus }: ProjectionSurfacePanelProps) {
  const { data, isLoading, error } = useProjectionSurface(surface, focus);
  const label = projectionDisplayName(surface);

  if (isLoading) return <LoadingState lines={4} />;
  if (error) return <ErrorState title={`${label} unavailable`} message={error} />;
  if (!data) return null;

  return <ProjectionSurfaceSummary summary={data.data} />;
}
