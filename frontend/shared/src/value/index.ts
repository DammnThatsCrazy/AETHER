// Canonical USD-first value formatting + presentation.
export {
  formatUSD,
  formatNativeValue,
  formatAetherValue,
  VALUE_UNAVAILABLE,
} from './format';
export type {
  FormatUSDOptions,
  FormatNativeOptions,
  FormatAetherValueOptions,
  FormattedAetherValue,
  AetherValueLike,
  NativeValueLike,
  USDValuationLike,
  DisplayValueLike,
  ValueFreshness,
  ValueConfidence,
  RollupStatus,
  ValueReconciliationState,
  OwnershipRelationship,
} from './format';

export {
  ValueDisplay,
  USDValue,
  NativeValueBreakdown,
  ValuationWarning,
} from './value-display';

export {
  RollupStatusBadge,
  FreshnessBadge,
  ReconciliationBadge,
  OwnershipConfidenceBadge,
} from './value-badges';

// Reporting-asset + viewer display-currency presentation (additive Wave 3).
export {
  REPORTING_UNAVAILABLE,
  DISPLAY_CONVERSION_UNAVAILABLE,
  isDecimalString,
  convertDecimalAmount,
  formatDecimalAmount,
  decorateAmountText,
  composeReportingDisplay,
} from './reporting-value';
export type {
  AssetDisplayMeta,
  DisplayCurrencyQuote,
  ReportingValuationLike,
  ReportingValueKind,
  ReportingUnavailableReason,
  ReportingValueRender,
  ComposeReportingDisplayInput,
  FormatDecimalAmountOptions,
} from './reporting-value';

export {
  resolveCanonicalAssetDisplayMeta,
  resolveReportingAssetMeta,
} from './reporting-asset-meta';

export {
  ReportingValueDisplay,
  buildReportingValueRender,
} from './reporting-value-display';
