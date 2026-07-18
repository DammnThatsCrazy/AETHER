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
  useExplorationStatus,
  useExplorationFilters,
} from './provider';
export type { ExplorationProviderProps } from './provider';

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
export { dimensionStateStyle, suppressedFilterCount, completenessNotices } from './truth-model';
export { TruthBanner } from './components/truth-banner';
export type { TruthBannerProps } from './components/truth-banner';
export { FacetPanel, cohortMinimumFor } from './components/facet-panel';
export type { FacetPanelProps, FacetGroup, FacetBucket } from './components/facet-panel';
