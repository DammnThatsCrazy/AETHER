/**
 * Local rendering primitives for the Agent Access operator page.
 *
 * Every component here exists to keep one rule: a `null` count is rendered as
 * "Unknown" with the reason it could not be computed, and never as `0`. There is
 * deliberately no `?? 0`, no `|| 0` and no `Number(value)` fallback anywhere in this
 * file — an operator who reads "0 unauthorized capabilities" when the truth is "we
 * could not read the authorizations" closes the investigation, which is the single
 * most damaging thing this surface can do.
 *
 * A truncated aggregate is labelled partial for the same reason: a number that covers
 * some of the tenants is not a total, and must never be presented as one.
 */

import { Badge, Card, CardContent, formatCount, useTimeContext } from '@aether/ui';

export const UNKNOWN_LABEL = 'Unknown';
export const NO_REASON_REPORTED =
  'The API reported no reason. Treat this as unknown, not as zero.';

/** Humanize a `missing_inputs` entry (`resource:reason:tenant_id=t1`) for an operator. */
export function describeMissingInput(entry: string): string {
  const [resource, ...rest] = entry.split(':');
  const detail = rest.join(':');
  const resourceLabel = (resource ?? entry).replace(/_/g, ' ');
  return detail ? `${resourceLabel} — ${detail.replace(/_/g, ' ')}` : resourceLabel;
}

export function UnknownReason({ reasons }: { readonly reasons: readonly string[] }) {
  return (
    <div className="mt-1 text-[10px] text-text-muted font-mono leading-snug">
      {reasons.length === 0 ? (
        NO_REASON_REPORTED
      ) : (
        <ul className="space-y-0.5">
          {reasons.map(reason => (
            <li key={reason}>· {describeMissingInput(reason)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface CountTileProps {
  readonly label: string;
  readonly value: number | null | undefined;
  readonly reasons?: readonly string[] | undefined;
}

/** One count. `null` becomes "Unknown" plus the reason — never a zero. */
export function CountTile({ label, value, reasons = [] }: CountTileProps) {
  const localeCtx = useTimeContext();
  const unknown = value === null || value === undefined;
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        {unknown ? (
          <>
            <div className="mt-1 text-2xl font-semibold text-warning font-mono">
              {UNKNOWN_LABEL}
            </div>
            <UnknownReason reasons={reasons} />
          </>
        ) : (
          <div className="mt-1 text-2xl font-semibold text-text-primary font-mono">
            {formatCount(value, localeCtx)}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** A count inside a table cell. Same rule, smaller. */
export function CountCell({ value }: { readonly value: number | null | undefined }) {
  const localeCtx = useTimeContext();
  if (value === null || value === undefined) {
    return <span className="text-warning font-mono">{UNKNOWN_LABEL}</span>;
  }
  return <span className="font-mono text-text-primary">{formatCount(value, localeCtx)}</span>;
}

/**
 * `authorized` is tri-state. `null` means the authorization read could not be
 * completed — it is NOT a denial, and must never render like one.
 */
export function AuthorizedBadge({ value }: { readonly value: boolean | null | undefined }) {
  if (value === null || value === undefined) {
    return <Badge variant="warning">{UNKNOWN_LABEL}</Badge>;
  }
  return value ? (
    <Badge variant="success">Authorized</Badge>
  ) : (
    <Badge variant="danger">Not authorized</Badge>
  );
}

interface PartialBannerProps {
  readonly subject: string;
  readonly missingInputs: readonly string[];
}

/** Shown whenever totals could not be computed. States plainly that this is not a total. */
export function PartialBanner({ subject, missingInputs }: PartialBannerProps) {
  return (
    <div
      role="status"
      className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
    >
      <div className="font-semibold font-mono">
        Partial read — {subject} totals are Unknown, not zero
      </div>
      <div className="mt-1 text-text-secondary">
        One or more inputs could not be read, so no cross-tenant total is shown. The
        per-tenant rows below are evidence from the tenants that did answer — their sum is
        not a total.
      </div>
      <UnknownReason reasons={missingInputs} />
    </div>
  );
}

/** Shown when every input was readable, so the totals really are totals. */
export function CompleteBanner({ summary }: { readonly summary: string }) {
  return (
    <div
      role="status"
      className="rounded border border-border-default bg-surface-raised px-3 py-2 text-xs text-text-secondary"
    >
      <span className="font-semibold font-mono text-success">Complete read</span> — {summary}
    </div>
  );
}

/** Per-tenant "we read all of it" / "we did not" marker. */
export function TenantKnownBadge({ known }: { readonly known: boolean }) {
  return known ? (
    <Badge variant="success">Complete</Badge>
  ) : (
    <Badge variant="warning">Partial</Badge>
  );
}
