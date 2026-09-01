import { useEffect, useState } from 'react';
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  ErrorState,
  LoadingState,
} from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

type Row = Record<string, unknown>;

interface RightsCenterData {
  policies: Row[];
  envelopes: Row[];
  decisions: Row[];
  evidenceManifests: Row[];
  impacts: Row[];
}

function rows(value: unknown): Row[] {
  if (!value || typeof value !== 'object') return [];
  const items = (value as { items?: unknown }).items;
  return Array.isArray(items) ? items.filter((item): item is Row => Boolean(item && typeof item === 'object')) : [];
}

function text(value: unknown): string {
  return value === null || value === undefined || value === '' ? '—' : String(value);
}

function Status({ value }: { readonly value: unknown }) {
  const status = text(value);
  const variant = ['allow', 'allow_with_obligations', 'rights_active', 'completed'].includes(status)
    ? 'success'
    : ['deny', 'blocked', 'failed', 'revoked'].includes(status)
      ? 'danger'
      : 'warning';
  return <Badge variant={variant}>{status}</Badge>;
}

function CountCard({ label, value }: { readonly label: string; readonly value: number }) {
  return (
    <Card>
      <CardContent>
        <p className="text-xs font-mono text-text-muted">{label}</p>
        <p className="mt-1 text-2xl font-semibold text-text-primary">{value}</p>
      </CardContent>
    </Card>
  );
}

export function RightsCenterPage() {
  const [data, setData] = useState<RightsCenterData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.all([
      api.rights.policies(),
      api.rights.envelopes(),
      api.rights.decisions(),
      api.rights.evidenceManifests(),
      api.rights.impacts(),
    ]).then(([policies, envelopes, decisions, evidenceManifests, impacts]) => {
      if (!active) return;
      setData({
        policies: rows(policies),
        envelopes: rows(envelopes),
        decisions: rows(decisions),
        evidenceManifests: rows(evidenceManifests),
        impacts: rows(impacts),
      });
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : 'Rights authority unavailable');
    });
    return () => { active = false; };
  }, []);

  if (error) {
    return (
      <div className="p-8">
        <ErrorState title="Rights Center unavailable" message={error} />
      </div>
    );
  }
  if (!data) return <div className="p-8"><LoadingState lines={8} /></div>;

  return (
    <div className="p-8 space-y-6 overflow-auto h-full">
      <div>
        <h1 className="text-xl font-semibold text-text-primary font-mono">Rights Center</h1>
        <p className="mt-1 text-sm text-text-secondary max-w-3xl">
          Your tenant&apos;s policies, evidence, rights envelopes, decisions, and impact work.
          A missing or unavailable authority record is shown as a blocked state; it is never treated as an empty result.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <CountCard label="Policies" value={data.policies.length} />
        <CountCard label="Artifact envelopes" value={data.envelopes.length} />
        <CountCard label="Decisions" value={data.decisions.length} />
        <CountCard label="Evidence manifests" value={data.evidenceManifests.length} />
        <CountCard label="Impact graphs" value={data.impacts.length} />
      </div>

      <Card>
        <CardHeader><CardTitle>Policy authority</CardTitle></CardHeader>
        <CardContent>
          <DataTable
            data={data.policies}
            keyExtractor={row => text(row.policy_set_id ?? row.id ?? 'policy')}
            columns={[
              { key: 'policy', header: 'Policy', render: row => <span className="font-mono text-xs">{text(row.policy_set_id ?? row.id)}</span> },
              { key: 'profile', header: 'Profile', render: row => text(row.rights_profile) },
              { key: 'revision', header: 'Revision', render: row => text(row.policy_revision) },
              { key: 'state', header: 'State', render: row => <Status value={row.activation_state} /> },
            ]}
            emptyMessage="No policy authority is registered for this tenant"
          />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Recent decisions</CardTitle></CardHeader>
          <CardContent>
            <DataTable
              data={data.decisions.slice(-20).reverse()}
              keyExtractor={row => text(row.decision_id ?? row.id ?? 'decision')}
              columns={[
                { key: 'decision', header: 'Decision', render: row => <span className="font-mono text-xs">{text(row.decision_id ?? row.id)}</span> },
                { key: 'action', header: 'Action', render: row => text(row.action) },
                { key: 'outcome', header: 'Outcome', render: row => <Status value={row.outcome} /> },
              ]}
              emptyMessage="No decisions recorded"
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Impact and remediation</CardTitle></CardHeader>
          <CardContent>
            <DataTable
              data={data.impacts}
              keyExtractor={row => text(row.impact_graph_id ?? row.id ?? 'impact')}
              columns={[
                { key: 'impact', header: 'Impact graph', render: row => <span className="font-mono text-xs">{text(row.impact_graph_id ?? row.id)}</span> },
                { key: 'roots', header: 'Roots', render: row => Array.isArray(row.root_refs) ? row.root_refs.length : '—' },
                { key: 'status', header: 'Status', render: row => <Status value={row.status} /> },
              ]}
              emptyMessage="No rights impacts recorded"
            />
          </CardContent>
        </Card>
      </div>

      <p className="text-xs text-text-muted font-mono border-t border-border-default pt-4">
        Evidence manifests are references to source evidence, not a substitute for contract or consent review.
        Rights Center does not grant access; the backend Rights Authority evaluates every material use.
      </p>
    </div>
  );
}

export default RightsCenterPage;
