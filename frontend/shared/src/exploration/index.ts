// Shared exploration fabric — registry-driven filter/URL primitives.
// UI components (FilterBar, FilterBuilder, TruthBanner, FacetPanel) and the
// exploration store/provider build on these; everything consumes the canonical
// contract registries, never hardcoded field lists.

export {
  allFilterFields,
  getFilterField,
  isKnownField,
  operatorsForField,
  isOperatorValidForField,
  surfaceCapability,
  filterFieldsForSurface,
  isKnownSurface,
  isValuelessOperator,
  isMultiValueOperator,
  isRangeOperator,
} from './registry';

export {
  sanitizeFilterGroup,
  encodeFilterGroup,
  decodeFilterGroup,
  encodeExplorationContext,
  decodeExplorationContext,
  decodedSurfaceIsKnown,
} from './url-codec';
export type { DecodeDefaults } from './url-codec';

export {
  createExplorationStore,
  explorationActions,
  useExplorationStore,
  initialExplorationState,
  withAddedFilter,
  withoutFilterAt,
} from './store';
export type { ExplorationState, ExplorationStatus, ExplorationActions } from './store';

export {
  ExplorationProvider,
  useExploration,
  useExplorationSelector,
  useExplorationContext,
  useExplorationClient,
  useExplorationStatus,
  useExplorationFilters,
} from './provider';
export type { ExplorationProviderProps } from './provider';

// Typed canonical API client. App-owned transports supply auth/CSRF/base URL;
// the shared client owns endpoint contracts, validation, and stale-response
// coordination.
export {
  createExplorationClient,
  assertRegistryValidContext,
  ExplorationClientValidationError,
  StaleExplorationResponseError,
} from './client';
export type {
  ExplorationApiResponse,
  ExplorationTransportRequest,
  ExplorationTransport,
  ExplorationRequestOptions,
  ExplorationQueryRequest,
  ExplorationFacetRequest,
  ExplorationFacet,
  ExplorationFacetData,
  SavedExplorationView,
  SaveExplorationViewRequest,
  ResolveContextLinkRequest,
  ResolvedContextLink,
  ExplorationValidationResult,
  ExplorationClient,
} from './client';

// Filter models + components.
export {
  operatorLabel,
  coerceScalar,
  buildFilterExpression,
  formatFilterValue,
  chipsFromContext,
} from './filter-model';
export type { FilterChipModel } from './filter-model';
export { FilterDispositionBadge, dispositionStyle } from './components/disposition-badge';
export { FilterBuilder } from './components/filter-builder';
export type { FilterBuilderProps } from './components/filter-builder';
export { FilterBar } from './components/filter-bar';
export type { FilterBarProps } from './components/filter-bar';

// Truth + facets.
export {
  dimensionStateStyle,
  suppressedFilterCount,
  completenessNotices,
  observationClassLabel,
  measurementTruthNotices,
} from './truth-model';
export type { MeasurementTruth, MeasurementCausality } from './truth-model';
export { TruthBanner } from './components/truth-banner';
export type { TruthBannerProps } from './components/truth-banner';
export { FacetPanel, cohortMinimumFor } from './components/facet-panel';
export type { FacetPanelProps, FacetGroup, FacetBucket } from './components/facet-panel';

// Chrome: breadcrumbs + saved views.
export { breadcrumbsFromContext, surfaceSupportsSavedViews } from './chrome-model';
export type { Crumb } from './chrome-model';
export { ExplorationBreadcrumbs } from './components/breadcrumbs';
export type { ExplorationBreadcrumbsProps } from './components/breadcrumbs';
export { SavedViewChrome } from './components/saved-view-chrome';
export type { SavedViewChromeProps, SavedView } from './components/saved-view-chrome';
