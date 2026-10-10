/**
 * KYBER — Agent Access Intelligence (operator).
 *
 * Three operator-gated cross-tenant reads: authorization posture by state, declared-vs-
 * observed identity drift, and a tenant-bounded blast-radius review.
 *
 * Counts are rendered by level/state. There is deliberately no composite "access risk
 * score": the backend does not compute one, and inventing one here would give operators a
 * number with no definition behind it. Anything the API could not compute renders as
 * "Unknown" with its reason (see `honest-counts.tsx`), and a truncated aggregate is
 * labelled partial rather than shown as a total.
 */

import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import {
  DRIFT_FINDINGS_PARTIAL,
  useAuthorityPosture,
  useBlastRadius,
  useDriftPosture,
} from '@kyber/features/agent-access';
import type {
  AuthorityPosture,
  BlastRadius,
  BlastRadiusQuery,
  DriftPosture,
} from '@kyber/features/agent-access';
import {
  AuthorizedBadge,
  CompleteBanner,
  CountCell,
  CountTile,
  PartialBanner,
  TenantKnownBadge,
} from './honest-counts';

const PAGE_SUBTITLE =
  'Cross-tenant agent access posture, observed only. Aether inventories what it has seen — it never claims total reach, and it never reports an unreadable input as zero.';

const DRIFT_LABELS: Record<string, string> = {
  capabilities_examined: 'Capabilities examined',
  declared: 'Declared',
  drifted: 'Drifted',
  observed_only: 'Observed, never declared',
};

const STATE_ORDER = ['active', 'pending', 'expired', 'revoked'];

function orderedStates(counts: Record<string, number | null>): string[] {
  const known = STATE_ORDER.filter(s => s in counts);
  const extra = Object.keys(counts).filter(s => !STATE_ORDER.includes(s)).sort();
  return [...known, ...extra];
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, ' ');
}

function riskVariant(level: string): 'danger' | 'warning' | 'info' | 'default' {
  const normalized = level.toLowerCase();
  if (normalized === 'critical' || normalized === 'high') return 'danger';
  if (normalized === 'medium') return 'warning';
  if (normalized === 'low') return 'info';
  return 'default';
}

// ── Authorization posture ────────────────────────────────────────────────────

function AuthorityCard() {
  const { data, loading, error, refresh } = useAuthorityPosture();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Authorization posture (cross-tenant)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading && data === null ? (
          <LoadingState lines={4} />
        ) : error !== null ? (
          <ErrorState
            title="Unable to load authorization posture"
            message={error}
            onRetry={refresh}
          />
        ) : data === null ? (
          <EmptyState title="No authorization posture returned" />
        ) : (
          <AuthorityBody posture={data} />
        )}
      </CardContent>
    </Card>
  );
}

