/**
 * Kyber — Ingestion control plane (WS-E): server-shaped payload types.
 *
 * These mirror the JSON returned by the Kyber operator ingestion surfaces:
 *   · GET /v1/kyber/ingest/observability{,/funnel,/traces,/traces/{event_id}}
 *   · GET /v1/kyber/ingest/replay/status
 *   · GET /v1/health/pipeline
 *   · GET /v1/config/sdk/versions
 *
 * The stage vocabulary and disposition statuses match
 * services/ingestion/ingestion_observability.py exactly (RAW is client-side and
 * never observed server-side; RESOLVED → METRICS/FINDINGS are declared for the
 * ladder but report `monitored: false`). No credentials flow through these — the
 * pages only render counters, spans, and static policy data.
 */

/** Blueprint §17 Observation Inspector ladder (declared + monitored subset). */
export type IngestionStage =
  | 'raw'
  | 'received'
  | 'validated'
  | 'bronze'
  | 'normalized'
  | 'resolved'
  | 'relationships'
  | 'graph_mutations'
  | 'projections'
  | 'metrics_findings';

/** Per-stage disposition vocabulary (accepted/duplicate/rejected/degraded/observed). */
export type StageDisposition = 'accepted' | 'duplicate' | 'rejected' | 'degraded' | 'observed';

export interface FunnelStageBucket {
  readonly stage: IngestionStage;
  readonly display: string;
  readonly monitored: boolean;
  readonly total: number;
  readonly by_status: Partial<Record<StageDisposition, number>>;
}

/** Operator-critical rollup the control plane renders. */
export interface FunnelRollup {
  readonly received: number;
  readonly accepted: number;
  readonly duplicates: number;
  readonly rejected: number;
  readonly degraded: number;
}

export interface IngestionInstrumentation {
  readonly monitored_stages: readonly IngestionStage[];
  readonly declared_unmonitored: readonly IngestionStage[];
  readonly scope: string;
}

export interface ObservabilityStatus {
  readonly enabled: boolean;
  readonly recorded_at: string;
  readonly instrumentation: IngestionInstrumentation;
}

export interface FunnelSnapshot extends ObservabilityStatus {
  readonly rollup: FunnelRollup;
  readonly stages: readonly FunnelStageBucket[];
}

export interface TraceSpan {
  readonly stage: IngestionStage;
  readonly display: string;
  readonly status: string;
  readonly at_ms: number;
  readonly detail?: string | null;
}

export interface ObservationTrace {
  readonly tenant_id: string;
  readonly event_id: string;
  readonly event_type: string;
  readonly path: string;
  readonly started_at: string;
  readonly outcome: string | null;
  readonly spans: readonly TraceSpan[];
  readonly complete: boolean;
}

export interface TraceResponse {
  readonly trace: ObservationTrace | null;
}

export interface RecentTracesResponse {
  readonly traces: readonly ObservationTrace[];
}

export interface PipelineHealth {
  readonly probe: string;
  readonly status: 'healthy' | 'degraded' | 'disabled';
  readonly enabled: boolean;
  readonly timestamp: string;
  readonly pipeline: FunnelRollup;
  readonly stages: readonly FunnelStageBucket[];
}

export interface ReplayStatus {
  readonly enabled: boolean;
  readonly source_service: string;
  readonly dry_run_default: boolean;
}

export interface SdkTierBand {
  readonly id: string;
  readonly status: string;
  readonly label: string;
  readonly min_version: string;
  readonly max_version_exclusive: string;
  readonly deprecated_after?: string | null;
  readonly blocked_after?: string | null;
  readonly capabilities: readonly string[];
  readonly note?: string | null;
}

export interface SdkUnclassifiedBand {
  readonly id: string;
  readonly label: string;
  readonly note?: string | null;
}

export interface SdkVersionTiersPayload {
  readonly schema_version: string;
  readonly enabled: boolean;
  readonly mode: 'off' | 'shadow' | 'warn' | 'enforce';
  readonly blocked_after_date: string;
  readonly tiers: readonly SdkTierBand[];
  readonly unclassified: SdkUnclassifiedBand;
}

/**
 * GET /v1/config/sdk/versions is an APIResponse-wrapped route, so the HTTP body
 * nests the tier payload under `data` (`{ data: SdkVersionTiersPayload }`).
 */
export interface SdkVersionTiersEnvelope {
  readonly data: SdkVersionTiersPayload;
}
