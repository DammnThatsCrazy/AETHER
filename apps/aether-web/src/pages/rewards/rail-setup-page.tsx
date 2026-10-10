import { useState } from 'react';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  CapabilityStateBadge, EmptyState, ErrorState, Input, LoadingState,
  Modal, ModalBody, ModalFooter, ModalHeader, resolveCapabilityState,
} from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { useRewardsRails } from '@aether-app/features/rewards/use-rewards';

// ── Helpers ───────────────────────────────────────────────────────────────────

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

// ── Rail metadata ─────────────────────────────────────────────────────────────

interface RailMeta {
  id: string;
  label: string;
  description: string;
  tenantNote: string;
  beta?: boolean;
  fields?: RailField[];
}

interface RailField {
  key: string;
  label: string;
  placeholder: string;
  type?: 'text' | 'password' | 'number';
  required?: boolean;
}

const RAILS: RailMeta[] = [
  {
    id: 'recommend_only',
    label: 'Recommend Only',
    description: 'Eligibility decisions are recorded but no action payload is emitted. Use for dry-run or analytics-only campaigns.',
    tenantNote: 'No delivery action is produced. Tenant reads decisions via the Decisions API.',
  },
  {
    id: 'manual_approval',
    label: 'Manual Approval',
    description: 'Action payloads are held in the approval queue until an operator approves or rejects them.',
    tenantNote: 'Approve actions in the Approval Queue. After approval the payload is released for delivery by your system.',
  },
  {
    id: 'manual_export',
    label: 'Manual Export',
    description: 'Action payloads are batched and made available for CSV / API export. Tenant ingests the export and executes delivery.',
    tenantNote: 'Download exports from the Exports section. Your team executes the rewards using the exported payload.',
  },
  {
    id: 'tenant_webhook',
    label: 'Tenant Webhook',
    description: 'Aether POSTs signed action payloads to your HTTPS endpoint. Your system receives the payload and executes the reward.',
    tenantNote: 'Your webhook endpoint must acknowledge with HTTP 200. Tenant executes the reward on receipt.',
    fields: [
      { key: 'webhook_url', label: 'Webhook URL', placeholder: 'https://your-api.example.com/aether/rewards', required: true },
      { key: 'secret_ref', label: 'HMAC Secret Reference', placeholder: 'e.g. secret:prod/aether/webhook-secret', type: 'password' },
    ],
  },
  {
    id: 'onchain_claim',
    label: 'On-Chain Claim',
    description: 'Aether generates a cryptographic eligibility proof. User redeems the proof on your smart contract to claim the reward.',
    tenantNote: 'Deploy and operate the smart contract. Aether only produces the proof. Tenant contract executes the on-chain reward.',
    fields: [
      { key: 'contract_address', label: 'Contract Address', placeholder: '0x...', required: true },
      { key: 'chain_id', label: 'Chain ID', placeholder: '1 (Ethereum), 137 (Polygon), 8453 (Base)…', type: 'number', required: true },
      { key: 'vm_type', label: 'VM Type', placeholder: 'evm / svm / move', required: true },
    ],
  },
];

const BETA_RAILS: RailMeta[] = [
  {
    id: 'stripe_credit',
    label: 'Stripe Credit',
    description: 'Action payload includes a Stripe customer credit amount. Tenant applies the credit via Stripe API.',
    tenantNote: 'Tenant Stripe account executes the credit. Aether does not hold or move funds.',
    beta: true,
    fields: [
      { key: 'stripe_account_id', label: 'Stripe Account ID', placeholder: 'acct_...', required: true },
    ],
  },
  {
    id: 'loyalty_points',
    label: 'Loyalty Points',
    description: 'Action payload specifies a loyalty point award amount. Tenant applies points in their loyalty system.',
    tenantNote: 'Tenant loyalty platform executes the point award. Aether produces the eligibility payload only.',
    beta: true,
  },
  {
    id: 'coupon',
    label: 'Coupon / Voucher',
    description: 'Action payload triggers coupon generation. Tenant issues the coupon via their commerce platform.',
    tenantNote: 'Tenant commerce platform creates and delivers the coupon. Aether does not issue or store coupon codes.',
    beta: true,
    fields: [
      { key: 'coupon_prefix', label: 'Coupon Code Prefix', placeholder: 'AETHER-' },
    ],
  },
  {
    id: 'internal_credit',
    label: 'Internal Credit',
    description: 'Action payload specifies an internal account credit. Tenant applies the credit to the user account in their system.',
    tenantNote: 'Tenant internal ledger executes the credit. Campaign budget policy is managed by the tenant.',
    beta: true,
  },
  {
    id: 'x402_credit',
    label: 'x402 Credit',
    description: 'Action payload specifies an x402 HTTP credit amount for AI agent interactions. Tenant applies the credit.',
    tenantNote: 'Tenant x402 infrastructure executes the credit. Aether produces the eligibility signal only.',
    beta: true,
  },
];

