import { z } from 'zod';
import { restClient, RestClientError } from '@aether-app/lib/api/rest/client';

const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });

const buildQS = (params: Record<string, string | number | boolean | undefined>): string => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
};

const BASE = '/v1/targeting-intelligence';

// ── Wire schemas (camelCase per @aether/shared targeting-intelligence contracts) ──
// Tolerant on purpose: the backend is built in parallel. Aether observes
// targeting — it never executes campaigns, so nothing here mutates external
// campaign platforms.

const evidenceRefsSchema = z.array(z.unknown()).nullish();

export const clusterTargetingRuleSchema = z.object({
  clusterId: z.string(),
  ruleType: z.string(),
  reasonCode: z.string().nullish(),
  confidenceScore: z.number().nullish(),
  evidenceRefs: evidenceRefsSchema,
}).passthrough();

export type ClusterTargetingRuleRecord = z.infer<typeof clusterTargetingRuleSchema>;

export const targetingIntentSchema = z.object({
  id: z.string(),
  tenantId: z.string().nullish(),
  campaignId: z.string().nullish(),
  source: z.string().nullish(),
  executionBoundary: z.string().nullish(),
  executionByAether: z.literal(false).nullish(),
  externalExecutionRequired: z.literal(true).nullish(),
  includeClusters: z.array(z.string()).nullish(),
  referenceClusters: z.array(z.string()).nullish(),
  excludeClusters: z.array(z.string()).nullish(),
  holdoutClusters: z.array(z.string()).nullish(),
  rules: z.array(clusterTargetingRuleSchema).nullish(),
  maxHopDepth: z.number().nullish(),
  graphMode: z.string().nullish(),
  minIdentityConfidence: z.number().nullish(),
  minClusterMembershipScore: z.number().nullish(),
  minPathConfidence: z.number().nullish(),
  minEvidenceCoverage: z.number().nullish(),
  createdAt: z.string().nullish(),
  updatedAt: z.string().nullish(),
  evidenceRefs: evidenceRefsSchema,
}).passthrough();

export type TargetingIntentRecord = z.infer<typeof targetingIntentSchema>;

export const eligibilitySnapshotSchema = z.object({
  snapshotId: z.string(),
  tenantId: z.string().nullish(),
  campaignId: z.string().nullish(),
  targetingIntentId: z.string().nullish(),
  asOf: z.string().nullish(),
  graphWatermark: z.string().nullish(),
  eligibleClusters: z.array(z.string()).nullish(),
  excludedClusters: z.array(z.string()).nullish(),
  holdoutClusters: z.array(z.string()).nullish(),
  identityConfidenceThreshold: z.number().nullish(),
  clusterMembershipThreshold: z.number().nullish(),
  pathConfidenceThreshold: z.number().nullish(),
  evidenceCoverageThreshold: z.number().nullish(),
  clusterMemberCounts: z.record(z.number()).nullish(),
  evidenceRefs: evidenceRefsSchema,
  createdAt: z.string().nullish(),
}).passthrough();

export type EligibilitySnapshotRecord = z.infer<typeof eligibilitySnapshotSchema>;

export const providerMappingQualitySchema = z.object({
  campaignId: z.string().nullish(),
  provider: z.string().nullish(),
  mappingRate: z.number().nullish(),
  providerSyncFreshness: z.string().nullish(),
  unresolvedAliasCount: z.number().nullish(),
  touchpointResolutionRate: z.number().nullish(),
  identityResolutionRate: z.number().nullish(),
  clusterAssignmentRate: z.number().nullish(),
  qualityScore: z.number().nullish(),
  blocksSuggestions: z.boolean().nullish(),
  reasons: z.array(z.string()).nullish(),
  computedAt: z.string().nullish(),
}).passthrough();

export type ProviderMappingQualityRecord = z.infer<typeof providerMappingQualitySchema>;

