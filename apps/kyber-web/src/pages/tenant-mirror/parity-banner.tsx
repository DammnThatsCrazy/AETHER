/**
 * The headline of the Tenant Mirror: did the invariant hold, and if not, where?
 *
 * Five states, and the distance between them is the whole point:
 *
 *  · matched          — quiet. The digest is shown so the operator can carry it.
 *  · diverged         — loud, and *located*. A digest that only says "different"
 *                       is close to useless at 3am, which is exactly why the
 *                       backend walks the payloads and returns JSON paths. Both
 *                       values and the classified reason are rendered per path,
 *                       and a capped list says it was capped rather than
 *                       understating the blast radius.
 *  · undetermined     — the comparison did not run, or could not be read. This
 *                       renders as its own alarming state and shares NO wording
 *                       with the matched state. Rendering "unavailable" as
 *                       "matched" — assuming parity held because nothing checked
 *                       — is the single most misleading thing this page could do.
 *  · not comparable   — a masked (D2) rendering. Redactions are not divergence.
 *  · exempt           — the manifest opted this surface out, with its written
 *                       reason. Opting out is allowed; doing it invisibly is not.
 *  · scope required   — a 403. Expected and explainable, never a generic error.
 *
 * Every non-matched state deliberately avoids the matched wording so that no
 * assertion, and no operator skim-reading mid-incident, can confuse the two.
 */

import type { ReactNode } from 'react';
import { Badge, Card, CardContent, DataTable } from '@aether/ui';
import type { Divergence, ParityComparison, ParityDigest, ParityState } from '@kyber/features/tenant-mirror';
import { divergencesTruncated } from '@kyber/features/tenant-mirror';

export const PARITY_MATCHED_LABEL =
  'Parity holds — the mirror returned exactly what the tenant sees';
export const PARITY_DIVERGED_LABEL =
  'PARITY BROKEN — the mirror and Aether returned different tenant-visible results';
export const PARITY_UNDETERMINED_LABEL = 'Parity could not be determined';
export const PARITY_NOT_COMPARABLE_LABEL = 'Not parity-comparable';
export const PARITY_EXEMPT_LABEL = 'This surface is exempt from tenant parity';
export const PARITY_SCOPE_REQUIRED_LABEL = 'Requires an active tenant access scope';

export const UNDETERMINED_WARNING =
  'Undetermined is not a pass. Nothing here says the tenant is seeing what you are seeing — do not close an investigation on this state.';

export const DIVERGENCE_TRUNCATED_NOTICE =
  'The backend capped this list. More divergences were located than are shown, so the blast radius is larger than the rows below.';

export const NO_LOCATED_DIVERGENCE =
  'The digests disagree but the backend located no divergence. Treat this as an unlocated break, never as parity.';

/** Human wording for `parity.Divergence.reason`, which is a stable vocabulary. */
const REASON_LABELS: Record<string, string> = {
  value_differs: 'Value differs',
  type_differs: 'Type differs',
  missing_in_mirror: 'Missing in mirror',
  missing_in_aether: 'Missing in Aether',
  length_differs: 'Length differs',
};

