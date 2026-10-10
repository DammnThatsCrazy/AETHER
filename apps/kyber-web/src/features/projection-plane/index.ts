/**
 * Intelligence-projection plane read model + presentational renderers.
 *
 * Shared by the Kyber risk360 (Risk 360 workbench) and fraud360 (Fraud 360
 * consolidation) operator surfaces. Reads the projection endpoints DIRECTLY via
 * the Kyber `api` client (never the flag-gated exploration fabric) and renders
 * the ProjectionResult payload honestly — sections/claims/dependency state as
 * reported, never fabricated.
 */

export {
  parseProjectionResult,
  sectionTone,
  hypothesisTone,
  sectionHasContent,
  isHypothesisLike,
  displayText,
} from './types';
export type {
  ProjectionResultModel,
  ProjectionSectionModel,
  ProjectionClaimModel,
  ProjectionDependencyModel,
  BadgeTone,
} from './types';
export {
  ProjectionContent,
  ProjectionResultView,
  ProjectionSectionCard,
  ProjectionClaimsList,
  ProjectionDependencyList,
  ProjectionHypothesisCard,
  ProjectionPlaneHealth,
  ProjectionSubjectPicker,
} from './projection-result-view';