export const targetingObservationSchema = z.object({
  observationId: z.string(),
  tenantId: z.string().nullish(),
  campaignId: z.string().nullish(),
  targetingIntentId: z.string().nullish(),
  eligibilitySnapshotId: z.string().nullish(),
  sourceProvider: z.string().nullish(),
  reachedClusters: z.array(z.string()).nullish(),
  reachedIncludedClusters: z.array(z.string()).nullish(),
  reachedReferenceClusters: z.array(z.string()).nullish(),
  reachedExcludedClusters: z.array(z.string()).nullish(),
  reachedHoldoutClusters: z.array(z.string()).nullish(),
  providerMappingQuality: providerMappingQualitySchema.nullish(),
  observedAt: z.string().nullish(),
  computedAt: z.string().nullish(),
  evidenceRefs: evidenceRefsSchema,
}).passthrough();

export type TargetingObservationRecord = z.infer<typeof targetingObservationSchema>;

export const leakageFindingSchema = z.object({
  findingId: z.string(),
  tenantId: z.string().nullish(),
  campaignId: z.string().nullish(),
  targetingIntentId: z.string().nullish(),
  clusterId: z.string(),
  reasonCode: z.string().nullish(),
  excludedEntityCount: z.number().nullish(),
  reachedEntityCount: z.number().nullish(),
  leakageRate: z.number().nullish(),
  likelyCauses: z.array(z.string()).nullish(),
  severity: z.string(),
  evidenceRefs: evidenceRefsSchema,
  computedAt: z.string().nullish(),
}).passthrough();

export type LeakageFindingRecord = z.infer<typeof leakageFindingSchema>;

export const targetingHoldoutSchema = z.object({
  holdoutId: z.string(),
  tenantId: z.string().nullish(),
  campaignId: z.string().nullish(),
  targetingIntentId: z.string().nullish(),
  clusterIds: z.array(z.string()).nullish(),
  reason: z.string().nullish(),
  contaminated: z.boolean().nullish(),
  contaminationRate: z.number().nullish(),
  startAt: z.string().nullish(),
  endAt: z.string().nullish(),
  evidenceRefs: evidenceRefsSchema,
}).passthrough();

export type TargetingHoldoutRecord = z.infer<typeof targetingHoldoutSchema>;

export const journeyDeltaSchema = z.object({
  deltaId: z.string(),
  tenantId: z.string().nullish(),
  campaignId: z.string().nullish(),
  clusterId: z.string(),
  comparedToClusterIds: z.array(z.string()).nullish(),
  holdoutClusterIds: z.array(z.string()).nullish(),
  populationStageDeltas: z.record(z.number()).nullish(),
  commsStageDeltas: z.record(z.number()).nullish(),
  reachedCount: z.number().nullish(),
  engagedCount: z.number().nullish(),
  convertedCount: z.number().nullish(),
  attributedCount: z.number().nullish(),
  nonProgressedCount: z.number().nullish(),
  progressedElsewhereCount: z.number().nullish(),
  evidenceRefs: evidenceRefsSchema,
  computedAt: z.string().nullish(),
}).passthrough();

export type JourneyDeltaRecord = z.infer<typeof journeyDeltaSchema>;

export const clusterTargetingImpactSchema = z.object({
  tenantId: z.string().nullish(),
  campaignId: z.string().nullish(),
  clusterId: z.string(),
  memberCount: z.number().nullish(),
  eligibleCount: z.number().nullish(),
  reachedCount: z.number().nullish(),
  engagedCount: z.number().nullish(),
  convertedCount: z.number().nullish(),
  attributedCount: z.number().nullish(),
  /** USD amounts per contract field names. Null when unknown — never zeroed. */
  spendUsd: z.number().nullish(),
  revenueUsd: z.number().nullish(),
  roas: z.number().nullish(),
  ltvDelta: z.number().nullish(),
  complaintRate: z.number().nullish(),
  unsubscribeRate: z.number().nullish(),
  churnSignalRate: z.number().nullish(),
  fraudSignalRate: z.number().nullish(),
  overexposureScore: z.number().nullish(),
  identityConfidence: z.number().nullish(),
  clusterMembershipConfidence: z.number().nullish(),
  evidenceCoverage: z.number().nullish(),
  computedAt: z.string().nullish(),
  evidenceRefs: evidenceRefsSchema,
}).passthrough();

