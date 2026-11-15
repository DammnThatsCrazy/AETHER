import { useState } from 'react';
import { useCapabilities, useQuery } from '@aether/ui';
import { z } from 'zod';
import type {
  PatternCurationAction, PatternKind, PatternLens, PatternStatus, PatternSurface, PatternVerdict,
} from '@aether/shared';
import { restClient } from '@aether-app/lib/api/rest/client';

/** Typed against the shared contract (packages/shared/pattern-discovery.ts);
 *  backend parity is asserted by tests/unit/test_pattern_discovery_contract_parity.py. */
export const PATTERN_VERDICTS = ['valid', 'malicious', 'benign', 'duplicate', 'unresolved'] as const satisfies readonly PatternVerdict[];
/** Statuses shown by default (surfaced automatically or kept by a person). */
export const VISIBLE_STATUSES = ['surfaced', 'unresolved', 'confirmed_valid', 'confirmed_malicious', 'promoted'] as const satisfies readonly PatternStatus[];

function envelope<T extends z.ZodTypeAny>(data: T) {
  return z.object({ data, status: z.string(), timestamp: z.string() }).passthrough();
}

export const patternSummarySchema = z.object({
  pattern_id: z.string(),
  kind: z.string(),
  title: z.string(),
  summary: z.string().nullable().optional(),
  status: z.string(),
  priority: z.string().nullable().optional(),
  severity: z.string().nullable().optional(),
  confidence: z.number(),
  confidence_cap: z.number().nullable().optional(),
  novelty: z.number().nullable().optional(),
  affected_entity_count: z.number(),
  risk_categories: z.array(z.string()),
  first_observed_at: z.string().nullable().optional(),
  last_observed_at: z.string().nullable().optional(),
  claim_state: z.string().nullable().optional(),
  pinned: z.boolean().nullable().optional(),
  detector_title: z.string().nullable().optional(),
  surfaced_at: z.string().nullable().optional(),
  changed_at: z.string().nullable().optional(),
  is_new: z.boolean().optional(),
  is_changed: z.boolean().optional(),
}).passthrough();
export type PatternSummaryRow = z.infer<typeof patternSummarySchema>;

const listSchema = z.object({ items: z.array(patternSummarySchema), count: z.number(), total: z.number() }).passthrough();

const detailSchema = patternSummarySchema.extend({
  evidence: z.array(z.object({
    type: z.string(), basis: z.string(), strength: z.number(),
  }).passthrough()),
  competing_explanations: z.array(z.object({ id: z.string(), note: z.string() })),
  review_history: z.array(z.record(z.unknown())),
}).passthrough();
export type PatternDetailRow = z.infer<typeof detailSchema>;

const coImplicatedSchema = z.array(z.object({ entity: z.string(), shared_patterns: z.number() }));

const sectionSchema = z.object({
  entity: z.string(),
  surface: z.string(),
  withheld: z.boolean(),
  reason_code: z.string().nullable().optional(),
  scope: z.string().optional(),
  last_seen_at: z.string().nullable().optional(),
  new_count: z.number().optional(),
  counts: z.object({
    total: z.number(), surfaced: z.number(), reviewed: z.number(), promoted: z.number(),
    watching: z.number(), hidden: z.number(),
  }),
}).catchall(z.union([z.array(patternSummarySchema), coImplicatedSchema, z.unknown()]));
export type PatternSection = z.infer<typeof sectionSchema>;

/** Sections each surface renders, in order: [response key, heading, kind]. */
export const SECTION_LAYOUT: Record<PatternSurface, ReadonlyArray<readonly [string, string, 'patterns' | 'entities']>> = {
  profile360: [
    ['emerging_patterns', 'Emerging patterns', 'patterns'],
    ['unresolved_identity_overlaps', 'Unresolved identity overlaps', 'patterns'],
    ['contradictory_evidence', 'Contradictory evidence', 'patterns'],
    ['baseline_changes', 'Changes from this profile’s baseline', 'patterns'],
    ['behavioral_cohorts', 'Behavioural cohorts', 'patterns'],
    ['similar_profiles', 'Similar profiles', 'entities'],
  ],
  agent360: [
    ['novel_delegation_motifs', 'Novel delegation motifs', 'patterns'],
    ['tool_call_signatures', 'Tool-call signatures', 'patterns'],
    ['spawning_anomalies', 'Sub-agent spawning anomalies', 'patterns'],
    ['shared_infrastructure', 'Shared infrastructure', 'patterns'],
    ['cross_principal_behavior', 'Behaviour repeated across principals', 'patterns'],
    ['agent_interactions', 'Agent-to-agent interaction', 'patterns'],
    ['shared_infrastructure_agents', 'Agents sharing infrastructure', 'entities'],
  ],
  risk360: [
    ['pattern_findings', 'Pattern-based findings', 'patterns'],
    ['campaigns', 'Cross-profile campaigns', 'patterns'],
    ['emerging_clusters', 'Emerging clusters', 'patterns'],
    ['graph_motifs', 'Graph motifs', 'patterns'],
    ['temporal_anomalies', 'Temporal anomalies', 'patterns'],
  ],
};