// ── Rail config form ──────────────────────────────────────────────────────────

interface ConfigFormState {
  [key: string]: string;
}

interface ConfigPanelProps {
  readonly rail: RailMeta;
  readonly currentConfig: Record<string, unknown>;
  readonly onClose: () => void;
  readonly onSaved: () => void;
}

type PanelStep = 'configure' | 'verifying' | 'done' | 'error';

function RailConfigPanel({ rail, currentConfig, onClose, onSaved }: ConfigPanelProps) {
  const initialState: ConfigFormState = {};
  for (const f of rail.fields ?? []) {
    initialState[f.key] = fmt(currentConfig[f.key], '');
  }

  const [form, setForm] = useState<ConfigFormState>(initialState);
  const [genericJson, setGenericJson] = useState(
    rail.fields ? '' : JSON.stringify(currentConfig, null, 2)
  );
  const [step, setStep] = useState<PanelStep>('configure');
  const [verifyResult, setVerifyResult] = useState<'ok' | 'fail' | null>(null);
  const [errorMsg, setErrorMsg] = useState('');

  function setField(key: string, value: string) {
    setForm(prev => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    setStep('verifying');
    setErrorMsg('');
    try {
      let config: Record<string, unknown>;
      if (rail.fields) {
        config = { ...form };
      } else {
        try {
          config = JSON.parse(genericJson || '{}') as Record<string, unknown>;
        } catch {
          config = {};
        }
      }

      await api.rewards.configureRail(rail.id, config);

      try {
        await api.rewards.verifyRail(rail.id);
        setVerifyResult('ok');
      } catch {
        setVerifyResult('fail');
      }

      setStep('done');
      onSaved();
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Configuration failed');
      setStep('error');
    }
  }

  async function handleVerifyOnly() {
    setStep('verifying');
    setErrorMsg('');
    try {
      await api.rewards.verifyRail(rail.id);
      setVerifyResult('ok');
      setStep('done');
    } catch (e) {
      setVerifyResult('fail');
      setErrorMsg(e instanceof Error ? e.message : 'Verification failed');
      setStep('error');
    }
  }

  const isMissingRequired = (rail.fields ?? []).some(f => f.required && !form[f.key]?.trim());

  return (
    <Modal open onClose={onClose}>
      <ModalHeader>
        <div className="flex items-center gap-2">
          <span className="font-semibold text-text-primary">{rail.label}</span>
          {rail.beta && <Badge variant="warning" size="sm">Beta</Badge>}
        </div>
        <p className="text-xs text-text-muted mt-1">{rail.description}</p>
      </ModalHeader>

      <ModalBody className="space-y-4">
        {/* Tenant note */}
        <div className="rounded-md bg-surface-raised border border-border-default px-3 py-2">
          <p className="text-xs text-text-secondary">
            <strong className="text-text-primary">Tenant responsibility:</strong> {rail.tenantNote}
          </p>
        </div>

        {step === 'configure' && (
          <>
            {rail.fields ? (
              rail.fields.map(f => (
                <Input
                  key={f.key}
                  label={f.label + (f.required ? ' *' : '')}
                  type={f.type ?? 'text'}
                  value={form[f.key] ?? ''}
                  onChange={e => setField(f.key, e.target.value)}
                  placeholder={f.placeholder}
                  autoComplete="off"
                />
              ))
            ) : (
              <div className="space-y-1">
                <label className="block text-xs font-medium text-text-secondary">Configuration JSON</label>
                <textarea
                  className="w-full h-32 rounded-md border border-border-default bg-surface-base px-3 py-2 text-xs font-mono text-text-primary focus:outline-none focus:ring-1 focus:ring-accent resize-y"
                  value={genericJson}
                  onChange={e => setGenericJson(e.target.value)}
                  placeholder="{}"
                />
              </div>
            )}
          </>
        )}

        {step === 'verifying' && (
          <div className="flex items-center gap-2 text-sm text-text-secondary">
            <span className="animate-spin inline-block">⟳</span>
            Saving and verifying connection…
          </div>
        )}

        {step === 'done' && (
          <div className="space-y-1.5">
            <p className="text-sm text-success font-medium">Rail configured.</p>
            {verifyResult === 'ok' && (
              <p className="text-xs text-text-muted">Connection verified successfully.</p>
            )}
            {verifyResult === 'fail' && (
              <p className="text-xs text-warning">
                Saved, but connection verification failed. Check your configuration and use "Verify Connection" from the rails list.
              </p>
            )}
          </div>
        )}

        {step === 'error' && (
          <p className="text-sm text-danger">{errorMsg}</p>
        )}
      </ModalBody>

      <ModalFooter>
        {(step === 'done' || step === 'error') ? (
          <div className="flex items-center justify-between w-full">
            {step === 'error' && (
              <Button size="sm" variant="secondary" onClick={() => { setStep('configure'); setErrorMsg(''); }}>
                Back
              </Button>
            )}
            <div className="flex items-center gap-2 ml-auto">
              {step === 'error' && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => { void handleVerifyOnly(); }}
                  disabled={step !== 'error'}
                >
                  Retry Verify
                </Button>
              )}
              <Button size="sm" variant="secondary" onClick={onClose}>Close</Button>
            </div>
          </div>
        ) : (
          <>
            <Button size="sm" variant="secondary" onClick={onClose} disabled={step === 'verifying'}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => { void handleSave(); }}
              disabled={step === 'verifying' || isMissingRequired}
            >
              {step === 'verifying' ? 'Saving…' : 'Save & Verify'}
            </Button>
          </>
        )}
      </ModalFooter>
    </Modal>
  );
}

