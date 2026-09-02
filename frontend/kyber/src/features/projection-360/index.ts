/**
 * Projection-surface seams (S6, Kyber) — typed, gated renderers for the three
 * implemented intelligence projections (outcome360 / economic360 /
 * infrastructure360) from SERVER-COMPUTED projection state. Pages reuse the
 * canonical exploration transport; the client never recomputes content and
 * never synthesizes a metric.
 */

export { projectionSurfaceContext, useProjectionSurface } from './use-projection-surface';
export type { ProjectionSurfaceEnvelope } from './projection-360-types';
export { ProjectionSurfaceSummary } from './projection-surface-summary';
export type { ProjectionSurfaceSummaryProps } from './projection-surface-summary';
export { ProjectionSurfacePanel } from './projection-surface-panel';
export type { ProjectionSurfacePanelProps } from './projection-surface-panel';
