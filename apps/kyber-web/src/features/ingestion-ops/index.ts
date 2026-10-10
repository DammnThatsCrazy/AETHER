/**
 * Barrel for the Kyber ingestion control plane (WS-E, blueprint Gate G).
 *
 * Re-exports the typed payload contracts (server-shaped, no credentials) and the
 * single operator page — Ingestion Ops — that renders the ingestion funnel, the
 * Observation Inspector (one observation's RAW→…→METRICS/FINDINGS trace), recent
 * traces, the mounted SDK-fleet view, the SDK version-compatibility tier manifest
 * and replay-service status. Routing is not a grant: the /v1/kyber/* endpoints
 * are Kyber-operator-only and gate every request; observability bodies report
 * `enabled: false` while the flag is OFF so the page renders honest states.
 */

export { IngestionOpsPage } from './IngestionOpsPage';
export type {
  FunnelRollup,
  FunnelSnapshot,
  FunnelStageBucket,
  IngestionStage,
  IngestionInstrumentation,
  ObservabilityStatus,
  ObservationTrace,
  PipelineHealth,
  RecentTracesResponse,
  ReplayStatus,
  SdkTierBand,
  SdkUnclassifiedBand,
  SdkVersionTiersEnvelope,
  SdkVersionTiersPayload,
  StageDisposition,
  TraceResponse,
  TraceSpan,
} from './types';
