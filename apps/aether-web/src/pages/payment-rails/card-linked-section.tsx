/**
 * Card-linked Activity — nested inside Payment Rails.
 *
 * Observation-only surface: basis badges keep top-up, funding, spend,
 * refund, and unknown visibly separated; a top-up is never labelled as
 * spend. Filters cover program/issuer/network/basis/source/confidence/
 * chain/asset and volume bounds.
 */
import { useState } from 'react';
import {
  Badge, CapabilityStatePanel, Card, CardContent, CardHeader, CardTitle, DataTable,
  EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import { paymentscanCardPrograms, cardActivityBases } from '@aether/shared';
import {
  useCardLinkedFlows, type CardLinkedFlowRecord, type CardLinkedFilters,
} from '@aether-app/features/card-linked';

export function basisVariant(basis: string): 'success' | 'warning' | 'danger' | 'default' {
  if (basis === 'spend' || basis === 'settlement' || basis === 'clearing') return 'success';
  if (basis === 'topup' || basis === 'funding') return 'warning';
  if (basis === 'refund' || basis === 'reversal') return 'danger';
  return 'default'; // mixed / benchmark_only / unknown — rendered visibly
}

function FilterSelect({ label, value, onChange, options }: {
  readonly label: string;
  readonly value: string;
  readonly onChange: (v: string) => void;
  readonly options: readonly { value: string; label: string }[];
}) {
  return (
    <label className="flex flex-col text-xs text-text-secondary gap-1">
      {label}
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="bg-surface-secondary border border-border rounded px-2 py-1 text-sm text-text-primary"
      >
        <option value="">All</option>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export function CardLinkedActivitySection() {
  const [program, setProgram] = useState('');
  const [basis, setBasis] = useState('');
  const [source, setSource] = useState('');
  const [network, setNetwork] = useState('');

  const filters: CardLinkedFilters = {};
  if (program) filters.card_program_id = program;
  if (basis) filters.basis = basis;
  if (source) filters.source = source;
  if (network) filters.payment_network = network;

  const flows = useCardLinkedFlows(filters);

  const notEnabled = !!flows.error && (
    flows.error.toLowerCase().includes('not found') || flows.error.includes('404')
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Card-linked Activity</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-xs text-text-muted mb-3">
          Observed crypto-card / card-linked flows by program, issuer, and network.
          Top-up and funding are on-chain evidence; spend comes only from provider
          feeds. USD amounts are source-reported; Aether does not convert missing amounts.
          Aether never processes card payments or stores card numbers.
        </p>
        <div className="flex flex-wrap gap-3 mb-4">
          <FilterSelect
            label="Card program" value={program} onChange={setProgram}
            options={paymentscanCardPrograms.map(p => ({ value: p.slug, label: p.display_name }))}
          />
          <FilterSelect
            label="Basis" value={basis} onChange={setBasis}
            options={cardActivityBases.map(b => ({ value: b, label: b }))}
          />
          <FilterSelect
            label="Source" value={source} onChange={setSource}
            options={[
              { value: 'sdk', label: 'SDK' },
              { value: 'onchain_observer', label: 'On-chain observer' },
              { value: 'provider_webhook', label: 'Provider webhook' },
              { value: 'tenant_import', label: 'Tenant import' },
            ]}
          />
          <FilterSelect
            label="Network" value={network} onChange={setNetwork}
            options={[
              { value: 'visa', label: 'Visa' },
              { value: 'mastercard', label: 'Mastercard' },
              { value: 'unknown', label: 'Unknown' },
            ]}
          />
        </div>

        {flows.isLoading && !flows.data ? (
          <LoadingState lines={4} />
        ) : notEnabled ? (
          <CapabilityStatePanel
            state="disabled"
            title="Card-linked payment rails is not enabled"
            description="Enable AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED to observe card-linked activity."
          />
        ) : flows.error ? (
          <ErrorState title="Failed to load card-linked flows" message={flows.error} onRetry={flows.refetch} />
        ) : !flows.data || flows.data.items.length === 0 ? (
          <EmptyState
            title="No card-linked activity observed"
            description="Flows appear once SDK, on-chain, or provider evidence carries card-program context."
          />
        ) : (
          <DataTable
            columns={[
              { key: 'program', header: 'Program', render: (r: CardLinkedFlowRecord) => <span className="font-mono text-xs">{r.card_program_id ?? 'unknown'}</span> },
              { key: 'issuer', header: 'Issuer', render: (r: CardLinkedFlowRecord) => r.issuer_id ?? 'unknown' },
              { key: 'network', header: 'Network', render: (r: CardLinkedFlowRecord) => r.payment_network ?? 'unknown' },
              {
                key: 'basis', header: 'Basis',
                render: (r: CardLinkedFlowRecord) => <Badge variant={basisVariant(r.basis)}>{r.basis}</Badge>,
              },
              { key: 'chain', header: 'Chain', render: (r: CardLinkedFlowRecord) => r.chain ?? '—' },
              { key: 'asset', header: 'Asset', render: (r: CardLinkedFlowRecord) => r.asset ?? '—' },
              { key: 'amount', header: 'USD', render: (r: CardLinkedFlowRecord) => r.amount_usd ?? '—' },
              { key: 'source', header: 'Source', render: (r: CardLinkedFlowRecord) => <span className="text-xs">{r.source}</span> },
              {
                key: 'confidence', header: 'Confidence',
                render: (r: CardLinkedFlowRecord) => <span className="text-xs">{r.confidence}</span>,
              },
              { key: 'at', header: 'Occurred', render: (r: CardLinkedFlowRecord) => <span className="text-xs font-mono">{r.occurred_at ?? '—'}</span> },
            ]}
            data={flows.data.items}
            keyExtractor={r => r.id}
          />
        )}
      </CardContent>
    </Card>
  );
}