export type ClusterTargetingImpactRecord = z.infer<typeof clusterTargetingImpactSchema>;

export const exportPackageSchema = z.object({
  exportId: z.string(),
  tenantId: z.string().nullish(),
  suggestionId: z.string().nullish(),
  targetingIntentId: z.string().nullish(),
  campaignId: z.string().nullish(),
  includeClusterIds: z.array(z.string()).nullish(),
  referenceClusterIds: z.array(z.string()).nullish(),
  excludeClusterIds: z.array(z.string()).nullish(),
  holdoutClusterIds: z.array(z.string()).nullish(),
  implementationNotes: z.array(z.string()).nullish(),
  externalExecutionRequired: z.literal(true).nullish(),
  executionByAether: z.literal(false).nullish(),
  evidenceRefs: evidenceRefsSchema,
  generatedAt: z.string().nullish(),
}).passthrough();

export type ExportPackageRecord = z.infer<typeof exportPackageSchema>;

export const campaignTargetingSummarySchema = z.object({
  campaignId: z.string().nullish(),
  intents: z.array(targetingIntentSchema).nullish(),
  latestSnapshots: z.array(eligibilitySnapshotSchema).nullish(),
  observations: z.array(targetingObservationSchema).nullish(),
  impacts: z.array(clusterTargetingImpactSchema).nullish(),
  leakageFindings: z.array(leakageFindingSchema).nullish(),
  mappingQuality: providerMappingQualitySchema.nullish(),
  executionByAether: z.boolean().nullish(),
  externalExecutionRequired: z.boolean().nullish(),
}).passthrough();

export type CampaignTargetingSummaryRecord = z.infer<typeof campaignTargetingSummarySchema>;

export const clusterTargetingImpactResponseSchema = z.object({
  clusterId: z.string().nullish(),
  impact: clusterTargetingImpactSchema.nullish(),
  journeyDeltas: z.array(journeyDeltaSchema).nullish(),
}).passthrough();

export type ClusterTargetingImpactResponseRecord = z.infer<typeof clusterTargetingImpactResponseSchema>;

// Tolerant list shapes: bare array or wrapped object (backend wraps, e.g.
// { intents: [...] }).
const listSchema = <T extends z.ZodType>(itemSchema: T, key: string) =>
  z.union([
    z.array(itemSchema),
    z.object({ [key]: z.array(itemSchema) }).passthrough(),
  ]);

function unwrapList<T>(data: T[] | Record<string, unknown>, key: string): T[] {
  if (Array.isArray(data)) return data;
  return (data[key] as T[] | undefined) ?? [];
}

// Tolerant single-item shapes: bare record or wrapped object (backend wraps,
// e.g. { export: {...} }).
const itemSchema = <T extends z.ZodType>(schema: T, key: string) =>
  z.union([schema, z.object({ [key]: schema }).passthrough()]);

function unwrapItem<T>(data: unknown, key: string): T {
  if (data !== null && typeof data === 'object' && key in (data as Record<string, unknown>)) {
    return (data as Record<string, unknown>)[key] as T;
  }
  return data as T;
}

// ── Fetchers ───────────────────────────────────────────────────────────────────

/**
 * The backend gates this plane behind AETHER_CLUSTER_TARGETING_INTELLIGENCE_ENABLED
 * and answers 400 "... is not enabled ..." when the flag is off; 404/501 cover
 * unrouted/unimplemented deployments.
 */
