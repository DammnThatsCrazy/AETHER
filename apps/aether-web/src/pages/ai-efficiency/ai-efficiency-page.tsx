import { useState } from 'react';
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  formatCount,
  useTimeContext,
} from '@aether/ui';
import { aiInvocationStatuses } from '@aether/shared';
import {
  useAISummary,
  useAIInvocations,
  useAIWorkflows,
  useAIModels,
  useAIWasteFindings,
  useAIRecommendations,
} from '@aether-app/features/ai-efficiency';
import type {
  AIEfficiencyFindingRecord,
  AIEfficiencySummaryRecord,
  AIExecutionFactRecord,
  AIModelUsageRecord,
  AIWorkflowEconomicsRecord,
} from '@aether-app/features/ai-efficiency';
import {
  CostBasisNote,
  CostValue,
  DetectorBadge,
  FindingSeverityBadge,
  GOVERNED_PROPOSALS_COPY,
  InvocationStatusBadge,
  UNKNOWN_COST_COPY,
  formatCostAmount,
  formatDateTime,
  formatLatency,
  formatQuality,
  formatRate,
} from './ai-efficiency-shared';

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  ...aiInvocationStatuses.map(s => ({ value: s, label: s })),
];

const NOT_CONFIGURED_TITLE = 'AI outcome efficiency is not configured';
const NOT_CONFIGURED_DESCRIPTION =
  'This workspace does not have the AI outcome efficiency plane enabled. Contact your administrator or Aether support to enable it.';

const selectClass =
  'text-sm border border-border-default rounded-md px-3 py-1.5 bg-surface-default text-text-primary focus:outline-none focus:ring-1 focus:ring-accent';

interface SummaryStatProps {
  readonly label: string;
  readonly value: React.ReactNode;
}

function SummaryStat({ label, value }: SummaryStatProps) {
  return (
    <div className="flex items-center justify-between text-xs font-mono">
      <span className="text-text-muted">{label}</span>
      <span className="text-text-primary">{value}</span>
    </div>
  );
}

interface CurrencyCostCardProps {
  readonly currency: string;
  readonly summary: AIEfficiencySummaryRecord;
}

/** One card per currency — costs are never merged or converted across currencies. */
function CurrencyCostCard({ currency, summary }: CurrencyCostCardProps) {
  const total = summary.totals_by_currency?.[currency];
  const perInvocation = summary.cost_per_invocation_by_currency?.[currency];
  const failedCost = summary.failed_execution_cost_by_currency?.[currency];
  const retryWaste = summary.retry_waste_cost_by_currency?.[currency];

  return (
    <Card>
      <CardContent className="space-y-2">
        <div className="text-xs text-text-muted font-mono">Total AI cost — {currency}</div>
        <div className="text-2xl font-semibold text-text-primary font-mono">
          {total === null || total === undefined
            ? <Badge variant="warning" size="sm">unknown</Badge>
            : `${formatCostAmount(total)} ${currency}`}
        </div>
        <SummaryStat label="Cost / invocation" value={<CostValue value={perInvocation} currency={currency} />} />
        <SummaryStat label="Failed execution cost" value={<CostValue value={failedCost} currency={currency} />} />
        <SummaryStat label="Retry waste cost" value={<CostValue value={retryWaste} currency={currency} />} />
      </CardContent>
    </Card>
  );
}

interface RateCardProps {
  readonly label: string;
  readonly rate: number | null | undefined;
  readonly description: string;
}

function RateCard({ label, rate, description }: RateCardProps) {
  return (
    <Card>
      <CardContent className="space-y-1">
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="text-2xl font-semibold text-text-primary font-mono">{formatRate(rate)}</div>
        <p className="text-[10px] text-text-muted">{description}</p>
      </CardContent>
    </Card>
  );
}

interface OverviewCardsProps {
  readonly summary: AIEfficiencySummaryRecord;
}

