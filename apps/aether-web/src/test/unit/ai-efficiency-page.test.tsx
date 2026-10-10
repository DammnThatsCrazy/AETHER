import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';
import { AIEfficiencyPage } from '@aether-app/pages/ai-efficiency';

// The shared queryCache tracks in-flight fetches with `promise.finally(...)`,
// which leaks an unhandled rejection when a fetcher rejects even though the
// UI handles the error (useQuery sets its error state). Patch it test-locally
// so the error-state tests do not trip vitest's unhandled-error detector.
beforeAll(() => {
  const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

/** Badge text can collide with filter <option> text; scope to badge elements. */
function getBadge(text: string): HTMLElement {
  const match = screen.getAllByText(text).find(el => el.classList.contains('ui-badge'));
  expect(match).toBeDefined();
  return match as HTMLElement;
}

function getBadges(text: string): HTMLElement[] {
  return screen.getAllByText(text).filter(el => el.classList.contains('ui-badge'));
}

const mocks = vi.hoisted(() => ({
  fetchAISummary: vi.fn(),
  fetchAIInvocations: vi.fn(),
  fetchAIWorkflows: vi.fn(),
  fetchAIModels: vi.fn(),
  fetchAIWasteFindings: vi.fn(),
  fetchAIRecommendations: vi.fn(),
}));

vi.mock('@aether-app/features/ai-efficiency/api', () => mocks);

// Two currencies (USD + EUR) — totals per currency are never merged.
const SUMMARY_FIXTURE = {
  totals_by_currency: { USD: 1240.5, EUR: 96.4 },
  invocation_count: 18234,
  completed_workflow_count: 512,
  cost_per_invocation_by_currency: { USD: 0.0681, EUR: 0.0129 },
  failed_execution_cost_by_currency: { USD: 84.2, EUR: 1.8 },
  retry_waste_cost_by_currency: { USD: 41.7, EUR: 0.6 },
  cache_utilization_rate: 0.34,
  human_correction_rate: 0.06,
  outcome_attribution_coverage: 0.72,
  cost_coverage: 0.91,
};

const INVOCATION_FIXTURES = [
  {
    invocation_id: 'inv_openai_support_001',
    tenant_id: 'tenant_demo_001',
    observed_at: '2026-07-08T14:05:00.000Z',
    workflow_run_id: 'wf_support_2026_07_08_001',
    task_type: 'support_reply',
    provider: 'openai',
    model: 'gpt-4o-mini',
    status: 'succeeded',
    latency_ms: 1240,
    retry_count: 0,
    selected_cost: 0.0042,
    cost_basis: 'billed',
    currency: 'USD',
    quality_score: 0.92,
  },
  {
    invocation_id: 'inv_mistral_embed_003',
    tenant_id: 'tenant_demo_001',
    observed_at: '2026-07-08T09:30:00.000Z',
    workflow_run_id: 'wf_catalog_eur_2026_07_08_001',
    task_type: 'embedding',
    provider: 'mistral',
    model: 'mistral-embed',
    status: 'succeeded',
    latency_ms: 320,
    retry_count: 0,
    selected_cost: 0.0009,
    cost_basis: 'provider_reported',
    currency: 'EUR',
    quality_score: null,
  },
  // Unknown cost: selected_cost null + cost_basis 'unknown' — must render as
  // an "unknown" badge, never as 0.
  {
    invocation_id: 'inv_openai_unknown_004',
    tenant_id: 'tenant_demo_001',
    observed_at: '2026-07-07T22:15:00.000Z',
    workflow_run_id: 'wf_support_2026_07_07_002',
    task_type: 'support_reply',
    provider: 'openai',
    model: 'gpt-4o',
    status: 'failed',
    error_code: 'provider_timeout',
    latency_ms: 30000,
    retry_count: 2,
    selected_cost: null,
    cost_basis: 'unknown',
    currency: 'USD',
    quality_score: null,
  },
];

const WORKFLOW_FIXTURES = [
  {
    tenant_id: 'tenant_demo_001',
    workflow_run_id: 'wf_support_2026_07_08_001',
    total_invocations: 4,
    successful_invocations: 4,
    failed_invocations: 0,
    total_retries: 0,
    total_latency_ms: 5210,
    fully_loaded_cost: 0.34,
    currency: 'USD',
    cost_coverage: 1,
    quality_score: 0.9,
    human_reviewed: true,
    human_corrected: false,
    technical_success: true,
    qualified_outcome_count: 1,
    first_observed_at: '2026-07-08T14:05:00.000Z',
    last_observed_at: '2026-07-08T14:06:40.000Z',
  },
  {
    tenant_id: 'tenant_demo_001',
    workflow_run_id: 'wf_support_2026_07_07_002',
    total_invocations: 3,
    successful_invocations: 1,
    failed_invocations: 2,
    total_retries: 4,
    total_latency_ms: 64100,
    fully_loaded_cost: null,
    currency: 'USD',
    cost_coverage: 0.33,
    quality_score: null,
    human_reviewed: false,
    human_corrected: true,
    technical_success: false,
    qualified_outcome_count: 0,
    first_observed_at: '2026-07-07T22:15:00.000Z',
    last_observed_at: '2026-07-07T22:18:10.000Z',
  },
  {
    tenant_id: 'tenant_demo_001',
    workflow_run_id: 'wf_catalog_eur_2026_07_08_001',
    total_invocations: 12,
    successful_invocations: 12,
    failed_invocations: 0,
    total_retries: 1,
    total_latency_ms: 4020,
    fully_loaded_cost: 12.4,
    currency: 'EUR',
    cost_coverage: 1,
    quality_score: 0.81,
    human_reviewed: false,
    human_corrected: false,
    technical_success: true,
    qualified_outcome_count: 2,
    first_observed_at: '2026-07-08T09:30:00.000Z',
    last_observed_at: '2026-07-08T09:34:20.000Z',
  },
];

const MODEL_FIXTURES = [
  { provider: 'openai', model: 'gpt-4o-mini', invocations: 11204, cost_by_currency: { USD: 401.2 }, avg_latency_ms: 1180, success_rate: 0.991, avg_quality: 0.9 },
  { provider: 'anthropic', model: 'claude-sonnet-4', invocations: 4820, cost_by_currency: { USD: 812.6 }, avg_latency_ms: 2240, success_rate: 0.987, avg_quality: 0.93 },
  { provider: 'mistral', model: 'mistral-embed', invocations: 2210, cost_by_currency: { EUR: 96.4 }, avg_latency_ms: 310, success_rate: 0.999, avg_quality: null },
];

// One finding per deterministic detector family.
const WASTE_FIXTURES = [
  {
    detector: 'retry_waste',
    severity: 'high',
    title: 'Retry storms on gpt-4o support replies',
    description: 'Timeout-driven retries re-run full prompts without backoff.',
    evidence_refs: ['inv_openai_unknown_004', 'wf_support_2026_07_07_002', 'trace_support_8622'],
    estimated_monthly_waste: 41.7,
    currency: 'USD',
    candidate_action: 'Add exponential backoff and cap retries at 1.',
  },
  {
    detector: 'model_overqualification',
    severity: 'medium',
    title: 'gpt-4o used for template filling',
    evidence_refs: ['inv_openai_support_001'],
    estimated_monthly_waste: 118.2,
    currency: 'USD',
    candidate_action: 'Route template tasks to gpt-4o-mini.',
  },
  {
    detector: 'deterministic_replacement_candidate',
    severity: 'medium',
    title: 'Currency formatting handled by LLM',
    evidence_refs: ['wf_support_2026_07_08_001'],
    estimated_monthly_waste: 22.5,
    currency: 'USD',
    candidate_action: 'Replace with a deterministic function.',
  },
  {
    detector: 'cache_opportunity',
    severity: 'low',
    title: 'Repeated identical catalog embedding prompts',
    evidence_refs: ['inv_mistral_embed_003', 'wf_catalog_eur_2026_07_08_001'],
    estimated_monthly_waste: 9.6,
    currency: 'EUR',
    candidate_action: 'Cache embeddings keyed by content hash.',
  },
  {
    detector: 'failed_workflow_concentration',
    severity: 'high',
    title: 'Failed-execution cost concentrated in one workflow',
    evidence_refs: ['wf_support_2026_07_07_002'],
    estimated_monthly_waste: null,
    currency: 'USD',
    candidate_action: 'Investigate provider timeouts before rerouting.',
  },
];

const RECOMMENDATION_FIXTURES = [
  {
    detector: 'model_overqualification',
    severity: 'medium',
    title: 'Route support_reply template tasks to gpt-4o-mini',
    description: 'Quality parity observed; projected 29% cost reduction.',
    evidence_refs: ['inv_openai_support_001'],
    estimated_monthly_waste: 118.2,
    currency: 'USD',
    candidate_action: 'Propose default model gpt-4o-mini for task_type support_reply.',
  },
];

function renderPage() {
  return render(<AIEfficiencyPage />);
}

beforeEach(() => {
  vi.clearAllMocks();
  queryCache.invalidatePrefix('ai-efficiency');
  mocks.fetchAISummary.mockResolvedValue({ summary: SUMMARY_FIXTURE, notConfigured: false });
  mocks.fetchAIInvocations.mockResolvedValue({ invocations: INVOCATION_FIXTURES, notConfigured: false });
  mocks.fetchAIWorkflows.mockResolvedValue({ workflows: WORKFLOW_FIXTURES, notConfigured: false });
  mocks.fetchAIModels.mockResolvedValue({ models: MODEL_FIXTURES, notConfigured: false });
  mocks.fetchAIWasteFindings.mockResolvedValue({ findings: WASTE_FIXTURES, notConfigured: false });
  mocks.fetchAIRecommendations.mockResolvedValue({ recommendations: RECOMMENDATION_FIXTURES, notConfigured: false });
});

describe('Aether AI Efficiency page', () => {
  it('renders per-currency overview cards, workflow economics, model comparison, waste findings, and recommendations', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Total AI cost — USD')).toBeInTheDocument());

    // One overview card per currency — totals stay in their own currency and
    // are never merged, converted, or summed.
    expect(screen.getByText('1240.50 USD')).toBeInTheDocument();
    expect(screen.getByText('Total AI cost — EUR')).toBeInTheDocument();
    expect(screen.getAllByText('96.40 EUR').length).toBeGreaterThan(0);
    expect(screen.queryByText(/1336\.9/)).toBeNull();
    expect(screen.getByText('0.0681 USD')).toBeInTheDocument();

    // Coverage / utilization cards.
    expect(screen.getByText('Qualified outcome coverage')).toBeInTheDocument();
    expect(screen.getByText('72.0%')).toBeInTheDocument();
    expect(screen.getByText('Cache utilization')).toBeInTheDocument();
    expect(screen.getByText('34.0%')).toBeInTheDocument();
    expect(screen.getByText('Cost coverage')).toBeInTheDocument();
    expect(screen.getByText('91.0%')).toBeInTheDocument();

    // Workflow economics table — fully loaded cost keeps its currency.
    expect(screen.getByText('Workflow economics')).toBeInTheDocument();
    expect(screen.getByText('wf_support_2026_07_08_001')).toBeInTheDocument();
    expect(screen.getByText('0.34 USD')).toBeInTheDocument();
    expect(screen.getByText('12.40 EUR')).toBeInTheDocument();
    expect(getBadge('yes')).toBeInTheDocument();
    expect(getBadge('no')).toBeInTheDocument();

    // Model comparison table.
    expect(screen.getByText('Model comparison')).toBeInTheDocument();
    expect(screen.getAllByText('gpt-4o-mini').length).toBeGreaterThan(0);
    expect(screen.getByText('claude-sonnet-4')).toBeInTheDocument();
    expect(screen.getByText('812.60 USD')).toBeInTheDocument();

    // Waste analysis — one finding per detector family, with severity badges,
    // evidence counts, and estimated monthly waste.
    expect(screen.getByText('Waste analysis')).toBeInTheDocument();
    for (const label of [
      'Retry waste',
      'Model overqualification',
      'Deterministic replacement',
      'Cache opportunity',
      'Failed workflow concentration',
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(getBadges('high').length).toBeGreaterThanOrEqual(2);
    expect(getBadge('low')).toBeInTheDocument();
    expect(screen.getByText('3 evidence refs')).toBeInTheDocument();
    expect(screen.getAllByText('41.70 USD').length).toBeGreaterThan(0);

    // Recommendations are governed proposals only.
    expect(screen.getByText('Recommendations')).toBeInTheDocument();
    expect(
      screen.getByText('Proposals only — Aether never changes models, prompts, or routing automatically.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Route support_reply template tasks to gpt-4o-mini')).toBeInTheDocument();
  });

  it('renders unknown costs as an unknown badge — never as zero', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('inv_openai_unknown_004')).toBeInTheDocument());
    // Unknown-cost invocation, unknown-cost workflow, and unknown-waste finding
    // each render the badge.
    expect(getBadges('unknown').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText('basis: unknown')).toBeInTheDocument();
    // A null cost must never surface as a zero amount.
    expect(screen.queryByText('0.00 USD')).toBeNull();
    expect(screen.queryByText('0 USD')).toBeNull();
  });

  it('filters invocations by provider', async () => {
    renderPage();
    await waitFor(() => expect(mocks.fetchAIInvocations).toHaveBeenCalledWith({}));
    await waitFor(() => expect(screen.getByText('claude-sonnet-4')).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText('Filter by provider'), 'anthropic');
    await waitFor(() => expect(mocks.fetchAIInvocations).toHaveBeenCalledWith({ provider: 'anthropic' }));
  });

  it('filters invocations by status', async () => {
    renderPage();
    await waitFor(() => expect(mocks.fetchAIInvocations).toHaveBeenCalledWith({}));
    await userEvent.selectOptions(screen.getByLabelText('Filter by status'), 'failed');
    await waitFor(() => expect(mocks.fetchAIInvocations).toHaveBeenCalledWith({ status: 'failed' }));
  });

  it('shows the empty state when there are no invocations', async () => {
    mocks.fetchAIInvocations.mockResolvedValue({ invocations: [], notConfigured: false });
    renderPage();
    await waitFor(() => expect(screen.getByText('No AI invocations observed yet')).toBeInTheDocument());
  });

  it('shows the not-configured state when the AI efficiency plane is not enabled', async () => {
    mocks.fetchAISummary.mockResolvedValue({ summary: null, notConfigured: true });
    mocks.fetchAIInvocations.mockResolvedValue({ invocations: [], notConfigured: true });
    mocks.fetchAIWorkflows.mockResolvedValue({ workflows: [], notConfigured: true });
    mocks.fetchAIModels.mockResolvedValue({ models: [], notConfigured: true });
    mocks.fetchAIWasteFindings.mockResolvedValue({ findings: [], notConfigured: true });
    mocks.fetchAIRecommendations.mockResolvedValue({ recommendations: [], notConfigured: true });
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByText('AI outcome efficiency is not configured').length).toBeGreaterThan(0),
    );
  });

  it('shows the error state when the invocations request fails', async () => {
    mocks.fetchAIInvocations.mockRejectedValue(new Error('boom'));
    renderPage();
    await waitFor(() => expect(screen.getByText('Failed to load AI invocations')).toBeInTheDocument());
    expect(screen.getByText('boom')).toBeInTheDocument();
  });
});
