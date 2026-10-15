/**
 * KYBER — Tenant Mirror (operator).
 *
 * Shows an operator exactly what one tenant sees on one surface, and — separately,
 * unmistakably — what only Kyber sees about it. The invariant the page exists to
 * make visible and falsifiable:
 *
 *   the tenant-visible result Aether returns for a tenant + surface + contract
 *   version is the same result the Mirror returns.
 *
 * Three design rules follow from that, and every part of this file serves one of them.
 *
 * 1. The two regions are separated to the point of being ugly about it. An operator
 *    must never mistake a Kyber-only diagnostic for something the tenant is looking
 *    at, because the failure mode is quoting an internal number back to a customer
 *    as their own. `tenantVisible` sits inside a solid-bordered region that also
 *    prints the raw payload; `operatorDiagnostics` sits inside a dashed, differently
 *    coloured region that says the tenant cannot see any of it.
 *
 * 2. Nothing tenant-visible is coerced. A count the backend returned as null renders
 *    as "Unknown" with the reason, never as 0 — see `TenantCount`. There is no `?? 0`
 *    in this file. A page that turns an unreadable value into a confident zero is
 *    lying about what the tenant sees, which is worse than not rendering at all.
 *
 * 3. Parity is never assumed. The banner has a first-class "could not be determined"
 *    state that shares no wording with the matched state (see `parity-banner.tsx`),
 *    and the state machine that decides between them lives in the feature module so
 *    it can be reasoned about on its own.
 *
 * The surface picker is built from `packages/shared/contracts/kyber-feature-surface-manifest.json`,
 * not from a list typed here. A parity-exempt surface is offered *with its written
 * exception reason* rather than silently offering no parity check — opting out is a
 * recorded decision, and hiding it would let someone re-decide it during an incident.
 */

import { useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  ScrollArea,
  Select,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  formatCount,
  formatUSD,
  useTimeContext,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import {
  DIAGNOSTIC_SECTIONS,
  MANIFEST_SCHEMA_VERSION,
  MAX_COMPARE_BYTES,
  MIRROR_SURFACES,
  compareTooLarge,
  deriveParityState,
  exemptionReason,
  findMirrorSurface,
  useTenantMirror,
  useTenantMirrorParity,
} from '@kyber/features/tenant-mirror';
import type {
  DiagnosticSection,
  MirrorEnvelope,
  MirrorQuery,
  MirrorSurface,
  OperatorDiagnostics,
} from '@kyber/features/tenant-mirror';
import { ParityBanner } from './parity-banner';

const PAGE_SUBTITLE =
  'One tenant, one surface, exactly as the tenant sees it — with Kyber-only diagnostics kept visibly apart from it. Kyber may add diagnostics; it may never recompute a tenant-visible value differently.';

export const TENANT_REGION_LABEL = 'TENANT-VISIBLE — this is exactly what the tenant sees';
export const OPERATOR_REGION_LABEL =
  'OPERATOR-ONLY — Kyber diagnostics the tenant never sees';

export const TENANT_REGION_RULE =
  'Every value below came out of the tenant’s own scoped read. Nothing on this page recomputed it. This is the only region you may quote back to a customer as their own result.';
export const OPERATOR_REGION_RULE =
  'Nothing below is on the tenant’s screen. These sections are additive operator metadata — never quote them to a customer as their own number, and never treat an empty section as “nothing wrong”.';

export const MASKED_NOTICE =
  'MASKED VIEW (D2) — identifiers below are redacted by the gateway. These are NOT the tenant’s real values, and this rendering is deliberately not parity-comparable.';

export const EMPTY_SECTION_NOTE =
  'Empty means not computed. It does not mean nothing is wrong.';

export const MIRROR_ERROR_TITLE = 'Unable to load the tenant mirror';

export const UNKNOWN_LABEL = 'Unknown';
export const NOT_RETURNED_NOTE =
  'The API did not return this value. Unknown — not zero.';

const SECTION_LABELS: Record<DiagnosticSection, string> = {
  quality: 'Quality',
  lineage: 'Lineage',
  policy: 'Policy',
  health: 'Health',
  recomputeOptions: 'Recompute options',
};

// ── Page-local honest primitives ─────────────────────────────────────────────
//
// Local on purpose: the equivalents on the Agent Access page are page-local there,
// and importing across page directories would couple two surfaces that answer to
// different backends. The rule they all keep is the same one — a value the API
// could not return is "Unknown" with its reason, never a confident zero.

function isUsdKey(name: string): boolean {
  const key = name.toLowerCase();
  return key === 'usd' || key.endsWith('_usd') || key.endsWith('_usd_value');
}

function UnknownValue({ note = NOT_RETURNED_NOTE }: { readonly note?: string }) {
  return (
    <span className="font-mono text-warning" title={note}>
      {UNKNOWN_LABEL}
    </span>
  );
}

/**
 * One tenant-visible count. `null` becomes "Unknown" plus the reason.
 * There is deliberately no `?? 0` here: a tenant looking at "we could not read
 * this" must not be described to an operator as a tenant looking at zero.
 */
function TenantCount({
  label,
  value,
}: {
  readonly label: string;
  readonly value: number | null | undefined;
}) {
  const locale = useTimeContext();
  const unknown = value === null || value === undefined;
  return (
    <div className="rounded border border-border-default bg-surface-raised px-3 py-2">
      <div className="text-[11px] font-mono text-text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold font-mono">
        {unknown ? (
          <UnknownValue />
        ) : (
          <span className="text-text-primary">{formatCount(value, locale)}</span>
        )}
      </div>
      {unknown && <div className="text-[10px] text-text-muted">{NOT_RETURNED_NOTE}</div>}
    </div>
  );
}

/** A tri-state flag. `null`/absent is "Unknown", never "false". */
function TenantFlag({
  label,
  value,
}: {
  readonly label: string;
  readonly value: boolean | null | undefined;
}) {
  return (
    <div className="rounded border border-border-default bg-surface-raised px-3 py-2">
      <div className="text-[11px] font-mono text-text-muted">{label}</div>
      <div className="mt-1">
        {value === null || value === undefined ? (
          <UnknownValue />
        ) : value ? (
          <Badge variant="warning">Yes</Badge>
        ) : (
          <Badge variant="default">No</Badge>
        )}
      </div>
    </div>
  );
}

/**
 * One diagnostic value. Money goes through the shared USD formatter — a number
 * formatted differently is a different number to the person reading it, and this
 * repo has exactly one formatter for that reason.
 */
function DiagnosticValue({ name, value }: { readonly name: string; readonly value: unknown }) {
  const locale = useTimeContext();
  if (value === null || value === undefined) {
    return <UnknownValue note="The backend did not compute this. Unknown, not zero." />;
  }
  if (typeof value === 'boolean') {
    return <Badge variant={value ? 'success' : 'default'}>{value ? 'true' : 'false'}</Badge>;
  }
  if (typeof value === 'number') {
    return (
      <span className="font-mono text-text-primary">
        {isUsdKey(name) ? formatUSD(value) : formatCount(value, locale)}
      </span>
    );
  }
  if (typeof value === 'string') {
    return <span className="font-mono text-text-primary break-all">{value}</span>;
  }
  if (Array.isArray(value) && value.length === 0) {
    return <span className="font-mono text-text-muted">(empty list)</span>;
  }
  return <span className="font-mono text-text-secondary break-all">{JSON.stringify(value)}</span>;
}

function DiagnosticRows({ section }: { readonly section: Record<string, unknown> }) {
  const keys = Object.keys(section).sort();
  return (
    <dl className="grid gap-1">
      {keys.map(key => (
        <div
          key={key}
          className="grid grid-cols-[minmax(0,14rem)_1fr] gap-2 border-b border-border-subtle py-1"
        >
          <dt className="text-[11px] font-mono text-text-muted">{key}</dt>
          <dd className="text-xs">
            <DiagnosticValue name={key} value={section[key]} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

// ── Tenant-visible region ────────────────────────────────────────────────────

function TenantVisibleRegion({
  envelope,
  masked,
}: {
  readonly envelope: MirrorEnvelope;
  readonly masked: boolean;
}) {
  const visible = envelope.tenantVisible;
  const counts = visible.entity_counts;
  const countKeys = counts ? Object.keys(counts).sort() : [];

  return (
    <section
      data-testid="tenant-visible-region"
      aria-label={TENANT_REGION_LABEL}
      className="rounded-lg border-4 border-accent bg-surface-base p-4 space-y-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="accent">TENANT-VISIBLE</Badge>
        <h2 className="font-mono text-sm font-semibold text-accent">{TENANT_REGION_LABEL}</h2>
      </div>
      <p className="text-[11px] text-text-secondary">{TENANT_REGION_RULE}</p>

      {masked && (
        <div
          role="alert"
          className="rounded border border-warning/60 bg-warning/10 px-3 py-2 text-xs font-mono text-warning"
        >
          {MASKED_NOTICE}
        </div>
      )}

      <div className="text-[11px] font-mono text-text-muted">
        surface {envelope.surface_id} · aether route {envelope.aether_route ?? UNKNOWN_LABEL} ·
        tenant {envelope.tenant_id} · contract {envelope.contract_version} · rendered at
        disclosure {envelope.disclosure ?? UNKNOWN_LABEL}
      </div>

      <div className="grid gap-2 md:grid-cols-4">
        <TenantCount label="Entities in this result" value={visible.entity_count} />
        {countKeys.map(key => (
          <TenantCount key={key} label={`${key} entities`} value={counts?.[key]} />
        ))}
        <TenantFlag label="Result truncated" value={visible.truncated} />
      </div>

      <div>
        <div className="mb-1 text-[11px] font-mono text-text-muted">
          The tenant-visible payload, verbatim — these are the bytes the parity digest is
          taken over.
        </div>
        <ScrollArea maxHeight="320px" className="rounded border border-border-default">
          <pre className="p-3 text-[11px] font-mono text-text-primary whitespace-pre-wrap break-all">
            {JSON.stringify(visible, null, 2)}
          </pre>
        </ScrollArea>
      </div>
    </section>
  );
}

// ── Operator-only region ─────────────────────────────────────────────────────

interface RecomputeRow {
  readonly rowKey: string;
  readonly optionId: string;
  readonly label: string;
  readonly capability: string;
  readonly offeredBy: string;
  readonly availableHere: boolean | null;
  readonly reason: string;
}

function readString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === 'string' && value.trim() !== '' ? value : UNKNOWN_LABEL;
}

function toRecomputeRows(options: readonly Record<string, unknown>[]): RecomputeRow[] {
  return options.map((option, index) => {
    const available = option['available_here'];
    return {
      rowKey: `${index}:${readString(option, 'option_id')}`,
      optionId: readString(option, 'option_id'),
      label: readString(option, 'label'),
      capability: readString(option, 'capability'),
      offeredBy: readString(option, 'offered_by'),
      availableHere: typeof available === 'boolean' ? available : null,
      reason: readString(option, 'reason'),
    };
  });
}

function RecomputeOptions({ options }: { readonly options: readonly Record<string, unknown>[] }) {
  const rows = toRecomputeRows(options);
  return (
    <>
      <p className="mb-2 text-[11px] text-text-muted">
        Declarations only. The Tenant Mirror is a read surface — nothing here runs from this
        page; each option names the plane that owns it.
      </p>
      <DataTable<RecomputeRow>
        data={rows}
        keyExtractor={row => row.rowKey}
        columns={[
          { key: 'label', header: 'Option', render: row => row.label },
          {
            key: 'capability',
            header: 'Capability',
            render: row => <span className="font-mono">{row.capability}</span>,
          },
          { key: 'offeredBy', header: 'Offered by', render: row => row.offeredBy },
          {
            key: 'availableHere',
            header: 'Available here',
            render: row =>
              row.availableHere === null ? (
                <UnknownValue />
              ) : row.availableHere ? (
                <Badge variant="success">Yes</Badge>
              ) : (
                <Badge variant="default">No</Badge>
              ),
          },
          { key: 'reason', header: 'Why', render: row => row.reason },
        ]}
      />
    </>
  );
}

function DiagnosticSectionBody({
  section,
  diagnostics,
}: {
  readonly section: DiagnosticSection;
  readonly diagnostics: OperatorDiagnostics;
}) {
  if (section === 'recomputeOptions') {
    const options = diagnostics.recomputeOptions;
    if (!options || options.length === 0) {
      return <EmptyState title="No recompute options declared" description={EMPTY_SECTION_NOTE} />;
    }
    return <RecomputeOptions options={options} />;
  }

  const body = diagnostics[section];
  if (!body || Object.keys(body).length === 0) {
    return (
      <EmptyState
        title={`${SECTION_LABELS[section]} was not computed`}
        description={EMPTY_SECTION_NOTE}
      />
    );
  }
  return <DiagnosticRows section={body} />;
}

function OperatorDiagnosticsRegion({
  diagnostics,
  grantedDisclosure,
}: {
  readonly diagnostics: OperatorDiagnostics;
  readonly grantedDisclosure: string | null;
}) {
  return (
    <section
      data-testid="operator-diagnostics-region"
      aria-label={OPERATOR_REGION_LABEL}
      className="rounded-lg border-4 border-dashed border-warning bg-surface-sunken p-4 space-y-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="warning">OPERATOR-ONLY</Badge>
        <h2 className="font-mono text-sm font-semibold text-warning">{OPERATOR_REGION_LABEL}</h2>
      </div>
      <p className="text-[11px] text-text-secondary">{OPERATOR_REGION_RULE}</p>
      <div className="text-[11px] font-mono text-text-muted">
        granted disclosure: {grantedDisclosure ?? UNKNOWN_LABEL}
      </div>

      <Tabs defaultValue="quality">
        <TabsList>
          {DIAGNOSTIC_SECTIONS.map(section => (
            <TabsTrigger key={section} value={section}>
              {SECTION_LABELS[section]}
            </TabsTrigger>
          ))}
        </TabsList>
        {DIAGNOSTIC_SECTIONS.map(section => (
          <TabsContent key={section} value={section}>
            <DiagnosticSectionBody section={section} diagnostics={diagnostics} />
          </TabsContent>
        ))}
      </Tabs>
    </section>
  );
}

// ── Controls ─────────────────────────────────────────────────────────────────

function surfaceOptions(): readonly { readonly value: string; readonly label: string }[] {
  return MIRROR_SURFACES.map(entry => ({
    value: entry.feature_id,
    label: entry.tenant_parity_required
      ? `${entry.feature_id} — ${entry.aether_route}`
      : `${entry.feature_id} — ${entry.aether_route} (parity exempt)`,
  }));
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function TenantMirrorPage() {
  const options = useMemo(surfaceOptions, []);
  const firstSurface: MirrorSurface | undefined = MIRROR_SURFACES[0];

  const [tenantId, setTenantId] = useState('');
  const [surfaceId, setSurfaceId] = useState(firstSurface?.feature_id ?? '');
  const [masked, setMasked] = useState(false);
  const [compareDraft, setCompareDraft] = useState('');
  const [appliedCompare, setAppliedCompare] = useState('');
  const [opened, setOpened] = useState(false);

  const surface = findMirrorSurface(surfaceId);
  const exempt = surface !== null && !surface.tenant_parity_required;
  const tooLarge = compareTooLarge(compareDraft);

  const mirrorQuery: MirrorQuery | null =
    opened && !exempt && surface !== null && tenantId.trim() !== ''
      ? { tenantId: tenantId.trim(), surface: surface.feature_id, masked }
      : null;

  const mirror = useTenantMirror(mirrorQuery);
  // A masked rendering is not parity-comparable, so the parity route is not called
  // for it at all — asking would only produce a refusal to explain away.
  const parity = useTenantMirrorParity(
    mirrorQuery === null || masked
      ? null
      : {
          tenantId: mirrorQuery.tenantId,
          surface: mirrorQuery.surface,
          compare: appliedCompare.trim() === '' ? undefined : appliedCompare.trim(),
        },
  );

  const parityState = deriveParityState({
    surface,
    access: parity.data,
    error: parity.error,
    masked,
  });

  const access = mirror.data;
  const envelope = access !== null && access.kind === 'granted' ? access.value : null;
  const forbidden = access !== null && access.kind === 'forbidden' ? access : null;

  return (
    <PageWrapper title="Tenant Mirror" subtitle={PAGE_SUBTITLE}>
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Mirror one tenant, one surface</CardTitle>
            <span className="text-[11px] font-mono text-text-muted">
              manifest contract {MANIFEST_SCHEMA_VERSION}
            </span>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-xs font-mono text-text-muted">
                Tenant ID (required)
                <Input
                  aria-label="Tenant ID"
                  value={tenantId}
                  placeholder="tenant identifier"
                  onChange={e => {
                    setTenantId(e.target.value);
                    setOpened(false);
                  }}
                />
              </label>
              <Select
                aria-label="Surface"
                label="Surface (from the feature-surface manifest)"
                value={surfaceId}
                options={options}
                onChange={value => {
                  setSurfaceId(value);
                  setOpened(false);
                }}
              />
              <Button
                size="sm"
                disabled={tenantId.trim() === '' || exempt}
                onClick={() => setOpened(true)}
              >
                Open mirror
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setMasked(current => !current)}
              >
                {masked ? 'Switch to tenant-visible view' : 'Switch to masked view'}
              </Button>
              <Button size="sm" variant="ghost" onClick={mirror.refresh}>
                Refresh
              </Button>
            </div>

            <div className="space-y-1">
              <label
                className="text-xs font-mono text-text-muted"
                htmlFor="aether-compare-payload"
              >
                Aether’s own tenantVisible payload (JSON) — supply it to get a located
                comparison. Without it the backend returns its digest only, and parity stays
                undetermined.
              </label>
              <textarea
                id="aether-compare-payload"
                aria-label="Aether tenantVisible payload"
                value={compareDraft}
                onChange={e => setCompareDraft(e.target.value)}
                rows={3}
                className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 font-mono text-[11px] text-text-primary"
              />
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  disabled={tenantId.trim() === '' || exempt || tooLarge}
                  onClick={() => {
                    setAppliedCompare(compareDraft);
                    setOpened(true);
                  }}
                >
                  Run parity comparison
                </Button>
                {tooLarge && (
                  <span className="text-xs font-mono text-danger">
                    Payload exceeds the backend’s {MAX_COMPARE_BYTES}-byte inline limit. Request
                    the digest without a payload and compare client-side against it.
                  </span>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {exempt && surface !== null ? (
          <ParityBanner state={{ kind: 'exempt', reason: exemptionReason(surface) }} />
        ) : forbidden !== null ? (
          <>
            <ParityBanner state={{ kind: 'forbidden', reason: forbidden.reason }} />
            <Card>
              <CardContent className="text-xs text-text-secondary">
                No tenant-visible payload and no diagnostics are rendered for this tenant,
                because none were read. This is an authorization outcome, not a failure of the
                page.
              </CardContent>
            </Card>
          </>
        ) : mirrorQuery === null ? (
          <EmptyState
            title="Name a tenant and open a surface"
            description="A mirror is only meaningful for one named tenant on one named surface."
          />
        ) : mirror.loading && access === null ? (
          <LoadingState lines={6} />
        ) : mirror.error !== null ? (
          <ErrorState
            title={MIRROR_ERROR_TITLE}
            message={mirror.error}
            onRetry={mirror.refresh}
          />
        ) : envelope === null ? (
          <EmptyState title="No mirror envelope returned" />
        ) : (
          <>
            {parity.loading && parity.data === null && !masked ? (
              <LoadingState lines={3} />
            ) : (
              <ParityBanner state={parityState} />
            )}
            <TenantVisibleRegion envelope={envelope} masked={masked} />
            <OperatorDiagnosticsRegion
              diagnostics={envelope.operatorDiagnostics}
              grantedDisclosure={access !== null && access.kind === 'granted' ? access.grantedDisclosure : null}
            />
          </>
        )}
      </div>
    </PageWrapper>
  );
}