/** A canonicalised value, rendered so absence and null stay distinguishable. */
function jsonText(value: unknown): string {
  if (value === undefined) return '(absent)';
  if (value === null) return 'null';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function DigestLine({ digest, label }: { readonly digest: ParityDigest; readonly label: string }) {
  return (
    <div className="font-mono text-[11px] text-text-secondary break-all">
      <span className="text-text-muted">{label}: </span>
      {digest.algorithm}:{digest.digest}
      <span className="text-text-muted">
        {' '}
        (contract {digest.contract_version}, canonical bytes{' '}
        {digest.canonical_bytes === null ? 'not reported' : digest.canonical_bytes})
      </span>
    </div>
  );
}

interface BannerShellProps {
  readonly tone: 'ok' | 'alarm' | 'warn' | 'info';
  readonly role: 'status' | 'alert';
  readonly heading: string;
  readonly children?: ReactNode;
}

const TONE_STYLES: Record<BannerShellProps['tone'], string> = {
  ok: 'border-success/40 bg-success/10',
  alarm: 'border-danger bg-danger/15',
  warn: 'border-warning/60 bg-warning/10',
  info: 'border-border-default bg-surface-raised',
};

const TONE_HEADING: Record<BannerShellProps['tone'], string> = {
  ok: 'text-success',
  alarm: 'text-danger',
  warn: 'text-warning',
  info: 'text-text-secondary',
};

function BannerShell({ tone, role, heading, children }: BannerShellProps) {
  return (
    <Card data-testid="parity-banner" className={`border-2 ${TONE_STYLES[tone]}`}>
      <CardContent className="space-y-2">
        <div role={role} className={`font-mono text-sm font-semibold ${TONE_HEADING[tone]}`}>
          {heading}
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

// ── Diverged ─────────────────────────────────────────────────────────────────

interface DivergenceRow extends Divergence {
  readonly rowKey: string;
}

function DivergenceTable({ comparison }: { readonly comparison: ParityComparison }) {
  const rows: DivergenceRow[] = comparison.divergences.map((d, index) => ({
    ...d,
    rowKey: `${index}:${d.path}`,
  }));

  if (rows.length === 0) {
    return <div className="text-xs text-danger font-mono">{NO_LOCATED_DIVERGENCE}</div>;
  }

  return (
    <DataTable<DivergenceRow>
      data={rows}
      keyExtractor={row => row.rowKey}
      columns={[
        {
          key: 'path',
          header: 'JSON path',
          render: row => <span className="font-mono text-text-primary">{row.path}</span>,
        },
        {
          key: 'reason',
          header: 'Reason',
          render: row => (
            <Badge variant="danger">{REASON_LABELS[row.reason] ?? row.reason}</Badge>
          ),
        },
        {
          key: 'aether',
          header: 'Aether (the tenant’s own result)',
          render: row => <span className="font-mono break-all">{jsonText(row.aether)}</span>,
        },
        {
          key: 'mirror',
          header: 'Mirror (what Kyber returned)',
          render: row => <span className="font-mono break-all">{jsonText(row.mirror)}</span>,
        },
      ]}
    />
  );
}

function DivergedBanner({ comparison }: { readonly comparison: ParityComparison }) {
  const total = comparison.divergence_count;
  const truncated = divergencesTruncated(comparison);

  return (
    <BannerShell tone="alarm" role="alert" heading={PARITY_DIVERGED_LABEL}>
      <div className="text-xs text-text-primary">
        {total === null
          ? 'The backend did not report a divergence total, so the count below is what was returned, not a total.'
          : `${total} divergence(s) located at contract version ${comparison.contract_version}. ${comparison.divergences.length} shown.`}
      </div>
      {truncated && (
        <div className="text-xs font-mono text-danger">{DIVERGENCE_TRUNCATED_NOTICE}</div>
      )}
      <DivergenceTable comparison={comparison} />
      <DigestLine label="Aether digest" digest={comparison.aether_digest} />
      <DigestLine label="Mirror digest" digest={comparison.mirror_digest} />
    </BannerShell>
  );
}

// ── Banner ───────────────────────────────────────────────────────────────────

export function ParityBanner({ state }: { readonly state: ParityState }) {
  if (state.kind === 'matched') {
    return (
      <BannerShell tone="ok" role="status" heading={PARITY_MATCHED_LABEL}>
        <div className="text-xs text-text-secondary">
          Both payloads canonicalise to the same bytes under contract version{' '}
          {state.comparison.contract_version}. The contract version is part of the hashed
          material, so this is parity under this contract and no other.
        </div>
        <DigestLine label="Aether digest" digest={state.comparison.aether_digest} />
        <DigestLine label="Mirror digest" digest={state.comparison.mirror_digest} />
      </BannerShell>
    );
  }

  if (state.kind === 'diverged') {
    return <DivergedBanner comparison={state.comparison} />;
  }

  if (state.kind === 'undetermined') {
    return (
      <BannerShell tone="warn" role="alert" heading={PARITY_UNDETERMINED_LABEL}>
        <div className="text-xs text-text-primary">{state.reason}</div>
        <div className="text-xs font-mono text-warning">{UNDETERMINED_WARNING}</div>
        {state.digest !== null && <DigestLine label="Mirror digest" digest={state.digest} />}
      </BannerShell>
    );
  }

  if (state.kind === 'not_comparable') {
    return (
      <BannerShell tone="warn" role="alert" heading={PARITY_NOT_COMPARABLE_LABEL}>
        <div className="text-xs text-text-primary">{state.reason}</div>
        <div className="text-xs font-mono text-warning">{UNDETERMINED_WARNING}</div>
        {state.digest !== null && <DigestLine label="Mirror digest" digest={state.digest} />}
      </BannerShell>
    );
  }

  if (state.kind === 'exempt') {
    return (
      <BannerShell tone="info" role="status" heading={PARITY_EXEMPT_LABEL}>
        <div className="text-xs text-text-primary">{state.reason}</div>
        <div className="text-xs text-text-muted">
          The manifest records this exemption deliberately. There is no mirror to compare, and
          the absence of a parity check here is a recorded decision — not an oversight, and not
          a pass.
        </div>
      </BannerShell>
    );
  }

  return (
    <BannerShell tone="warn" role="alert" heading={PARITY_SCOPE_REQUIRED_LABEL}>
      <div className="text-xs text-text-primary">{state.reason}</div>
      <div className="text-xs text-text-muted">
        Tenant mirror reads are D3 and are gated on an active tenant access scope. Reaching this
        page granted nothing; the scope has to exist and be active for this tenant.
      </div>
    </BannerShell>
  );
}
