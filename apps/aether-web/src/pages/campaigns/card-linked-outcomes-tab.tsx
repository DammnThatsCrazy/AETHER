/**
 * Campaign360 → Card-linked Outcomes.
 *
 * Top-up and spend metrics are always separated, and every payload carries
 * an attribution basis (direct/temporal/probabilistic/benchmark_only/
 * insufficient_evidence) — correlation is never presented as causality.
 */
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { useCardLinkedCampaignOutcomes } from '@aether-app/features/card-linked';

function Metric({ label, value, sub }: { readonly label: string; readonly value: React.ReactNode; readonly sub?: string }) {
  return (
    <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className="text-xl font-semibold text-text-primary mt-0.5">{value}</p>
      {sub && <p className="text-xs text-text-muted mt-0.5">{sub}</p>}
    </div>
  );
}

function attributionVariant(basis: string): 'success' | 'warning' | 'default' {
  if (basis === 'direct') return 'success';
  if (basis === 'temporal' || basis === 'probabilistic') return 'warning';
  return 'default';
}

function Breakdown({ title, counts }: { readonly title: string; readonly counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  if (entries.length === 0) return null;
  return (
    <div>
      <p className="text-xs text-text-secondary mb-1">{title}</p>
      <div className="flex flex-wrap gap-2">
        {entries.map(([key, count]) => (
          <Badge key={key} variant="default">{key}: {count}</Badge>
        ))}
      </div>
    </div>
  );
}

export function CardLinkedOutcomesTab({ campaignId }: { readonly campaignId: string }) {
  const outcomes = useCardLinkedCampaignOutcomes(campaignId);

  const notEnabled = !!outcomes.error && (
    outcomes.error.toLowerCase().includes('not found') || outcomes.error.includes('404')
  );

  if (outcomes.isLoading && !outcomes.data) return <LoadingState lines={5} />;
  if (notEnabled) {
    return (
      <EmptyState
        title="Card-linked campaign attribution is not enabled"
        description="Enable AETHER_CARD_LINKED_CAMPAIGN_ATTRIBUTION_ENABLED to attribute card-linked outcomes."
        icon="◌"
      />
    );
  }
  if (outcomes.error) {
    return <ErrorState title="Failed to load card-linked outcomes" message={outcomes.error} onRetry={outcomes.refetch} />;
  }
  const data = outcomes.data;
  if (!data || data.card_linked_flow_count === 0) {
    return (
      <EmptyState
        title="No card-linked outcomes observed for this campaign"
        description="Outcomes appear once card-linked flows carry this campaign's attribution."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm text-text-secondary">Attribution basis:</span>
        <Badge variant={attributionVariant(data.attribution_basis)}>{data.attribution_basis}</Badge>
        <span className="text-xs text-text-muted">
          Correlation-based labels are never causal claims.
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="Card top-up users" value={data.card_topup_users} sub="on-chain funding evidence" />
        <Metric label="Card spend users" value={data.card_spend_users} sub="provider feed evidence only" />
        <Metric label="Top-up volume (USD)" value={data.card_topup_volume_usd} sub="never counted as spend" />
        <Metric label="Spend volume (USD)" value={data.card_spend_volume_usd} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Metric label="Card-linked flows" value={data.card_linked_flow_count} />
        <Metric label="Active card wallets" value={data.active_card_wallets} />
        <Metric label="Programs observed" value={data.programs_observed.length ? data.programs_observed.join(', ') : 'none'} />
      </div>

      <Card>
        <CardHeader><CardTitle>Evidence breakdowns</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Breakdown title="By basis" counts={data.basis_breakdown} />
          <Breakdown title="By source" counts={data.source_breakdown} />
          <Breakdown title="By confidence" counts={data.confidence_breakdown} />
          {data.issuers_observed.length > 0 && (
            <p className="text-xs text-text-muted">Issuers: {data.issuers_observed.join(', ')}</p>
          )}
          {data.payment_networks_observed.length > 0 && (
            <p className="text-xs text-text-muted">Networks: {data.payment_networks_observed.join(', ')}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