function isNotConfigured(err: unknown): boolean {
  if (!(err instanceof RestClientError)) return false;
  if (err.status === 404 || err.status === 501) return true;
  return err.status === 400 && /not enabled/i.test(err.message);
}

export interface TargetingIntentListResult {
  readonly intents: TargetingIntentRecord[];
  /** True when the backend reports targeting intelligence is not enabled (404/501). */
  readonly notConfigured: boolean;
}

export async function fetchTargetingIntents(): Promise<TargetingIntentListResult> {
  try {
    const r = await restClient.get(`${BASE}/intents`, wrap(listSchema(targetingIntentSchema, 'intents')));
    return { intents: unwrapList(r.data, 'intents'), notConfigured: false };
  } catch (err) {
    if (isNotConfigured(err)) return { intents: [], notConfigured: true };
    throw err;
  }
}

export function createTargetingIntent(body: Record<string, unknown>): Promise<TargetingIntentRecord> {
  return restClient
    .post(`${BASE}/intents`, wrap(itemSchema(targetingIntentSchema, 'intent')), body)
    .then(r => unwrapItem<TargetingIntentRecord>(r.data, 'intent'));
}

export function fetchTargetingIntent(intentId: string): Promise<TargetingIntentRecord> {
  return restClient
    .get(`${BASE}/intents/${encodeURIComponent(intentId)}`, wrap(itemSchema(targetingIntentSchema, 'intent')))
    .then(r => unwrapItem<TargetingIntentRecord>(r.data, 'intent'));
}

export function createEligibilitySnapshot(intentId: string): Promise<EligibilitySnapshotRecord> {
  return restClient
    .post(
      `${BASE}/intents/${encodeURIComponent(intentId)}/eligibility-snapshot`,
      wrap(itemSchema(eligibilitySnapshotSchema, 'snapshot')),
      {},
    )
    .then(r => unwrapItem<EligibilitySnapshotRecord>(r.data, 'snapshot'));
}

export interface EligibilitySnapshotListResult {
  readonly snapshots: EligibilitySnapshotRecord[];
  readonly notConfigured: boolean;
}

export async function fetchEligibilitySnapshots(intentId?: string): Promise<EligibilitySnapshotListResult> {
  try {
    const r = await restClient.get(
      `${BASE}/snapshots${buildQS({ intent_id: intentId })}`,
      wrap(listSchema(eligibilitySnapshotSchema, 'snapshots')),
    );
    return { snapshots: unwrapList(r.data, 'snapshots'), notConfigured: false };
  } catch (err) {
    if (isNotConfigured(err)) return { snapshots: [], notConfigured: true };
    throw err;
  }
}

export interface TargetingObservationListResult {
  readonly observations: TargetingObservationRecord[];
  readonly notConfigured: boolean;
}

export async function fetchTargetingObservations(campaignId?: string): Promise<TargetingObservationListResult> {
  try {
    const r = await restClient.get(
      `${BASE}/observations${buildQS({ campaign_id: campaignId })}`,
      wrap(listSchema(targetingObservationSchema, 'observations')),
    );
    return { observations: unwrapList(r.data, 'observations'), notConfigured: false };
  } catch (err) {
    if (isNotConfigured(err)) return { observations: [], notConfigured: true };
    throw err;
  }
}

export interface LeakageFindingListResult {
  readonly findings: LeakageFindingRecord[];
  readonly notConfigured: boolean;
}

export async function fetchLeakageFindings(campaignId?: string): Promise<LeakageFindingListResult> {
  try {
    const r = await restClient.get(
      `${BASE}/leakage${buildQS({ campaign_id: campaignId })}`,
      wrap(listSchema(leakageFindingSchema, 'findings')),
    );
    return { findings: unwrapList(r.data, 'findings'), notConfigured: false };
  } catch (err) {
    if (isNotConfigured(err)) return { findings: [], notConfigured: true };
    throw err;
  }
}