/** True when the tenant's capabilities enable pattern discovery. Outside a
 *  CapabilityProvider (isolated page renders) the surfaces stay off rather
 *  than crash the page that hosts them. ``useCapabilities`` reads context
 *  first and throws afterwards, so hook order is the same either way. */
export function usePatternDiscoveryEnabled(): boolean {
  try {
    const { capabilities } = useCapabilities();
    return Boolean(capabilities?.feature_flags?.pattern_discovery_enabled);
  } catch {
    return false;
  }
}

function sectionPath(surface: PatternSurface, entityId: string, riskKind = 'user'): string {
  const id = encodeURIComponent(entityId);
  if (surface === 'profile360') return `/v1/profile/${id}/patterns`;
  if (surface === 'agent360') return `/v1/agent/${id}/patterns`;
  return `/v1/risk360/${encodeURIComponent(riskKind)}/${id}/patterns`;
}

export function usePatternSection(surface: PatternSurface, entityId: string, riskKind?: string) {
  const enabled = usePatternDiscoveryEnabled();
  return useQuery({
    key: `pattern-section:${surface}:${riskKind ?? ''}:${encodeURIComponent(entityId)}`,
    fetcher: () => restClient.get(sectionPath(surface, entityId, riskKind), envelope(sectionSchema)).then(r => r.data),
    enabled: enabled && Boolean(entityId),
    staleTime: 30_000,
  });
}

export function usePatternList(params: { feed?: boolean; status?: string; kind?: PatternKind | '' }) {
  const enabled = usePatternDiscoveryEnabled();
  const qs = new URLSearchParams();
  if (params.feed) qs.set('feed', 'true');
  if (params.status) qs.set('status', params.status);
  if (params.kind) qs.set('kind', params.kind);
  qs.set('limit', '100');
  return useQuery({
    key: `pattern-list:${qs.toString()}`,
    fetcher: () => restClient.get(`/v1/intelligence/patterns?${qs.toString()}`, envelope(listSchema)).then(r => r.data),
    enabled,
    staleTime: 15_000,
  });
}

export function usePatternDetail(patternId: string | null) {
  const enabled = usePatternDiscoveryEnabled();
  return useQuery({
    key: `pattern-detail:${patternId ?? ''}`,
    fetcher: () => restClient
      .get(`/v1/intelligence/patterns/${encodeURIComponent(patternId ?? '')}`, envelope(detailSchema))
      .then(r => r.data),
    enabled: enabled && Boolean(patternId),
    staleTime: 10_000,
  });
}

export function usePatternReview() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const review = async (patternId: string, verdict: PatternVerdict, reason: string): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await restClient.post(
        `/v1/intelligence/patterns/${encodeURIComponent(patternId)}/review`,
        envelope(z.unknown()),
        { verdict, reason },
      );
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { review, busy, error };
}


// ── Curation (item 1): hide / unhide / pin / unpin / rename, no verdict needed ──

export function usePatternCurate() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const curate = async (patternId: string, action: PatternCurationAction, title?: string): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await restClient.post(
        `/v1/intelligence/patterns/${encodeURIComponent(patternId)}/curate`,
        envelope(z.unknown()),
        title !== undefined ? { action, title } : { action },
      );
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { curate, busy, error };
}

// ── What's new since I last looked (item 2) ─────────────────────────────────

const digestSchema = z.object({
  count: z.number(),
  by_kind: z.record(z.number()),
  by_severity: z.record(z.number()),
  by_segment: z.record(z.number()),
}).passthrough();