function OverviewCards({ summary }: OverviewCardsProps) {
  const timeCtx = useTimeContext();
  const currencies = Object.keys(summary.totals_by_currency ?? {}).sort();

  return (
    <div className="space-y-3">
      <Card>
        <CardContent className="space-y-2">
          <div className="text-xs text-text-muted font-mono">Invocations observed</div>
          <div className="text-2xl font-semibold text-text-primary font-mono">
            {formatCount(summary.invocation_count ?? 0, timeCtx)}
          </div>
          <SummaryStat label="Completed workflows" value={formatCount(summary.completed_workflow_count ?? 0, timeCtx)} />
          <SummaryStat label="Human correction rate" value={formatRate(summary.human_correction_rate)} />
        </CardContent>
      </Card>

      {currencies.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {currencies.map(currency => (
            <CurrencyCostCard key={currency} currency={currency} summary={summary} />
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <RateCard
          label="Qualified outcome coverage"
          rate={summary.outcome_attribution_coverage}
          description="Share of AI spend attributable to a qualified business outcome."
        />
        <RateCard
          label="Cache utilization"
          rate={summary.cache_utilization_rate}
          description="Share of input tokens served from provider caches."
        />
        <RateCard
          label="Cost coverage"
          rate={summary.cost_coverage}
          description="Share of invocations with a known cost basis. Unknown costs stay unknown."
        />
      </div>
    </div>
  );
}

export function AIEfficiencyPage() {
  const timeCtx = useTimeContext();
  const [provider, setProvider] = useState('');
  const [status, setStatus] = useState('');

  const params: { provider?: string; status?: string } = {};
  if (provider) params.provider = provider;
  if (status) params.status = status;

  const summary = useAISummary();
  const { invocations, notConfigured, loading, error, refresh } = useAIInvocations(params);
  const workflows = useAIWorkflows();
  const models = useAIModels();
  const waste = useAIWasteFindings();
  const recommendations = useAIRecommendations();

  const providerOptions = [
    { value: '', label: 'All providers' },
    ...[...new Set(models.models.map(m => m.provider))].sort().map(p => ({ value: p, label: p })),
  ];

  const workflowColumns = [
    {
      key: 'workflow_run_id',
      header: 'Workflow',
      render: (row: AIWorkflowEconomicsRecord) => (
        <span className="font-mono text-xs text-text-primary">{row.workflow_run_id}</span>
      ),
    },
    {
      key: 'invocations',
      header: 'Invocations',
      render: (row: AIWorkflowEconomicsRecord) => (
        <span className="font-mono">{formatCount(row.total_invocations, timeCtx)}</span>
      ),
    },
    {
      key: 'success',
      header: 'Success',
      render: (row: AIWorkflowEconomicsRecord) => (
        <div className="font-mono text-xs">
          <span className="text-success">{formatCount(row.successful_invocations ?? 0, timeCtx)}</span>
          <span className="text-text-muted"> / </span>
          <span className="text-danger">{formatCount(row.failed_invocations ?? 0, timeCtx)} failed</span>
        </div>
      ),
    },
    {
      key: 'retries',
      header: 'Retries',
      render: (row: AIWorkflowEconomicsRecord) => (
        <span className="font-mono">{formatCount(row.total_retries ?? 0, timeCtx)}</span>
      ),
    },
    {
      key: 'fully_loaded_cost',
      header: 'Fully loaded cost',
      render: (row: AIWorkflowEconomicsRecord) => (
        <div className="space-y-0.5">
          <CostValue value={row.fully_loaded_cost} currency={row.currency} />
          <div className="text-[10px] text-text-muted font-mono">coverage {formatRate(row.cost_coverage)}</div>
        </div>
      ),
    },
    {
      key: 'quality',
      header: 'Quality',
      render: (row: AIWorkflowEconomicsRecord) => (
        <span className="font-mono">{formatQuality(row.quality_score)}</span>
      ),
    },
    {
      key: 'technical_success',
      header: 'Technical success',
      render: (row: AIWorkflowEconomicsRecord) => (
        <Badge variant={row.technical_success ? 'success' : 'danger'}>
          {row.technical_success ? 'yes' : 'no'}
        </Badge>
      ),
    },
  ];

  const modelColumns = [
    {
      key: 'model',
      header: 'Provider / model',
      render: (row: AIModelUsageRecord) => (
        <div>
          <div className="text-text-primary font-mono">{row.model}</div>
          <div className="text-[10px] text-text-muted font-mono">{row.provider}</div>
        </div>
      ),
    },
    {
      key: 'invocations',
      header: 'Invocations',
      render: (row: AIModelUsageRecord) => (
        <span className="font-mono">{formatCount(row.invocations, timeCtx)}</span>
      ),
    },
    {
      key: 'cost',
      header: 'Cost',
      render: (row: AIModelUsageRecord) => {
        const entries = Object.entries(row.cost_by_currency ?? {}).sort(([a], [b]) => a.localeCompare(b));
        if (entries.length === 0) return <Badge variant="warning" size="sm">unknown</Badge>;
        return (
          <div className="space-y-0.5">
            {entries.map(([currency, amount]) => (
              <div key={currency}><CostValue value={amount} currency={currency} /></div>
            ))}
          </div>
        );
      },
    },
    {
      key: 'latency',
      header: 'Avg latency',
      render: (row: AIModelUsageRecord) => (
        <span className="font-mono text-text-muted">{formatLatency(row.avg_latency_ms, timeCtx)}</span>
      ),
    },
    {
      key: 'success_rate',
      header: 'Success rate',
      render: (row: AIModelUsageRecord) => (
        <span className="font-mono">{formatRate(row.success_rate)}</span>
      ),
    },
    {
      key: 'avg_quality',
      header: 'Avg quality',
      render: (row: AIModelUsageRecord) => (
        <span className="font-mono">{formatQuality(row.avg_quality)}</span>
      ),
    },
  ];

  const invocationColumns = [
    {
      key: 'invocation',
      header: 'Invocation',
      render: (row: AIExecutionFactRecord) => (
        <div>
          <div className="font-mono text-xs text-text-primary">{row.invocation_id}</div>
          <div className="text-[10px] text-text-muted font-mono">{row.task_type}</div>
        </div>
      ),
    },
    {
      key: 'model',
      header: 'Model',
      render: (row: AIExecutionFactRecord) => (
        <div>
          <div className="font-mono text-xs text-text-primary">{row.model}</div>
          <div className="text-[10px] text-text-muted font-mono">{row.provider}</div>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row: AIExecutionFactRecord) => (
        <div className="space-y-0.5">
          <InvocationStatusBadge status={row.status} />
          {row.error_code && (
            <div className="text-[10px] text-danger font-mono">{row.error_code}</div>
          )}
        </div>
      ),
    },
    {
      key: 'cost',
      header: 'Cost',
      render: (row: AIExecutionFactRecord) => (
        <div className="space-y-0.5">
          <CostValue value={row.selected_cost} currency={row.currency} />
          <div><CostBasisNote basis={row.cost_basis} /></div>
        </div>
      ),
    },
    {
      key: 'latency',
      header: 'Latency',
      render: (row: AIExecutionFactRecord) => (
        <div className="font-mono text-xs">
          <div className="text-text-muted">{formatLatency(row.latency_ms, timeCtx)}</div>
          {(row.retry_count ?? 0) > 0 && (
            <div className="text-[10px] text-warning">{row.retry_count} retries</div>
          )}
        </div>
      ),
    },
    {
      key: 'observed_at',
      header: 'Observed',
      render: (row: AIExecutionFactRecord) => (
        <span className="text-xs text-text-muted">{formatDateTime(row.observed_at, timeCtx)}</span>
      ),
    },
  ];

  const renderFinding = (finding: AIEfficiencyFindingRecord, index: number) => (
    <div
      key={`${finding.detector}:${index}`}
      className="border border-border-default rounded-md px-3 py-2.5 space-y-1.5"
    >
      <div className="flex items-center gap-2 flex-wrap">
        <FindingSeverityBadge severity={finding.severity} />
        <DetectorBadge detector={finding.detector} />
        <span className="text-sm font-medium text-text-primary">{finding.title}</span>
      </div>
      {finding.description && (
        <p className="text-xs text-text-secondary">{finding.description}</p>
      )}
      <div className="flex items-center gap-4 flex-wrap text-xs font-mono text-text-muted">
        <span>{(finding.evidence_refs ?? []).length} evidence refs</span>
        <span className="flex items-center gap-1.5">
          Est. monthly waste:
          <CostValue value={finding.estimated_monthly_waste} currency={finding.currency} />
        </span>
        {finding.candidate_action && (
          <span className="text-text-secondary">→ {finding.candidate_action}</span>
        )}
      </div>
    </div>
  );

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">AI Efficiency</h1>
        <p className="text-sm text-text-secondary mt-0.5">
          AI invocation costs, workflow economics, and governed efficiency proposals. {UNKNOWN_COST_COPY}
        </p>
      </div>

      {/* Overview cards */}
      {summary.loading && !summary.summary && !summary.error && !summary.notConfigured ? (
        <LoadingState lines={4} />
      ) : summary.error ? (
        <ErrorState title="Failed to load AI cost summary" message={summary.error} onRetry={summary.refresh} />
      ) : summary.notConfigured ? (
        <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />
      ) : !summary.summary ? (
        <EmptyState
          title="No AI cost summary yet"
          description="Summary metrics appear here once AI invocations are observed."
        />
      ) : (
        <OverviewCards summary={summary.summary} />
      )}

      {/* Workflow economics */}
      <Card>
        <CardHeader>
          <CardTitle>Workflow economics</CardTitle>
        </CardHeader>
        <CardContent>
          {workflows.loading && workflows.workflows.length === 0 && !workflows.error && !workflows.notConfigured ? (
            <LoadingState lines={4} />
          ) : workflows.error ? (
            <ErrorState title="Failed to load workflow economics" message={workflows.error} onRetry={workflows.refresh} />
          ) : workflows.notConfigured ? (
            <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />
          ) : workflows.workflows.length === 0 ? (
            <EmptyState
              title="No workflow economics yet"
              description="Workflows appear here once invocations carrying a workflow_run_id are observed. Workflow IDs are never fabricated."
            />
          ) : (
            <DataTable
              columns={workflowColumns}
              data={workflows.workflows}
              keyExtractor={row => row.workflow_run_id}
            />
          )}
        </CardContent>
      </Card>

      {/* Model comparison */}
      <Card>
        <CardHeader>
          <CardTitle>Model comparison</CardTitle>
        </CardHeader>
        <CardContent>
          {models.loading && models.models.length === 0 && !models.error && !models.notConfigured ? (
            <LoadingState lines={4} />
          ) : models.error ? (
            <ErrorState title="Failed to load model comparison" message={models.error} onRetry={models.refresh} />
          ) : models.notConfigured ? (
            <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />
          ) : models.models.length === 0 ? (
            <EmptyState
              title="No model usage yet"
              description="Model comparisons appear here once AI invocations are observed."
            />
          ) : (
            <DataTable
              columns={modelColumns}
              data={models.models}
              keyExtractor={row => `${row.provider}:${row.model}`}
            />
          )}
        </CardContent>
      </Card>

      {/* Waste analysis */}
      <Card>
        <CardHeader>
          <CardTitle>Waste analysis</CardTitle>
        </CardHeader>
        <CardContent>
          {waste.loading && waste.findings.length === 0 && !waste.error && !waste.notConfigured ? (
            <LoadingState lines={4} />
          ) : waste.error ? (
            <ErrorState title="Failed to load waste findings" message={waste.error} onRetry={waste.refresh} />
          ) : waste.notConfigured ? (
            <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />
          ) : waste.findings.length === 0 ? (
            <EmptyState
              title="No waste findings"
              description="Deterministic detectors have not flagged any AI spend waste."
            />
          ) : (
            <div className="space-y-2">
              {waste.findings.map(renderFinding)}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recommendations */}
      <Card>
        <CardHeader>
          <CardTitle>Recommendations</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-text-muted font-mono">{GOVERNED_PROPOSALS_COPY}</p>
          {recommendations.loading && recommendations.recommendations.length === 0 && !recommendations.error && !recommendations.notConfigured ? (
            <LoadingState lines={3} />
          ) : recommendations.error ? (
            <ErrorState
              title="Failed to load recommendations"
              message={recommendations.error}
              onRetry={recommendations.refresh}
            />
          ) : recommendations.notConfigured ? (
            <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />
          ) : recommendations.recommendations.length === 0 ? (
            <EmptyState
              title="No recommendations"
              description="Governed efficiency proposals appear here once detectors produce candidate actions."
            />
          ) : (
            <div className="space-y-2">
              {recommendations.recommendations.map(renderFinding)}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Invocations */}
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <select
            value={provider}
            onChange={e => setProvider(e.target.value)}
            className={selectClass}
            aria-label="Filter by provider"
          >
            {providerOptions.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          <select
            value={status}
            onChange={e => setStatus(e.target.value)}
            className={selectClass}
            aria-label="Filter by status"
          >
            {STATUS_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {loading && invocations.length === 0 ? (
          <LoadingState lines={6} />
        ) : error ? (
          <ErrorState title="Failed to load AI invocations" message={error} onRetry={refresh} />
        ) : notConfigured ? (
          <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />
        ) : invocations.length === 0 ? (
          <EmptyState
            title="No AI invocations observed yet"
            description="Invocations appear here once ai_invocation_observed events are ingested. Records never carry raw prompt or completion content."
          />
        ) : (
          <DataTable
            columns={invocationColumns}
            data={invocations}
            keyExtractor={row => row.invocation_id}
          />
        )}
      </div>
    </div>
  );
}