export interface TargetingHoldoutListResult {
  readonly holdouts: TargetingHoldoutRecord[];
  readonly notConfigured: boolean;
}

export async function fetchTargetingHoldouts(): Promise<TargetingHoldoutListResult> {
  try {
    const r = await restClient.get(`${BASE}/holdouts`, wrap(listSchema(targetingHoldoutSchema, 'holdouts')));
    return { holdouts: unwrapList(r.data, 'holdouts'), notConfigured: false };
  } catch (err) {
    if (isNotConfigured(err)) return { holdouts: [], notConfigured: true };
    throw err;
  }
}

export interface JourneyDeltaListResult {
  readonly journeyDeltas: JourneyDeltaRecord[];
  readonly notConfigured: boolean;
}

export async function fetchJourneyDeltas(campaignId?: string): Promise<JourneyDeltaListResult> {
  try {
    const r = await restClient.get(
      `${BASE}/journey-deltas${buildQS({ campaign_id: campaignId })}`,
      wrap(listSchema(journeyDeltaSchema, 'journeyDeltas')),
    );
    return { journeyDeltas: unwrapList(r.data, 'journeyDeltas'), notConfigured: false };
  } catch (err) {
    if (isNotConfigured(err)) return { journeyDeltas: [], notConfigured: true };
    throw err;
  }
}

export interface CreateTargetingExportParams {
  readonly suggestionId?: string;
  readonly targetingIntentId?: string;
}

/** Builds a tenant-exportable implementation package. Aether never executes it. */
export function createTargetingExport(params: CreateTargetingExportParams): Promise<ExportPackageRecord> {
  const body: Record<string, string> = {};
  if (params.suggestionId) body.suggestionId = params.suggestionId;
  if (params.targetingIntentId) body.targetingIntentId = params.targetingIntentId;
  return restClient
    .post(`${BASE}/exports`, wrap(itemSchema(exportPackageSchema, 'export')), body)
    .then(r => unwrapItem<ExportPackageRecord>(r.data, 'export'));
}

export interface ExportPackageListResult {
  readonly exports: ExportPackageRecord[];
  readonly notConfigured: boolean;
}

export async function fetchTargetingExports(): Promise<ExportPackageListResult> {
  try {
    const r = await restClient.get(`${BASE}/exports`, wrap(listSchema(exportPackageSchema, 'exports')));
    return { exports: unwrapList(r.data, 'exports'), notConfigured: false };
  } catch (err) {
    if (isNotConfigured(err)) return { exports: [], notConfigured: true };
    throw err;
  }
}

export interface CampaignTargetingSummaryResult {
  readonly summary: CampaignTargetingSummaryRecord | null;
  readonly notConfigured: boolean;
}

export async function fetchCampaignTargetingIntelligence(campaignId: string): Promise<CampaignTargetingSummaryResult> {
  try {
    const r = await restClient.get(
      `/v1/campaigns/${encodeURIComponent(campaignId)}/targeting-intelligence`,
      wrap(campaignTargetingSummarySchema),
    );
    return { summary: r.data, notConfigured: false };
  } catch (err) {
    if (isNotConfigured(err)) return { summary: null, notConfigured: true };
    throw err;
  }
}

export interface ClusterTargetingImpactResult {
  readonly response: ClusterTargetingImpactResponseRecord | null;
  readonly notConfigured: boolean;
}

export async function fetchClusterTargetingImpact(clusterId: string): Promise<ClusterTargetingImpactResult> {
  try {
    const r = await restClient.get(
      `/v1/clusters/${encodeURIComponent(clusterId)}/targeting-impact`,
      wrap(clusterTargetingImpactResponseSchema),
    );
    return { response: r.data, notConfigured: false };
  } catch (err) {
    if (isNotConfigured(err)) return { response: null, notConfigured: true };
    throw err;
  }
}
