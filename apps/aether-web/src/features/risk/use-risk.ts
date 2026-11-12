import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

/**
 * Risk reads — thin, tenant-scoped wrappers over endpoints already in `api`:
 *   - investigation cases (`/v1/investigations`), whose status can be moved
 *     forward through the backend's own transition rules;
 *   - the tenant data-quality overview (`/v1/data-quality/overview`), which
 *     carries the backend's own quality score and open drift counts by
 *     severity.
 * Agent capability risk findings come from the existing agent-access hook.
 */

export type CaseStatus = 'open' | 'triage' | 'active' | 'escalated' | 'closed';

export interface CaseSubject {
  readonly kind: string;
  readonly id: string;
  readonly label: string | null;
}

export interface CaseEvidence {
  readonly id: string;
  readonly type: string;
  readonly source: string;
  readonly observedAt: string | null;
}

export interface InvestigationCase {
  readonly id: string;
  readonly title: string;
  readonly status: CaseStatus;
  readonly subjects: readonly CaseSubject[];
  readonly evidence: readonly CaseEvidence[];
  readonly annotationCount: number;
  readonly createdBy: string | null;
  readonly createdAt: string | null;
  readonly updatedAt: string | null;
}

const STATUSES: readonly CaseStatus[] = ['open', 'triage', 'active', 'escalated', 'closed'];

function str(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((v): v is Record<string, unknown> => Boolean(v) && typeof v === 'object') : [];
}

/** Accepts the bare list the route returns, or an `{ data }` / `{ items }` envelope. */
export function normaliseCases(raw: unknown): InvestigationCase[] {
  let list: unknown = raw;
  if (list && typeof list === 'object' && !Array.isArray(list)) {
    const env = list as { data?: unknown; items?: unknown };
    list = Array.isArray(env.data) ? env.data : env.items;
  }
  return records(list)
    .filter(r => str(r['id']))
    .map(r => {
      const status = str(r['status']);
      return {
        id: String(r['id']),
        title: str(r['title']) ?? 'Untitled case',
        status: STATUSES.includes(status as CaseStatus) ? (status as CaseStatus) : 'open',
        subjects: records(r['subjects'])
          .filter(s => str(s['id']))
          .map(s => ({ kind: str(s['kind']) ?? 'entity', id: String(s['id']), label: str(s['label']) })),
        evidence: records(r['evidence']).map((e, i) => ({
          id: str(e['id']) ?? `evidence-${i}`,
          type: str(e['type']) ?? 'evidence',
          source: str(e['source']) ?? 'source not recorded',
          observedAt: str(e['observedAt']),
        })),
        annotationCount: Array.isArray(r['annotations']) ? r['annotations'].length : 0,
        createdBy: str(r['createdBy']),
        createdAt: str(r['createdAt']),
        updatedAt: str(r['updatedAt']),
      };
    });
}

export function riskCasesKey(tenantId: string): string {
  return `risk:${tenantId}:cases`;
}

export function useRiskCases(tenantId: string) {
  return useQuery<InvestigationCase[]>({
    key: riskCasesKey(tenantId),
    fetcher: () => api.investigations.list(tenantId, undefined, 200).then(normaliseCases),
    staleTime: 30_000,
    enabled: Boolean(tenantId),
  });
}

export interface DataQualityRisk {
  /** Backend-computed overall intelligence quality score (0–1), or null when not computed. */
  readonly score: number | null;
  readonly status: string | null;
  readonly openDrift: number | null;
  readonly driftBySeverity: Readonly<Record<string, number>>;
}

export function normaliseDataQuality(raw: unknown): DataQualityRisk {
  const r = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const score = r['score'] && typeof r['score'] === 'object' ? (r['score'] as Record<string, unknown>) : {};
  const overall = score['overall_intelligence_quality_score'];
  const open = r['open_drift_event_count'];
  const bySev = r['drift_by_severity'] && typeof r['drift_by_severity'] === 'object' ? (r['drift_by_severity'] as Record<string, unknown>) : {};
  const driftBySeverity: Record<string, number> = {};
  for (const [k, v] of Object.entries(bySev)) if (typeof v === 'number' && Number.isFinite(v)) driftBySeverity[k.toLowerCase()] = v;
  return {
    score: typeof overall === 'number' && Number.isFinite(overall) ? overall : null,
    status: str(score['status']),
    openDrift: typeof open === 'number' && Number.isFinite(open) ? open : null,
    driftBySeverity,
  };
}

export function useRiskDataQuality(tenantId: string) {
  return useQuery<DataQualityRisk>({
    key: `risk:${tenantId}:data-quality`,
    fetcher: () => api.dataQuality.overview().then(normaliseDataQuality),
    staleTime: 60_000,
    enabled: Boolean(tenantId),
  });
}

export function useTransitionCase(tenantId: string) {
  return useMutation<{ id: string; status: CaseStatus }, unknown>({
    mutationFn: ({ id, status }) => api.investigations.transitionStatus(id, { tenantId, status }),
    invalidateKeys: [riskCasesKey(tenantId)],
  });
}