// ── Rail card ─────────────────────────────────────────────────────────────────

interface RailCardProps {
  readonly meta: RailMeta;
  readonly serverRail: Record<string, unknown> | null;
  readonly onConfigure: () => void;
}

function RailCard({ meta, serverRail, onConfigure }: RailCardProps) {
  const rawStatus = serverRail ? fmt(serverRail.status, 'not_configured') : 'not_configured';
  const state = resolveCapabilityState(rawStatus) ?? 'not_configured';

  return (
    <div className="flex items-start justify-between rounded-lg border border-border-default px-4 py-3 gap-4">
      <div className="flex-1 min-w-0 space-y-0.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-sm text-text-primary">{meta.label}</span>
          {meta.beta && <Badge variant="warning" size="sm">Beta</Badge>}
          <CapabilityStateBadge
            state={state}
            label={rawStatus.replace(/_/g, ' ')}
            reason={`rail status: ${rawStatus}`}
            size="sm"
          />
        </div>
        <p className="text-xs text-text-muted">{meta.description}</p>
        <p className="text-xs text-text-secondary italic">{meta.tenantNote}</p>
      </div>
      <div className="shrink-0 flex items-center gap-2">
        <Button size="sm" variant="secondary" onClick={onConfigure}>
          Configure
        </Button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function RewardRailSetupPage() {
  const { data, isLoading, error, refetch } = useRewardsRails();
  const [configuringRail, setConfiguringRail] = useState<RailMeta | null>(null);

  const d = asRecord(data);
  const serverRails = asList(d.rails ?? d.items ?? data).map(asRecord);

  function findServerRail(railId: string): Record<string, unknown> | null {
    return serverRails.find(r => fmt(r.id ?? r.rail_id) === railId) ?? null;
  }

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Reward Delivery Rails</h1>
          <p className="text-sm text-text-secondary mt-0.5">
            Configure how verified eligibility action payloads reach your systems.
            Aether produces the payload — tenant rails execute the reward.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => { void refetch?.(); }}>
          Refresh
        </Button>
      </div>

      {error && (
        <ErrorState
          title="Failed to load rail configuration"
          message={String(error)}
        />
      )}

      {isLoading && <LoadingState lines={6} />}

      {!isLoading && !error && (
        <>
          {/* Production rails */}
          <Card>
            <CardHeader>
              <CardTitle>Delivery Rails</CardTitle>
            </CardHeader>
            <CardContent>
              {serverRails.length === 0 && (
                <EmptyState
                  title="No rails returned from server"
                  description="Configure a rail below to begin. Aether produces action payloads — your configured rail delivers them."
                />
              )}
              <div className="space-y-3">
                {RAILS.map(meta => (
                  <RailCard
                    key={meta.id}
                    meta={meta}
                    serverRail={findServerRail(meta.id)}
                    onConfigure={() => setConfiguringRail(meta)}
                  />
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Beta rails */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <CardTitle>Beta Rails</CardTitle>
                <Badge variant="warning" size="sm">Preview</Badge>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-text-muted mb-4">
                Beta rails are available for early access. APIs and payload formats may change before GA.
                Contact support to enable beta rails for your tenant.
              </p>
              <div className="space-y-3">
                {BETA_RAILS.map(meta => (
                  <RailCard
                    key={meta.id}
                    meta={meta}
                    serverRail={findServerRail(meta.id)}
                    onConfigure={() => setConfiguringRail(meta)}
                  />
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* No-custody notice */}
      <p className="text-xs text-text-muted border border-border-default rounded-md px-3 py-2 bg-surface-raised">
        <strong className="text-text-secondary">No-custody platform:</strong> Aether verifies eligibility and produces action payloads only.
        Each rail defines how the payload reaches your infrastructure. Tenant systems are responsible for executing reward delivery and managing campaign budget policy.
      </p>

      {/* Config modal */}
      {configuringRail && (
        <RailConfigPanel
          rail={configuringRail}
          currentConfig={findServerRail(configuringRail.id) ?? {}}
          onClose={() => setConfiguringRail(null)}
          onSaved={() => { setConfiguringRail(null); void refetch?.(); }}
        />
      )}
    </div>
  );
}
