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
