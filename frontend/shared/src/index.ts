export { cn } from './utils/cn';

// External store primitive (framework-agnostic core + React binding).
export { createStore, useStore } from './state/index';
export type { Store } from './state/index';

// The exploration fabric is exposed via the '@aether/ui/exploration' subpath
// (like '@aether/ui/query'), NOT this barrel: it value-imports the CJS-only
// '@aether/shared' registries, and keeping it off the main entry means apps
// pulling '@aether/ui' for components don't drag that chain into their bundle.

// Shared time system — the ONLY sanctioned home for Intl date/time formatting.
export {
  TimeProvider,
  useTime,
  useTimeContext,
  resolveViewerContext,
  useNow,
  formatInstant,
  formatDate,
  formatTime,
  formatDateTime,
  formatRelative,
  describeZone,
  toCanonicalUtc,
  TIME_LENSES,
  UTC_CONTEXT,
} from './time/index';
export type {
  TimeContext,
  TimeLens,
  TimeZoneResolution,
  ResolvedViewerTime,
  TimeProviderPreferences,
} from './time/index';

export { TimeWindowSelector } from './components/time-window-selector';
export type { TimeWindow } from './components/time-window-selector';
export { TimeLensControl } from './components/time-lens-control';

// Locale-explicit number formatting (same attribution rules as time).
export { formatCount, formatDecimal, formatCurrency } from './format/number';
export type { LocaleContext, FormatDecimalOptions } from './format/number';
export { FreshnessIndicator } from './components/freshness-indicator';
export { EvidenceDrawer } from './components/evidence-drawer';
export type { EvidenceRef } from './components/evidence-drawer';

export { UsageBar } from './components/usage-bar';
export { ToastProvider, Toaster, useToast } from './components/toast';
export { Popover } from './components/popover';
export { SocialProviderIcon } from './components/social-provider-icon';
export type { SocialProvider } from './components/social-provider-icon';

export { ThemeProvider, useTheme } from './hooks/use-theme';
export type { Theme } from './hooks/use-theme';

export { Badge } from './components/badge';
export { Button } from './components/button';
export { Card, CardHeader, CardTitle, CardContent, CardFooter } from './components/card';
export { DataTable } from './components/data-table';
export { EmptyState } from './components/empty-state';
export { EnvironmentBadge } from './components/environment-badge';
export { ErrorState } from './components/error-state';
export { GlyphIcon } from './components/glyph-icon';
export { Input } from './components/input';
export { LoadingState } from './components/loading-state';
export { Modal, ModalHeader, ModalBody, ModalFooter } from './components/modal';
export { ScrollArea } from './components/scroll-area';
export { Select } from './components/select';
export { SeverityBadge } from './components/severity-badge';
export { Skeleton } from './components/skeleton';
export { StatusIndicator } from './components/status-indicator';
export { Tabs, TabsList, TabsTrigger, TabsContent } from './components/tabs';

// Canonical capability credential-lifecycle state matrix (shared by both apps).
export {
  capabilityStates,
  capabilityStateStyle,
  capabilityStatePrecedence,
  worstCapabilityState,
  isCapabilityState,
  toneVariant,
  fromImplementationStatus,
  fromDimensionState,
  resolveCapabilityState,
  CapabilityStateBadge,
  CapabilityStatePanel,
  MockModeBanner,
} from './status/index';
export type {
  CapabilityState,
  CapabilityTone,
  CapabilityStateStyle,
  CapabilityStateBadgeProps,
  CapabilityStatePanelProps,
  MockModeBannerProps,
  RuntimeDataMode,
} from './status/index';
export { TerminalSeparator } from './components/terminal-separator';
export { Toggle } from './components/toggle';
export { Tooltip } from './components/tooltip';

export {
  queryCache,
  useQuery,
  useMutation,
  usePaginatedQuery,
} from './query/index';
export type {
  UseQueryOptions,
  UseQueryResult,
  UseMutationOptions,
  UseMutationResult,
  PageFetcherParams,
  PageFetcherResult,
  PageFetcher,
  UsePaginatedQueryResult,
} from './query/index';

export type {
  ServiceHealthStatus,
  ServiceHealthRecord,
  PipelineHealthRecord,
  QueueHealthRecord,
  IncidentRecord,
  IncidentSeverity,
  IncidentStatus,
  OperationalRunbook,
  ServiceLevelObjective,
  SLOWindow,
  SLOStatus,
  IncidentPostmortem,
  PostmortemStatus,
  TenantStatusSummary,
  TenantSafeIncident,
} from './types/reliability';

export { NoesisWorkspace } from './components/noesis-workspace';
export type { NoesisAction, NoesisGraphPayload, NoesisMessageItem, NoesisResponsePayload } from './components/noesis-workspace';

// Relationship-layer vocabulary is canonical in @aether/shared (graph-contract).
// Import it from there directly — this UI package no longer ships a divergent copy.

export { parseProblemDetails, isProblemDetails } from './problem-details';
export type { ProblemDetails } from './problem-details';

// Canonical USD-first value formatting + presentation.
export {
  formatUSD,
  formatNativeValue,
  formatAetherValue,
  VALUE_UNAVAILABLE,
  ValueDisplay,
  USDValue,
  NativeValueBreakdown,
  ValuationWarning,
  RollupStatusBadge,
  FreshnessBadge,
  ReconciliationBadge,
  OwnershipConfidenceBadge,
} from './value/index';
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
} from './value/index';
