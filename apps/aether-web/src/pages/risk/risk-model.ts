import type { Tone } from '@aether-app/components/ae-ui';
import type { RiskFinding } from '@aether-app/features/agent-access';
import type { CaseStatus, InvestigationCase } from '@aether-app/features/risk/use-risk';

/**
 * Pure helpers for the Risk page. They arrange what the backend returned —
 * agent capability findings (with their observed risk level), investigation
 * cases (which carry a status, never a severity) and data-quality drift counts.
 * There is deliberately no composite risk or posture score.
 */

export type Severity = 'critical' | 'high' | 'medium' | 'low';

export const SEVERITIES: readonly Severity[] = ['critical', 'high', 'medium', 'low'];

export const SEVERITY_LABEL: Record<Severity, string> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' };

export const SEVERITY_TONE: Record<Severity, Tone> = { critical: 'ember', high: 'solar', medium: 'amber', low: 'blue' };

export function asSeverity(level: string | null | undefined): Severity | null {
  const l = (level ?? '').trim().toLowerCase();
  return (SEVERITIES as readonly string[]).includes(l) ? (l as Severity) : null;
}

export const STATUS_LABEL: Record<CaseStatus, string> = {
  open: 'Open',
  triage: 'Triage',
  active: 'Mitigating',
  escalated: 'Escalated',
  closed: 'Closed',
};

export const STATUS_TONE: Record<CaseStatus, Tone> = {
  open: 'blue',
  triage: 'amber',
  active: 'sage',
  escalated: 'ember',
  closed: 'mute',
};

/** Mirrors the backend's forward-only `_VALID_TRANSITIONS` for investigation cases. */
export const NEXT_STATUSES: Record<CaseStatus, readonly CaseStatus[]> = {
  open: ['triage', 'active', 'escalated', 'closed'],
  triage: ['active', 'escalated', 'closed'],
  active: ['escalated', 'closed'],
  escalated: ['closed'],
  closed: [],
};

export type Category = 'agent' | 'case';

export const CATEGORY_LABEL: Record<Category, string> = { agent: 'Agent access', case: 'Investigation' };

export type RiskItem =
  | {
      readonly kind: 'finding';
      readonly key: string;
      readonly category: 'agent';
      readonly severity: Severity | null;
      readonly title: string;
      readonly finding: RiskFinding;
    }
  | {
      readonly kind: 'case';
      readonly key: string;
      readonly category: 'case';
      readonly severity: null;
      readonly title: string;
      readonly case: InvestigationCase;
    };

const SEVERITY_RANK: Record<Severity, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const STATUS_RANK: Record<CaseStatus, number> = { escalated: 0, active: 1, triage: 2, open: 3, closed: 4 };

function rank(item: RiskItem): number {
  if (item.kind === 'finding') return item.severity ? SEVERITY_RANK[item.severity] : 5;
  // Unrated cases sit between rated findings and unrated findings, escalated first.
  return 4 + STATUS_RANK[item.case.status] / 10;
}

export function findingKey(finding: RiskFinding, index: number): string {
  return `finding:${index}:${finding.code}`;
}

export function caseKey(c: InvestigationCase): string {
  return `case:${c.id}`;
}

/** Open register rows: every finding and every case that is not closed, most urgent first. */
export function buildRegister(findings: readonly RiskFinding[], cases: readonly InvestigationCase[]): RiskItem[] {
  const items: RiskItem[] = [
    ...findings.map((finding, index): RiskItem => ({
      kind: 'finding',
      key: findingKey(finding, index),
      category: 'agent',
      severity: asSeverity(finding.risk_level),
      title: finding.summary?.trim() || finding.code,
      finding,
    })),
    ...cases
      .filter(c => c.status !== 'closed')
      .map((c): RiskItem => ({ kind: 'case', key: caseKey(c), category: 'case', severity: null, title: c.title, case: c })),
  ];
  return items.sort((a, b) => rank(a) - rank(b));
}

export type SeverityFilter = 'all' | Severity | 'unrated';

export function matches(item: RiskItem, severity: SeverityFilter, category: 'all' | Category): boolean {
  if (category !== 'all' && item.category !== category) return false;
  if (severity === 'all') return true;
  if (severity === 'unrated') return item.severity === null;
  return item.severity === severity;
}

export function relativeAge(iso: string | null | undefined, now: number): string {
  if (!iso) return 'time not recorded';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 'time not recorded';
  const mins = Math.max(0, Math.round((now - t) / 60_000));
  if (mins < 60) return `${Math.max(1, mins)}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** App route for a case subject, or null when the kind has no page. */
export function subjectHref(kind: string, id: string): string | null {
  const k = kind.toLowerCase();
  const enc = encodeURIComponent(id);
  if (k === 'user') return `/users/${enc}`;
  if (k === 'agent' || k === 'agent_profile360' || k === 'agent_economic_identity') return `/agents/${enc}`;
  return null;
}
