/**
 * Presentation primitives for the Agent Access surface.
 *
 * These exist for one reason: the Agent Access APIs deliberately answer "we do
 * not know" with `null` counts, an `exposure_known: false`-style flag and a
 * `missing_inputs` list, and they disclose every bounded read that truncated.
 * Rendering any of that as `0`, `—`, `None`, or an empty bar destroys the
 * guarantee at the last mile: zero is a claim about reality, and an unknown
 * count is precisely the absence of one.
 *
 * So, in this module:
 *   - `CountStat` / `CountValue` render `null`/`undefined` as **Unknown** with
 *     the reason from `missing_inputs` shown to the user — never a number.
 *   - `PartialLabel` sits NEXT TO a number the backend flagged as partial
 *     (`truncated` / `sampled` / `counts.scope: "scanned_window_only"`), so a
 *     window-scoped count is never presented as a total.
 *   - `AuthorizedBadge` treats `authorized` as tri-state; `null` renders as a
 *     neutral "Unknown", never as a denial.
 */
import type { ReactNode } from 'react';
import { Badge } from '@aether/ui';

/** A count that may be unknown. `null`/`undefined` mean "not computed", never 0. */
export type UnknownableCount = number | null | undefined;

export function isUnknownCount(value: UnknownableCount): boolean {
  return value === null || value === undefined || Number.isNaN(value);
}

/**
 * Human-readable gloss for the backend's `missing_inputs` tokens. The raw token
 * is always shown alongside the gloss — it is the operator's only handle on
 * which read failed, and paraphrasing it away would hide the evidence.
 */
const MISSING_INPUT_LABELS: Record<string, string> = {
  capability_installations: 'no observed agent-to-server installation',
  capability_catalog: 'capability outside the scanned catalog window',
  capability_authorizations: 'authorization read hit its scan limit',
  capability_server_binding: 'an installation had no observed server identity',
  capability_access_graph: 'the access graph could not be queried',
  capability_reach_pairs: 'reach relations exceeded the compute budget',
};

export function describeMissingInput(token: string): string {
  const head = token.split(':')[0] ?? token;
  const gloss = MISSING_INPUT_LABELS[head];
  return gloss ? `${gloss} (${token})` : token;
}

export function statTestId(label: string): string {
  return `agent-access-stat-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')}`;
}

/** The canonical unknown marker. Deliberately a word, never a dash or a zero. */
export function UnknownValue({ className }: { readonly className?: string | undefined }) {
  return (
    <span data-unknown="true" className={className}>
      <Badge variant="warning">Unknown</Badge>
    </span>
  );
}

/** Sits next to a number the backend flagged as partial. Never replaces the number. */
export function PartialLabel({ reason }: { readonly reason: string }) {
  return (
    <Badge variant="warning" size="sm" className="align-middle">
      Partial — {reason}
    </Badge>
  );
}

interface CountStatProps {
  readonly label: string;
  readonly value: UnknownableCount;
  /** `missing_inputs` entries explaining why the value could not be computed. */
  readonly reasons?: readonly string[] | undefined;
  /** Set when the backend says this number covers a bounded window, not the whole set. */
  readonly partialReason?: string | undefined;
  readonly hint?: string | undefined;
  readonly testId?: string | undefined;
}

/**
 * One labelled count in a `<dl>`. An unknown value shows "Unknown" plus the
 * reason(s); it never falls back to a number, a dash, or an empty cell.
 */
export function CountStat({ label, value, reasons, partialReason, hint, testId }: CountStatProps) {
  const unknown = isUnknownCount(value);
  const explained = (reasons ?? []).map(describeMissingInput);
  return (
    <div
      data-testid={testId ?? statTestId(label)}
      className="bg-surface-raised border border-border-default rounded-md px-4 py-3"
    >
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd className="mt-0.5 text-xl font-semibold text-text-primary flex flex-wrap items-center gap-2">
        {unknown ? <UnknownValue /> : <span>{value}</span>}
        {!unknown && partialReason ? <PartialLabel reason={partialReason} /> : null}
      </dd>
      {unknown ? (
        <p className="text-[11px] text-text-secondary mt-1">
          {explained.length > 0
            ? `Not computed — ${explained.join('; ')}`
            : 'Not computed — this value could not be determined. Unknown is not zero.'}
        </p>
      ) : null}
      {!unknown && hint ? <p className="text-[11px] text-text-muted mt-1">{hint}</p> : null}
    </div>
  );
}