function AuthorityBody({ posture }: { readonly posture: AuthorityPosture }) {
  const states = orderedStates(posture.counts_by_state);
  return (
    <>
      {posture.totals_known ? (
        <CompleteBanner summary={posture.summary} />
      ) : (
        <PartialBanner subject="authorization" missingInputs={posture.missing_inputs} />
      )}

      {states.length === 0 ? (
        <EmptyState
          title="No capability authorizations observed"
          description="No tenant in the discovered set has granted a capability authorization yet."
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-4">
          {states.map(state => (
            <CountTile
              key={state}
              label={`${titleCase(state)} authorizations`}
              value={posture.counts_by_state[state]}
              reasons={posture.missing_inputs}
            />
          ))}
        </div>
      )}

      {posture.tenants.length === 0 ? (
        <EmptyState
          title="No tenants discovered"
          description="No tenant has an observed capability inventory yet."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-border-default text-text-muted">
                <th className="py-2 px-2 text-left">Tenant</th>
                <th className="py-2 px-2 text-left">Read</th>
                {states.map(state => (
                  <th key={state} className="py-2 px-2 text-right">
                    {titleCase(state)}
                  </th>
                ))}
                <th className="py-2 px-2 text-left">Why unknown</th>
              </tr>
            </thead>
            <tbody>
              {posture.tenants.map(row => (
                <tr key={row.tenant_id} className="border-b border-border-subtle">
                  <td className="py-2 px-2 text-text-primary">{row.tenant_id}</td>
                  <td className="py-2 px-2">
                    <TenantKnownBadge known={row.known} />
                  </td>
                  {states.map(state => (
                    <td key={state} className="py-2 px-2 text-right">
                      <CountCell value={row.counts_by_state[state]} />
                    </td>
                  ))}
                  <td className="py-2 px-2 text-text-muted">
                    {row.missing_inputs.length === 0 ? '' : row.missing_inputs.join(', ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[10px] text-text-muted">
        Authorization state is derived on read from the grant row, never stored. Tenants
        examined: {posture.tenant_discovery.tenants_examined} of{' '}
        {posture.tenant_discovery.distinct_tenants_seen} seen
        {posture.tenant_discovery.complete ? '' : ' (tenant discovery incomplete)'}.
      </p>
    </>
  );
}

// ── Identity drift ───────────────────────────────────────────────────────────

function DriftCard() {
  const { data, loading, error, refresh } = useDriftPosture();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Declared-vs-observed drift (cross-tenant)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading && data === null ? (
          <LoadingState lines={4} />
        ) : error !== null ? (
          <ErrorState title="Unable to load drift findings" message={error} onRetry={refresh} />
        ) : data === null ? (
          <EmptyState title="No drift posture returned" />
        ) : (
          <DriftBody posture={data} />
        )}
      </CardContent>
    </Card>
  );
}

function DriftBody({ posture }: { readonly posture: DriftPosture }) {
  const partialFindings = posture.findings_scope === DRIFT_FINDINGS_PARTIAL;
  const countKeys = Object.keys(DRIFT_LABELS).filter(key => key in posture.counts);

  return (
    <>
      {posture.totals_known ? (
        <CompleteBanner summary={posture.summary} />
      ) : (
        <PartialBanner subject="drift" missingInputs={posture.missing_inputs} />
      )}

      <div className="grid gap-3 md:grid-cols-4">
        {countKeys.map(key => (
          <CountTile
            key={key}
            label={DRIFT_LABELS[key] ?? titleCase(key)}
            value={posture.counts[key]}
            reasons={posture.missing_inputs}
          />
        ))}
      </div>

      {partialFindings && posture.findings.length > 0 && (
        <div className="text-xs text-warning font-mono">
          Partial — these findings are evidence from an incomplete scan, not every drifted
          capability.
        </div>
      )}

      {posture.findings.length === 0 ? (
        <EmptyState
          title={
            partialFindings
              ? 'No drift found in the part of the inventory that could be read'
              : 'No declared capability has drifted'
          }
          description={
            partialFindings
              ? 'The scan was incomplete, so this is not evidence that no drift exists.'
              : 'Every declared capability still matches what was observed. Undeclared capabilities are normal and are counted, not flagged.'
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-border-default text-text-muted">
                <th className="py-2 px-2 text-left">Tenant</th>
                <th className="py-2 px-2 text-left">Capability</th>
                <th className="py-2 px-2 text-left">Risk</th>
                <th className="py-2 px-2 text-left">Finding</th>
              </tr>
            </thead>
            <tbody>
              {posture.findings.map((finding, index) => (
                <tr
                  key={`${finding.tenant_id}:${finding.capability_id ?? index}`}
                  className="border-b border-border-subtle"
                >
                  <td className="py-2 px-2 text-text-secondary">{finding.tenant_id}</td>
                  <td className="py-2 px-2 text-text-primary">
                    {finding.capability_id ?? 'unattributed'}
                  </td>
                  <td className="py-2 px-2">
                    <Badge variant={riskVariant(finding.risk_level)}>{finding.risk_level}</Badge>
                  </td>
                  <td className="py-2 px-2 text-text-secondary">{finding.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ── Blast radius ─────────────────────────────────────────────────────────────

function BlastRadiusCard() {
  const [tenantId, setTenantId] = useState('');
  const [agentId, setAgentId] = useState('');
  const [query, setQuery] = useState<BlastRadiusQuery | null>(null);
  const { data, loading, error, refresh } = useBlastRadius(query);

  const canReview = tenantId.trim() !== '' && agentId.trim() !== '';

  return (
    <Card>
      <CardHeader>
        <CardTitle>Blast-radius review (one tenant)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-text-secondary">
          Bounded to a single named tenant by design. Reach is what this agent was observed
          able to touch — never a proof of total reach.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-text-muted font-mono">
            Tenant ID (required)
            <Input
              value={tenantId}
              onChange={e => setTenantId(e.target.value)}
              placeholder="tenant_001"
            />
          </label>
          <label className="text-xs text-text-muted font-mono">
            Agent ID
            <Input
              value={agentId}
              onChange={e => setAgentId(e.target.value)}
              placeholder="agent_001"
            />
          </label>
          <Button
            size="sm"
            disabled={!canReview}
            onClick={() => setQuery({ tenantId: tenantId.trim(), agentId: agentId.trim() })}
          >
            Review
          </Button>
        </div>

        {query === null ? (
          <EmptyState
            title="Name a tenant and an agent to review"
            description="A blast radius is only meaningful inside one tenant's observed inventory."
          />
        ) : loading && data === null ? (
          <LoadingState lines={3} />
        ) : error !== null ? (
          <ErrorState title="Unable to load blast radius" message={error} onRetry={refresh} />
        ) : data === null ? (
          <EmptyState title="No blast radius returned" />
        ) : (
          <BlastRadiusBody review={data} />
        )}
      </CardContent>
    </Card>
  );
}

function BlastRadiusBody({ review }: { readonly review: BlastRadius }) {
  const countKeys = Object.keys(review.counts);
  const capabilities = review.capabilities ?? [];
  const agents = review.agents ?? [];

  return (
    <>
      {review.exposure_known ? (
        <CompleteBanner summary={review.summary} />
      ) : (
        <PartialBanner subject="exposure" missingInputs={review.missing_inputs} />
      )}

      <div className="grid gap-3 md:grid-cols-3">
        {countKeys.map(key => (
          <CountTile
            key={key}
            label={titleCase(key)}
            value={review.counts[key]}
            reasons={review.missing_inputs}
          />
        ))}
      </div>

      {capabilities.length === 0 && agents.length === 0 ? (
        <EmptyState
          title={
            review.exposure_known
              ? 'Nothing observed within reach'
              : 'No evidence could be read'
          }
          description={
            review.exposure_known
              ? 'This agent was not observed connected to any server carrying a catalogued capability.'
              : 'The inputs needed for this review were not available, so no conclusion can be drawn.'
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-border-default text-text-muted">
                <th className="py-2 px-2 text-left">
                  {capabilities.length > 0 ? 'Capability' : 'Agent'}
                </th>
                {capabilities.length > 0 && <th className="py-2 px-2 text-left">Basis</th>}
                <th className="py-2 px-2 text-left">Authorized</th>
              </tr>
            </thead>
            <tbody>
              {capabilities.map(capability => (
                <tr key={capability.capability_id} className="border-b border-border-subtle">
                  <td className="py-2 px-2 text-text-primary">{capability.capability_id}</td>
                  <td className="py-2 px-2 text-text-secondary">{capability.basis}</td>
                  <td className="py-2 px-2">
                    <AuthorizedBadge value={capability.authorized} />
                  </td>
                </tr>
              ))}
              {agents.map(agent => (
                <tr key={agent.agent_id} className="border-b border-border-subtle">
                  <td className="py-2 px-2 text-text-primary">{agent.agent_id}</td>
                  <td className="py-2 px-2">
                    <AuthorizedBadge value={agent.authorized} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function AgentAccessPage() {
  return (
    <PageWrapper title="Agent Access Intelligence" subtitle={PAGE_SUBTITLE}>
      <div className="space-y-4">
        <AuthorityCard />
        <DriftCard />
        <BlastRadiusCard />
      </div>
    </PageWrapper>
  );
}
