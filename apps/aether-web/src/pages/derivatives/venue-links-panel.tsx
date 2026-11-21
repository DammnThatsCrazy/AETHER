import { useEffect, useRef, useState } from 'react';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, Input,
  LoadingState, Select, useQuery, useToast, queryCache,
} from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { asList, asRecord, fmt } from '@aether-app/components/domain-intelligence';

type Row = Record<string, unknown>;
type Method = 'wallet' | 'key' | 'oauth' | 'tenant_push';

// How each venue's account data is reached. Wallet venues read public account
// activity by address (no key); key venues need the member's read-only key;
// Coinbase futures also accepts OAuth through the Aether-hosted app.
const PEM_SECRET_VENUES: ReadonlySet<string> = new Set(['kalshi', 'coinbase_futures']);

const VENUES: ReadonlyArray<{ value: string; label: string; methods: [Method, ...Method[]] }> = [
  { value: 'hyperliquid', label: 'Hyperliquid', methods: ['wallet', 'tenant_push'] },
  { value: 'polymarket', label: 'Polymarket', methods: ['wallet', 'tenant_push'] },
  { value: 'dydx', label: 'dYdX', methods: ['wallet', 'tenant_push'] },
  { value: 'gmx', label: 'GMX', methods: ['wallet', 'tenant_push'] },
  { value: 'drift', label: 'Drift', methods: ['wallet', 'tenant_push'] },
  { value: 'kalshi', label: 'Kalshi', methods: ['key', 'tenant_push'] },
  { value: 'bybit', label: 'Bybit', methods: ['key', 'tenant_push'] },
  { value: 'coinbase_futures', label: 'Coinbase Financial Markets', methods: ['key', 'oauth', 'tenant_push'] },
];

const METHOD_LABELS: Record<Method, string> = {
  wallet: 'Wallet ownership proof',
  key: 'Read-only API key',
  oauth: 'Sign in with the venue (OAuth)',
  tenant_push: 'We already hold this activity',
};

const RELATIONSHIP_LABELS: Record<string, string> = {
  personal_account: "Member's own account",
  organization_system: 'Your organization',
};

const OAUTH_RETURN = '/derivatives/oauth/return';
const LINKS_KEY = 'derivatives:venue-links';

function statusVariant(status: unknown): 'success' | 'warning' | 'default' {
  if (status === 'active') return 'success';
  if (status === 'disconnected') return 'warning';
  return 'default';
}

