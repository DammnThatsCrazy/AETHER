/**
 * Gated projection-surface panel (Kyber) — fetches the server-computed summary
 * through the typed exploration transport and renders it. "Gated": a loading /
 * error / unavailable envelope each render their own honest state; the surface
 * never fabricates content to fill a gap.
 */

import { ErrorState, LoadingState } from '@aether/ui';
import type { ExplorationAnchor } from '@aether/shared/exploration-contract';
import type { ProjectionId } from '@aether/shared/intelligence-projection';
import {
  projectionDisplayName,
  projectionSurfaceEvidenceReadiness,
} from './projection-360-types';
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
  const label = projectionDisplayName(surface);
  const readiness = projectionSurfaceEvidenceReadiness(surface);

  // Honesty gate (M10): while the registries report no evidence-backed data for
  // this surface (relationship/social evidence plane in_flight, social lens
  // capability absent, or an unregistered projection/surface capability) the
  // server query stays DISABLED and the panel renders the explicit "not
  // available / no evidence-backed data yet" state. The hook is still called
  // unconditionally (Rules of Hooks) with `enabled: false`, so no query fires
  // and no follower/engagement/influence value is ever fabricated or defaulted
  // to zero.
  const { data, isLoading, error } = useProjectionSurface(surface, focus, {
    enabled: readiness.ready,
  });

  if (!readiness.ready) {
    return (
      <ProjectionSurfaceSummary
        summary={{
          projectionId: surface,
          available: false,
          reason: readiness.reason ?? 'no_evidence_backed_data_yet',
          sections: [],
        }}
      />
    );
  }

  if (isLoading) return <LoadingState lines={4} />;
  if (error) return <ErrorState title={`${label} unavailable`} message={error} />;
  if (!data) return null;

  return <ProjectionSurfaceSummary summary={data.data} />;
}
