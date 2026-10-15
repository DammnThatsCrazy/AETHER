/**
 * Typed client view of a projection-surface exploration envelope (Kyber).
 *
 * A 360 is an intelligence projection over canonical Aether truth — never a
 * competing system of record. The exploration fabric executes the projection
 * server-side (S1 engine over the registered providers) and returns a
 * server-computed projection SUMMARY as the envelope's `data` for the
 * projection surfaces (outcome360 / economic360 / infrastructure360):
 * digest, lens frame, temporal mode, degradation state, per-section typed
 * states, and suppressed sections — NOT full section bodies.
 *
 * This module names that payload so a surface renders ONLY fields the typed
 * envelope declares. Numbers, digests and section states come from the server;
 * the client never recomputes content and never synthesizes a metric.
 */

import type { ExplorationResultEnvelope } from '@aether/shared/exploration-contract';
import type { ProjectionId, SectionState } from '@aether/shared/intelligence-projection';
import { intelligenceProjectionDefinitions } from '@aether/shared/intelligence-projections_generated';
import { surfaceCapabilities } from '@aether/shared/surface-capabilities';

/** Engine degradation level the projection surface reports (mirrors ProjectionDegradation.level). */
export type ProjectionDegradationLevel = 'none' | 'partial' | 'full';

/** One rendered projection section (state only — never a client-synthesized body). */
export interface ProjectionSurfaceSection {
  readonly id: string;
  readonly state: SectionState;
}

/** Dependency state of a sibling projection the result depends on. */
export interface ProjectionSurfaceDependency {
  readonly projectionId: ProjectionId;
  readonly state: SectionState;
}

/**
 * The projection summary the exploration surface returns as `envelope.data`.
 * `available:false` means the projection could not be satisfied this run and
 * carries a static, content-free `reason` (never an echoed provider
 * diagnostic); `available:true` carries the digest / lens / temporal frame and
 * per-section typed states.
 */
export interface ProjectionSurfaceSummary {
  readonly projectionId: ProjectionId;
  readonly available: boolean;
  readonly reason?: string | null;
  readonly digest?: string | null;
  readonly asOf?: string | null;
  readonly lensIds?: string[] | null;
  readonly temporalMode?: string | null;
  readonly degradationState?: ProjectionDegradationLevel | null;
  readonly sections: readonly ProjectionSurfaceSection[];
  readonly suppressedSections?: readonly string[] | null;
  readonly dependencyState?: readonly ProjectionSurfaceDependency[] | null;
}

/**
 * The typed exploration envelope for a projection surface. Reuses the canonical
 * ExplorationResultEnvelope transport — the same client the exploration fabric
 * precedent already uses; nothing new is invented.
 */
export type ProjectionSurfaceEnvelope = ExplorationResultEnvelope<ProjectionSurfaceSummary>;

/**
 * Display name from the generated projection registry — never a client-typed
 * label literal, so the header can never drift from the canonical registry.
 */
export function projectionDisplayName(projectionId: ProjectionId): string {
  return intelligenceProjectionDefinitions[projectionId]?.displayName ?? projectionId;
}

/**
 * Why a projection surface cannot yet render evidence-backed content (M10).
 *
 * - `projection_not_registered` — the surface id is not a registered
 *   intelligence projection.
 * - `surface_capability_not_registered` — the projection's declared surface(s)
 *   are not yet registered with the exploration fabric.
 * - `no_evidence_backed_data_yet` — the Social360 / relationship-fidelity
 *   (relationship_360) evidence plane is in_flight; there is no evidence-backed
 *   data yet. This is the honest unavailable state: the surface never fabricates
 *   follower counts, engagement, or influence values, and never defaults missing
 *   data to zero. Lens-registry entries alone (M9) are not evidence — while the
 *   lens capability list is empty/absent the surface stays unavailable.
 */
export type ProjectionSurfaceUnavailableReason =
  | 'projection_not_registered'
  | 'surface_capability_not_registered'
  | 'no_evidence_backed_data_yet';

/** Client-side evidence-readiness decision for a projection surface. */
export interface ProjectionSurfaceEvidenceReadiness {
  readonly ready: boolean;
  readonly reason?: ProjectionSurfaceUnavailableReason | null;
}

/**
 * Client-side honesty gate over the generated projection registry + the
 * surface-capability registry.
 *
 * A surface may only query for / render evidence-backed content when it is a
 * registered intelligence projection whose declared surface capability exists
 * on the exploration fabric AND — for relationship_360-kind surfaces (the
 * Social360 / relationship-fidelity product surfaces) — the canonical data
 * plane is `implemented`. Until then the surface degrades to the explicit
 * "not available / no evidence-backed data yet" state. This keeps the gate
 * generic (no per-surface hardcoding): it reads the same registries the M9
 * sibling extends, so a missing social lens entry degrades gracefully.
 */
export function projectionSurfaceEvidenceReadiness(
  surface: ProjectionId,
): ProjectionSurfaceEvidenceReadiness {
  const definition = intelligenceProjectionDefinitions[surface];
  if (!definition) {
    return { ready: false, reason: 'projection_not_registered' };
  }
  const hasSurfaceCapability = definition.surfaceIds.some((id) =>
    Object.prototype.hasOwnProperty.call(surfaceCapabilities, id),
  );
  if (!hasSurfaceCapability) {
    return { ready: false, reason: 'surface_capability_not_registered' };
  }
  const isRelationshipFidelitySurface = definition.projectionKind === 'relationship_360';
  if (isRelationshipFidelitySurface && definition.implementationState !== 'implemented') {
    return { ready: false, reason: 'no_evidence_backed_data_yet' };
  }
  return { ready: true, reason: null };
}
