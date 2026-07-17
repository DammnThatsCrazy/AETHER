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