export function VenueLinksPanel() {
  const { toast } = useToast();
  const links = useQuery({ key: LINKS_KEY, fetcher: () => api.venueLinks.list(), staleTime: 30_000 });
  const [venue, setVenue] = useState<string>(VENUES[0]?.value ?? 'hyperliquid');
  const methods: [Method, ...Method[]] = VENUES.find(v => v.value === venue)?.methods ?? ['tenant_push'];
  const [method, setMethod] = useState<Method>(methods[0]);
  const [form, setForm] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm(f => ({ ...f, [key]: e.target.value }));
  // Kalshi and Coinbase CDP keys sign with a PEM private key. A password input
  // strips the PEM's line breaks on paste, so those venues get a multiline field.
  const pemSecret = PEM_SECRET_VENUES.has(venue);

  function refresh() {
    queryCache.invalidate(LINKS_KEY);
    void links.refetch();
  }

  async function act(label: string, run: () => Promise<unknown>) {
    setBusy(true);
    try {
      await run();
      toast.success(label);
      refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const base = { subject_id: form.subject_id ?? '', venue, consent_receipt_id: form.consent_receipt_id ?? '' };
    if (method === 'oauth') {
      setBusy(true);
      try {
        const challenge = await api.venueLinks.oauthStart(venue, {
          subject_id: base.subject_id,
          account_ref: form.account_ref ?? '',
          consent_receipt_id: base.consent_receipt_id,
          redirect_uri: `${window.location.origin}${import.meta.env.BASE_URL.replace(/\/$/, '')}${OAUTH_RETURN}`,
        });
        window.location.assign(challenge.authorize_url);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : String(error));
        setBusy(false);
      }
      return;
    }
    await act('Account linked', async () => {
      if (method === 'wallet') {
        await api.venueLinks.linkWallet({
          ...base, wallet_address: form.wallet_address ?? '', chain_namespace: form.chain_namespace ?? '',
          proof_evidence_id: form.proof_evidence_id ?? '',
        });
      } else if (method === 'key') {
        await api.venueLinks.linkKey({
          ...base, account_ref: form.account_ref ?? '', api_key: form.api_key ?? '', scopes: ['read'],
          ...(form.api_secret ? { api_secret: form.api_secret } : {}),
          ...(form.passphrase ? { passphrase: form.passphrase } : {}),
        });
      } else {
        await api.venueLinks.linkTenantPush({ ...base, account_ref: form.account_ref ?? '' });
      }
      setForm({});
    });
  }

  const rows = asList(asRecord(links.data).items).map(asRecord) as Row[];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Linked venue accounts</CardTitle>
          <Button size="sm" variant="secondary" disabled={busy || rows.length === 0}
            onClick={() => act('Sync finished', () => api.venueLinks.syncAll())}>
            Sync all
          </Button>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-text-secondary mb-3">
            Each link is your member&apos;s own account (or activity you already hold), governed by its own
            consent and data-rights grant. Disconnect stops reading but keeps what was already observed;
            revoke ends the grant.
          </p>
          {links.isLoading && !links.data ? <LoadingState lines={3} /> : links.error ? (
            <EmptyState title="Venue account links are unavailable" description={String(links.error)} />
          ) : rows.length === 0 ? (
            <EmptyState title="No linked venue accounts" description="Link a member's venue account below to observe its activity." />
          ) : (
            <DataTable
              columns={[
                { key: 'venue', header: 'Venue', render: (r: Row) => fmt(r.venue) },
                { key: 'subject_id', header: 'Member', render: (r: Row) => fmt(r.subject_id) },
                { key: 'account_ref', header: 'Account', render: (r: Row) => <span className="font-mono text-xs">{fmt(r.account_ref)}</span> },
                { key: 'method', header: 'Linked by', render: (r: Row) => fmt(r.method) },
                { key: 'source_relationship', header: 'Source', render: (r: Row) => RELATIONSHIP_LABELS[String(r.source_relationship)] ?? 'Not yet governed' },
                { key: 'status', header: 'Status', render: (r: Row) => <Badge variant={statusVariant(r.status)}>{fmt(r.status)}</Badge> },
                { key: 'sync', header: 'Last read', render: (r: Row) => fmt(asRecord(r.sync_state).synced_at) },
                {
                  key: 'actions', header: '', render: (r: Row) => (
                    <div className="flex gap-2 justify-end">
                      {r.status === 'active' && (
                        <>
                          <Button size="sm" variant="ghost" disabled={busy}
                            onClick={() => act('Sync finished', () => api.venueLinks.sync(String(r.link_id)))}>Sync</Button>
                          <Button size="sm" variant="ghost" disabled={busy}
                            onClick={() => act('Disconnected', () => api.venueLinks.disconnect(String(r.link_id)))}>Disconnect</Button>
                        </>
                      )}
                      {r.status !== 'revoked' && (
                        <Button size="sm" variant="ghost" disabled={busy}
                          onClick={() => act('Revoked', () => api.venueLinks.revoke(String(r.link_id), 'revoked in Aether'))}>Revoke</Button>
                      )}
                    </div>
                  ),
                },
              ]}
              data={rows}
              keyExtractor={(r: Row) => String(r.link_id)}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Link a member&apos;s account</CardTitle></CardHeader>
        <CardContent>
          <form className="grid gap-3 md:grid-cols-2" onSubmit={submit}>
            <Select label="Venue" value={venue} options={VENUES.map(v => ({ value: v.value, label: v.label }))}
              onChange={v => { setVenue(v); setMethod((VENUES.find(x => x.value === v)?.methods ?? ['tenant_push' as Method])[0]); }} />
            <Select label="How" value={method} options={methods.map(m => ({ value: m, label: METHOD_LABELS[m] }))}
              onChange={v => setMethod(v as Method)} />
            <Input label="Member (subject id)" value={form.subject_id ?? ''} onChange={set('subject_id')} required />
            <Input label="Consent receipt id" value={form.consent_receipt_id ?? ''} onChange={set('consent_receipt_id')} required />
            {method === 'wallet' ? (
              <>
                <Input label="Wallet address" value={form.wallet_address ?? ''} onChange={set('wallet_address')} required />
                <Input label="Chain namespace (CAIP-2)" placeholder="eip155:137" value={form.chain_namespace ?? ''} onChange={set('chain_namespace')} required />
                <Input label="Ownership proof evidence id" value={form.proof_evidence_id ?? ''} onChange={set('proof_evidence_id')} required />
              </>
            ) : (
              <Input label="Venue account reference" value={form.account_ref ?? ''} onChange={set('account_ref')} required />
            )}
            {method === 'key' && (
              <>
                <Input label="Read-only API key (or key id)" value={form.api_key ?? ''} onChange={set('api_key')} required autoComplete="off" />
                {pemSecret ? (
                  <div className="space-y-1">
                    <label htmlFor="venue-api-secret" className="block text-xs font-medium text-text-secondary">Private key (PEM)</label>
                    <textarea
                      id="venue-api-secret"
                      className="w-full h-28 rounded-md border border-border-default bg-surface-base px-3 py-2 text-xs font-mono text-text-primary focus:outline-none focus:ring-1 focus:ring-accent resize-y"
                      value={form.api_secret ?? ''}
                      onChange={set('api_secret')}
                      placeholder="-----BEGIN PRIVATE KEY-----"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </div>
                ) : (
                  <Input label="Secret or private key" type="password" value={form.api_secret ?? ''} onChange={set('api_secret')} autoComplete="off" />
                )}
                <Input label="Passphrase (if the venue uses one)" type="password" value={form.passphrase ?? ''} onChange={set('passphrase')} autoComplete="off" />
                <p className="text-xs text-text-secondary md:col-span-2">
                  Use a key with read permission only. Keys that can trade, transfer or withdraw are refused, and the
                  key is stored encrypted and never shown again.
                </p>
              </>
            )}
            <div className="md:col-span-2">
              <Button type="submit" disabled={busy}>{method === 'oauth' ? 'Continue to the venue' : 'Link account'}</Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export function VenueOAuthReturnPage() {
  const params = new URLSearchParams(window.location.search);
  const state = params.get('state') ?? '';
  const code = params.get('code') ?? '';
  const denied = params.get('error');
  const [result, setResult] = useState<'pending' | 'linked' | 'failed'>(denied ? 'failed' : 'pending');
  const [message, setMessage] = useState<string>(denied ? `The venue returned: ${denied}` : '');
  const redeemed = useRef(false);

  useEffect(() => {
    // The state is single-use: redeem it exactly once, even under StrictMode.
    if (redeemed.current || denied || !state || !code) return;
    redeemed.current = true;
    api.venueLinks.oauthComplete({ state, code })
      .then(() => { setResult('linked'); setMessage('The account is linked. You can close this page or return to Derivatives.'); })
      .catch((error: unknown) => { setResult('failed'); setMessage(error instanceof Error ? error.message : String(error)); });
  }, [state, code, denied]);

  return (
    <main className="p-8 max-w-lg">
      <Card>
        <CardHeader><CardTitle>{result === 'failed' ? 'Linking did not finish' : 'Linking your account'}</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-text-secondary">{message || (state && code ? 'Finishing…' : 'This page needs the venue’s state and code.')}</p>
          <Button variant="secondary" onClick={() => window.location.assign(`${import.meta.env.BASE_URL.replace(/\/$/, '')}/derivatives`)}>
            Back to Derivatives
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
