/**
 * DO NOT EDIT — generated from packages/shared/contracts/surface-capability-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

import type { FilterFieldCategory } from './filter-fields';

export const surfaceCapabilitiesContractVersion = '1.0.0' as const;

/** Exploration surfaces registered with the fabric (sorted). */
export const explorationSurfaceIds = [
  'campaign360',
  'cluster360',
  'comparison_workbench',
  'geo',
  'graph',
  'journeys',
  'product_intelligence',
  'profile360',
  'temporal_observatory',
  'timeline',
] as const;
export type ExplorationSurfaceId = typeof explorationSurfaceIds[number];

/** Temporal query modes a surface may support. */
export const explorationTemporalModes = ['window', 'as_of', 'compare', 'relative'] as const;
export type ExplorationTemporalMode = typeof explorationTemporalModes[number];

/** Render views a surface may support. */
export const explorationViews = [
  'graph',
  'table',
  'map',
  'timeline',
  'flow',
  'comparison',
] as const;
export type ExplorationView = typeof explorationViews[number];

/** What the fabric did with one filter on one surface — never silently dropped. */
export const filterDispositions = [
  'applied',
  'translated',
  'unsupported',
  'suppressed',
  'not_applicable',
] as const;
export type FilterDisposition = typeof filterDispositions[number];

/** Declared capabilities of one exploration surface. */
export interface SurfaceCapability {
  surfaceId: ExplorationSurfaceId;
  supportedFieldCategories: readonly FilterFieldCategory[];
  supportedTemporalModes: readonly ExplorationTemporalMode[];
  supportedViews: readonly ExplorationView[];
  supportsFacets: boolean;
  supportsComparison: boolean;
  supportsSelectionSets: boolean;
  supportsSavedViews: boolean;
  supportsExport: boolean;
}

export const surfaceCapabilities: Record<ExplorationSurfaceId, SurfaceCapability> = {
  campaign360: {
    surfaceId: 'campaign360',
    supportedFieldCategories: ['entity', 'time', 'geography', 'campaign', 'economic', 'truth'],
    supportedTemporalModes: ['window', 'compare', 'relative'],
    supportedViews: ['table', 'flow', 'timeline'],
    supportsFacets: true,
    supportsComparison: true,
    supportsSelectionSets: true,
    supportsSavedViews: true,
    supportsExport: true,
  },
  cluster360: {
    surfaceId: 'cluster360',
    supportedFieldCategories: ['entity', 'time', 'graph', 'risk', 'truth'],
    supportedTemporalModes: ['window', 'as_of'],
    supportedViews: ['graph', 'table'],
    supportsFacets: true,
    supportsComparison: true,
    supportsSelectionSets: true,
    supportsSavedViews: false,
    supportsExport: true,
  },
  comparison_workbench: {
    surfaceId: 'comparison_workbench',
    supportedFieldCategories: ['entity', 'time', 'geography', 'device', 'graph', 'risk', 'campaign', 'economic', 'truth'],
    supportedTemporalModes: ['window', 'as_of', 'compare', 'relative'],
    supportedViews: ['comparison', 'table', 'graph', 'timeline'],
    supportsFacets: true,
    supportsComparison: true,
    supportsSelectionSets: true,
    supportsSavedViews: true,
    supportsExport: true,
  },
  geo: {
    surfaceId: 'geo',
    supportedFieldCategories: ['entity', 'time', 'geography', 'campaign', 'risk'],
    supportedTemporalModes: ['window', 'compare', 'relative'],
    supportedViews: ['map', 'table'],
    supportsFacets: true,
    supportsComparison: true,
    supportsSelectionSets: true,
    supportsSavedViews: true,
    supportsExport: true,
  },
  graph: {
    surfaceId: 'graph',
    supportedFieldCategories: ['entity', 'time', 'geography', 'device', 'graph', 'risk', 'campaign', 'economic', 'truth'],
    supportedTemporalModes: ['window', 'as_of', 'relative'],
    supportedViews: ['graph', 'table'],
    supportsFacets: true,
    supportsComparison: false,
    supportsSelectionSets: true,
    supportsSavedViews: true,
    supportsExport: true,
  },
  journeys: {
    surfaceId: 'journeys',
    supportedFieldCategories: ['entity', 'time', 'device', 'campaign', 'truth'],
    supportedTemporalModes: ['window', 'relative'],
    supportedViews: ['flow', 'table', 'timeline'],
    supportsFacets: true,
    supportsComparison: true,
    supportsSelectionSets: true,
    supportsSavedViews: true,
    supportsExport: true,
  },
  product_intelligence: {
    surfaceId: 'product_intelligence',
    supportedFieldCategories: ['entity', 'time', 'device', 'campaign', 'economic', 'truth'],
    supportedTemporalModes: ['window', 'compare', 'relative'],
    supportedViews: ['table', 'timeline', 'flow'],
    supportsFacets: true,
    supportsComparison: true,
    supportsSelectionSets: true,
    supportsSavedViews: true,
    supportsExport: true,
  },
  profile360: {
    surfaceId: 'profile360',
    supportedFieldCategories: ['entity', 'time', 'geography', 'device', 'campaign', 'economic', 'risk', 'truth'],
    supportedTemporalModes: ['window', 'as_of', 'relative'],
    supportedViews: ['table', 'timeline'],
    supportsFacets: false,
    supportsComparison: true,
    supportsSelectionSets: false,
    supportsSavedViews: false,
    supportsExport: true,
  },
  temporal_observatory: {
    surfaceId: 'temporal_observatory',
    supportedFieldCategories: ['entity', 'time', 'truth'],
    supportedTemporalModes: ['window', 'as_of', 'compare', 'relative'],
    supportedViews: ['timeline', 'table'],
    supportsFacets: false,
    supportsComparison: true,
    supportsSelectionSets: false,
    supportsSavedViews: true,
    supportsExport: true,
  },
  timeline: {
    surfaceId: 'timeline',
    supportedFieldCategories: ['entity', 'time', 'device', 'campaign', 'truth'],
    supportedTemporalModes: ['window', 'as_of', 'relative'],
    supportedViews: ['timeline', 'table'],
    supportsFacets: false,
    supportsComparison: false,
    supportsSelectionSets: true,
    supportsSavedViews: false,
    supportsExport: true,
  },
};