/**
 * Section-level "we do not know" notice. Visually and semantically distinct from
 * an empty state (nothing observed) and from an error state (the read failed).
 */
export function UnknownNotice({
  title,
  detail,
  reasons,
}: {
  readonly title: string;
  readonly detail?: string | undefined;
  readonly reasons?: readonly string[] | undefined;
}) {
  const entries = reasons ?? [];
  return (
    <div
      role="note"
      data-unknown="true"
      className="border border-warning/40 bg-warning/10 rounded-md px-3 py-2.5"
    >
      <p className="text-xs font-semibold text-warning">{title}</p>
      {detail ? <p className="text-xs text-text-secondary mt-1">{detail}</p> : null}
      {entries.length > 0 ? (
        <>
          <p className="text-[11px] text-text-secondary mt-2">Missing inputs:</p>
          <ul className="mt-0.5 space-y-0.5 list-disc list-inside">
            {entries.map(entry => (
              <li key={entry} className="text-[11px] text-text-secondary">
                {describeMissingInput(entry)}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

/** Section-level "this answer is bounded" notice, for truncated / sampled reads. */
export function PartialNotice({
  title,
  reasons,
}: {
  readonly title: string;
  readonly reasons: readonly string[];
}) {
  if (reasons.length === 0) return null;
  return (
    <div role="note" data-partial="true" className="border border-warning/40 bg-warning/10 rounded-md px-3 py-2.5">
      <p className="text-xs font-semibold text-warning">{title}</p>
      <ul className="mt-1 space-y-0.5 list-disc list-inside">
        {reasons.map(reason => (
          <li key={reason} className="text-[11px] text-text-secondary">{reason}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Tri-state authorization. `null` is "we could not determine this", styled
 * neutrally — styling it as a denial would invent a revocation that never happened.
 */
export function AuthorizedBadge({ authorized }: { readonly authorized: boolean | null | undefined }) {
  if (authorized === true) return <Badge variant="success">Authorized</Badge>;
  if (authorized === false) return <Badge variant="danger">Not authorized</Badge>;
  return (
    <span data-unknown="true">
      <Badge variant="default">Unknown</Badge>
    </span>
  );
}

/** Backend risk vocabulary → badge tone. No composite score is derived anywhere. */
export function riskVariant(level: string): 'danger' | 'warning' | 'info' | 'default' {
  const normalized = level.trim().toLowerCase();
  if (normalized === 'critical' || normalized === 'high') return 'danger';
  if (normalized === 'medium') return 'warning';
  if (normalized === 'low') return 'info';
  return 'default';
}

/** Derived authorization lifecycle state → badge tone. */
export function authorizationStateVariant(state: string): 'success' | 'warning' | 'danger' | 'info' | 'default' {
  const normalized = state.trim().toLowerCase();
  if (normalized === 'active') return 'success';
  if (normalized === 'revoked') return 'danger';
  if (normalized === 'expired') return 'warning';
  if (normalized === 'pending') return 'info';
  return 'default';
}

/** Counts by observed risk level. Never collapsed into a single number. */
export function RiskLevelCounts({
  known,
  byLevel,
}: {
  readonly known: boolean | null | undefined;
  readonly byLevel: Record<string, number>;
}) {
  if (known === false) {
    return <UnknownValue />;
  }
  const entries = Object.entries(byLevel);
  if (entries.length === 0) {
    return <span className="text-xs text-text-muted">No risk levels observed</span>;
  }
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {entries
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([level, count]) => (
          <Badge key={level} variant={riskVariant(level)}>
            {level}: {count}
          </Badge>
        ))}
    </span>
  );
}

/** A titled page section with a real heading and an accessible name. */
export function Section({
  id,
  title,
  description,
  children,
}: {
  readonly id: string;
  readonly title: string;
  readonly description?: string | undefined;
  readonly children: ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-heading`} className="space-y-3">
      <div>
        <h2 id={`${id}-heading`} className="text-base font-semibold text-text-primary">
          {title}
        </h2>
        {description ? <p className="text-xs text-text-secondary mt-0.5">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}