const whatsNewSchema = z.object({
  scope: z.string(),
  withheld: z.boolean(),
  since: z.string(),
  since_source: z.string().optional(),
  last_seen_at: z.string().nullable(),
  new: z.array(patternSummarySchema),
  changed: z.array(patternSummarySchema),
  retired: z.array(patternSummarySchema),
  digest: z.object({ new: digestSchema, changed: digestSchema, retired: digestSchema }),
}).passthrough();
export type PatternWhatsNewView = z.infer<typeof whatsNewSchema>;

export function useWhatsNew(scope = 'feed') {
  const enabled = usePatternDiscoveryEnabled();
  return useQuery({
    key: `pattern-whats-new:${scope}`,
    fetcher: () => restClient
      .get(`/v1/intelligence/patterns/whats-new?scope=${encodeURIComponent(scope)}`, envelope(whatsNewSchema))
      .then(r => r.data),
    enabled,
    staleTime: 15_000,
  });
}

export async function markPatternsSeen(scope = 'feed'): Promise<void> {
  await restClient.post('/v1/intelligence/patterns/whats-new/seen', envelope(z.unknown()), { scope });
}

// ── Patterns on the graph (item 3) ──────────────────────────────────────────

const graphSchema = z.object({
  pattern_id: z.string(),
  kind: z.string(),
  title: z.string().nullable(),
  nodes: z.array(z.object({ id: z.string(), kind: z.string(), label: z.string(), role: z.string() })),
  edges: z.array(z.object({ source: z.string(), target: z.string(), type: z.string() })),
  truncated: z.boolean(),
}).passthrough();
export type PatternGraphView = z.infer<typeof graphSchema>;

export function usePatternGraph(patternId: string | null) {
  const enabled = usePatternDiscoveryEnabled();
  return useQuery({
    key: `pattern-graph:${patternId ?? ''}`,
    fetcher: () => restClient
      .get(`/v1/intelligence/patterns/${encodeURIComponent(patternId ?? '')}/graph`, envelope(graphSchema))
      .then(r => r.data),
    enabled: enabled && Boolean(patternId),
    staleTime: 30_000,
  });
}

const overlaySchema = z.object({
  by_node: z.record(z.array(z.string())),
  patterns: z.array(z.object({
    pattern_id: z.string(),
    kind: z.string(),
    title: z.string().nullable(),
    severity: z.string().nullable().optional(),
    members_in_view: z.array(z.string()),
    affected_entity_count: z.number().nullable().optional(),
  }).passthrough()),
}).passthrough();
export type PatternOverlayView = z.infer<typeof overlaySchema>;

export function usePatternOverlay(nodeIds: readonly string[]) {
  const enabled = usePatternDiscoveryEnabled();
  const ids = nodeIds.slice(0, 500);
  return useQuery({
    key: `pattern-overlay:${ids.join(',')}`,
    fetcher: () => restClient
      .post('/v1/intelligence/patterns/graph-overlay', envelope(overlaySchema), { node_ids: ids })
      .then(r => r.data),
    enabled: enabled && ids.length > 0,
    staleTime: 30_000,
  });
}

// ── Segment lenses (item 4) ─────────────────────────────────────────────────

const lensSchema = z.object({
  lens: z.string(),
  subject: z.string(),
  withheld: z.boolean(),
  last_seen_at: z.string().nullable().optional(),
  new_count: z.number().optional(),
  scope: z.string().optional(),
  counts: z.object({ total: z.number(), by_kind: z.record(z.number()) }),
  groups: z.array(z.object({ kind: z.string(), heading: z.string(), patterns: z.array(patternSummarySchema) })),
}).passthrough();
export type PatternLensViewData = z.infer<typeof lensSchema>;

export function usePatternLens(lens: PatternLens, subject: string) {
  const enabled = usePatternDiscoveryEnabled();
  return useQuery({
    key: `pattern-lens:${lens}:${encodeURIComponent(subject)}`,
    fetcher: () => restClient
      .get(`/v1/intelligence/patterns/lenses/${lens}/${encodeURIComponent(subject)}`, envelope(lensSchema))
      .then(r => r.data),
    enabled: enabled && Boolean(subject),
    staleTime: 30_000,
  });
}
