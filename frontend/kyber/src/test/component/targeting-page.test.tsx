import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TargetingIntelligencePage } from '@kyber/pages/targeting';
import { SuggestionCard } from '@kyber/features/suggestions/components/SuggestionCard';

const mocks = vi.hoisted(() => ({
  isFeatureEnabled: vi.fn(() => true),
  targetingHealth: vi.fn(),
  targetingLeakageQueue: vi.fn(),
  targetingMappingQuality: vi.fn(),
  targetingRecompute: vi.fn(),
  targetingReleaseReadiness: vi.fn(),
  targetingAudit: vi.fn(),
}));

vi.mock('@kyber/lib/featureFlags', () => ({
  isFeatureEnabled: mocks.isFeatureEnabled,
  featureFlags: {},
}));

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    targetingHealth: mocks.targetingHealth,
    targetingLeakageQueue: mocks.targetingLeakageQueue,
    targetingMappingQuality: mocks.targetingMappingQuality,
    targetingRecompute: mocks.targetingRecompute,
    targetingReleaseReadiness: mocks.targetingReleaseReadiness,
    targetingAudit: mocks.targetingAudit,
  } } },
}));

const HEALTH_FIXTURE = {
  tenantsObserved: 2,
  intentCount: 3,
  snapshotCount: 5,
  leakageBySeverity: { critical: 1, high: 2, medium: 1 },
  intentsBySource: { tenant_declared: 2, suggestion_generated: 1 },
};

const LEAKAGE_QUEUE_FIXTURE = {
  queue: [
    {
      findingId: 'ti_leak_001',
      tenantId: 'tenant_001',
      campaignId: 'camp_spring_launch_001',
      clusterId: 'cluster_z',
      severity: 'critical',
      leakageRate: 0.21,
      reasonCode: 'fraud_risk',
      likelyCauses: ['provider_ignored_exclusion', 'lookalike_expansion'],
      computedAt: '2026-07-08T12:00:00.000Z',
    },
    {
      findingId: 'ti_leak_002',
      tenantId: 'tenant_002',
      campaignId: 'camp_renewal_005',
      clusterId: 'cluster_t',
      severity: 'high',
      leakageRate: 0.09,
      reasonCode: 'consent_blocked',
      likelyCauses: ['identity_resolved_after_launch'],
      computedAt: '2026-07-07T09:00:00.000Z',
    },
  ],
};

const MAPPING_QUALITY_FIXTURE = {
  diagnostics: [
    {
      tenantId: 'tenant_002',
      campaignId: 'camp_renewal_005',
      provider: 'google_ads',
      qualityScore: 0.34,
      blocksSuggestions: true,
      providerSyncFreshness: 'stale',
      reasons: ['unresolved provider aliases above threshold'],
      computedAt: '2026-07-07T09:00:00.000Z',
    },
    {
      tenantId: 'tenant_001',
      campaignId: 'camp_spring_launch_001',
      provider: 'meta_ads',
      qualityScore: 0.87,
      blocksSuggestions: false,
      providerSyncFreshness: 'recent',
      reasons: [],
      computedAt: '2026-07-08T12:00:00.000Z',
    },
  ],
};

const READINESS_FIXTURE = {
  ready: false,
  checks: [
    { name: 'contracts_importable', passed: true, detail: '' },
    { name: 'stores_reachable', passed: false, detail: 'targeting_audit store unreachable' },
  ],
  flags: { enabled: true, exports_enabled: true, ooda_suggestions_enabled: false, kyber_enabled: true },
};

const AUDIT_FIXTURE = {
  audit: [
    {
      id: 'aud_ti_001',
      tenantId: 'tenant_001',
      action: 'snapshot_recomputed',
      actor: 'kyber-operator',
      detail: {},
      occurredAt: '2026-07-09T10:00:00.000Z',
    },
  ],
};

const TARGETING_SUGGESTION_FIXTURE = {
  suggestion_id: 'sugg_targeting_001',
  title: 'Exclusion leakage observed in cluster cluster_z',
  summary: 'Cluster cluster_z was excluded but reach was observed.',
  status: 'review_required',
  priority: 'P1',
  suggestion_class: 'retargeting',
  confidence_score: 0.72,
  targeting: {
    includeClusterIds: ['cluster_a', 'cluster_b'],
    excludeClusterIds: ['cluster_z'],
    holdoutClusterIds: ['cluster_h'],
    evidenceChain: {
      targetingIntentId: 'ti_intent_001',
      eligibilitySnapshotId: 'ti_snap_001',
      observationId: 'ti_obs_001',
    },
  },
  evidence: [{ id: 'ev_leak_001', type: 'annotation', source: 'exclusion_leakage_finding' }],
};

function renderPage() {
  return render(<MemoryRouter><TargetingIntelligencePage /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.isFeatureEnabled.mockReturnValue(true);
  mocks.targetingHealth.mockResolvedValue(HEALTH_FIXTURE);
  mocks.targetingLeakageQueue.mockResolvedValue(LEAKAGE_QUEUE_FIXTURE);
  mocks.targetingMappingQuality.mockResolvedValue(MAPPING_QUALITY_FIXTURE);
  mocks.targetingRecompute.mockResolvedValue({ recomputed: 'snapshot', snapshot: {} });
  mocks.targetingReleaseReadiness.mockResolvedValue(READINESS_FIXTURE);
  mocks.targetingAudit.mockResolvedValue(AUDIT_FIXTURE);
});

describe('Kyber Targeting Intelligence page', () => {
  it('shows loading while the fleet request is pending', () => {
    mocks.targetingHealth.mockReturnValue(new Promise(() => undefined));
    const { container } = render(<MemoryRouter><TargetingIntelligencePage /></MemoryRouter>);
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('renders fleet health, the leakage queue, mapping quality, release readiness, and the audit trail', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Targeting Intelligence')).toBeInTheDocument());

    // Fleet health.
    expect(screen.getByText('Tenants observed')).toBeInTheDocument();
    expect(screen.getByText('Targeting intents')).toBeInTheDocument();
    expect(screen.getByText('Eligibility snapshots')).toBeInTheDocument();
    expect(screen.getByText('critical: 1')).toBeInTheDocument();
    expect(screen.getByText('high: 2')).toBeInTheDocument();
    expect(screen.getByText('tenant declared')).toBeInTheDocument();

    // Leakage queue table: tenant, campaign, cluster, severity, rate, age.
    expect(screen.getByText('Exclusion leakage queue')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText('tenant_001').length).toBeGreaterThan(0));
    expect(screen.getAllByText('camp_spring_launch_001').length).toBeGreaterThan(0);
    expect(screen.getByText('cluster_z')).toBeInTheDocument();
    // 'critical' also appears as a filter <option>; scope to the row badge.
    expect(screen.getAllByText('critical').some(el => el.classList.contains('ui-badge'))).toBe(true);
    expect(screen.getByText('21.0%')).toBeInTheDocument();

    // Mapping quality diagnostics table.
    expect(screen.getByText('Provider mapping quality')).toBeInTheDocument();
    expect(screen.getByText('google_ads')).toBeInTheDocument();
    expect(screen.getByText('34.0%')).toBeInTheDocument();
    expect(screen.getByText('blocked')).toBeInTheDocument();
    expect(screen.getByText('allowed')).toBeInTheDocument();

    // Release readiness panel.
    expect(screen.getByText('Release readiness')).toBeInTheDocument();
    expect(screen.getByText('not ready')).toBeInTheDocument();
    expect(screen.getByText('contracts importable')).toBeInTheDocument();
    expect(screen.getByText('targeting_audit store unreachable')).toBeInTheDocument();

    // Audit trail feed.
    expect(screen.getByText('Audit trail')).toBeInTheDocument();
    expect(screen.getByText('snapshot recomputed')).toBeInTheDocument();
    expect(screen.getByText('by kyber-operator')).toBeInTheDocument();

    // Non-execution boundary copy.
    expect(
      screen.getByText(/it never executes campaigns and never mutates external campaign platforms/),
    ).toBeInTheDocument();
  });

  it('opens the leakage detail drawer when a queue row is clicked', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('cluster_z')).toBeInTheDocument());
    await userEvent.click(screen.getByText('cluster_z'));
    await waitFor(() => expect(screen.getByText('Leakage finding detail')).toBeInTheDocument());
    expect(screen.getByText('ti_leak_001')).toBeInTheDocument();
    expect(screen.getByText('provider ignored exclusion')).toBeInTheDocument();
    expect(screen.getByText('lookalike expansion')).toBeInTheDocument();
    expect(screen.getByText(/remediation happens in the tenant's external campaign platform/)).toBeInTheDocument();
  });

  it('filters the leakage queue by severity', async () => {
    renderPage();
    await waitFor(() => expect(mocks.targetingLeakageQueue).toHaveBeenCalledWith(undefined));
    await userEvent.selectOptions(screen.getByLabelText('Filter leakage by severity'), 'critical');
    await waitFor(() => expect(mocks.targetingLeakageQueue).toHaveBeenCalledWith('critical'));
  });

  it('runs a snapshot recompute after confirmation and shows the success state', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Recompute controls')).toBeInTheDocument());

    await userEvent.type(screen.getByLabelText('Recompute tenant ID'), 'tenant_001');
    await userEvent.type(screen.getByLabelText('Recompute intent ID'), 'ti_intent_001');
    await userEvent.type(screen.getByLabelText('Recompute as-of timestamp'), '2026-07-02T00:00:00Z');

    // Two-step confirmation: recompute is armed, then confirmed.
    await userEvent.click(screen.getByRole('button', { name: 'Recompute…' }));
    expect(mocks.targetingRecompute).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Confirm recompute' }));

    await waitFor(() =>
      expect(mocks.targetingRecompute).toHaveBeenCalledWith({
        tenantId: 'tenant_001',
        intentId: 'ti_intent_001',
        asOf: '2026-07-02T00:00:00Z',
      }),
    );
    await waitFor(() => expect(screen.getByText('Recompute complete: snapshot')).toBeInTheDocument());
  });

  it('shows the recompute error state when the request fails', async () => {
    mocks.targetingRecompute.mockRejectedValue(new Error('operator permission required'));
    renderPage();
    await waitFor(() => expect(screen.getByText('Recompute controls')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('tab', { name: 'Leakage re-evaluation' }));
    await userEvent.type(screen.getByLabelText('Recompute tenant ID'), 'tenant_002');
    await userEvent.type(screen.getByLabelText('Recompute observation ID'), 'ti_obs_005');
    await userEvent.click(screen.getByRole('button', { name: 'Recompute…' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm recompute' }));

    await waitFor(() =>
      expect(mocks.targetingRecompute).toHaveBeenCalledWith({ tenantId: 'tenant_002', observationId: 'ti_obs_005' }),
    );
    await waitFor(() =>
      expect(screen.getByText('Recompute failed: operator permission required')).toBeInTheDocument(),
    );
  });

  it('shows empty states when the fleet has no targeting data', async () => {
    mocks.targetingHealth.mockResolvedValue({
      tenantsObserved: 0,
      intentCount: 0,
      snapshotCount: 0,
      leakageBySeverity: {},
      intentsBySource: {},
    });
    mocks.targetingLeakageQueue.mockResolvedValue({ queue: [] });
    mocks.targetingMappingQuality.mockResolvedValue({ diagnostics: [] });
    mocks.targetingAudit.mockResolvedValue({ audit: [] });
    renderPage();
    await waitFor(() => expect(screen.getByText('Leakage queue is empty')).toBeInTheDocument());
    expect(screen.getByText('No mapping quality diagnostics')).toBeInTheDocument();
    expect(screen.getByText('No audit entries')).toBeInTheDocument();
  });

  it('shows the error state when the fleet health request fails', async () => {
    mocks.targetingHealth.mockRejectedValue(new Error('fleet unavailable'));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Unable to load targeting fleet health')).toBeInTheDocument(),
    );
    expect(screen.getByText('fleet unavailable')).toBeInTheDocument();
  });

  it('shows the flag-off state and does not fetch when the feature is disabled', async () => {
    mocks.isFeatureEnabled.mockReturnValue(false);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Targeting intelligence is disabled')).toBeInTheDocument(),
    );
    expect(mocks.targetingHealth).not.toHaveBeenCalled();
    expect(mocks.targetingLeakageQueue).not.toHaveBeenCalled();
  });
});

describe('OODA suggestion targeting evidence drawer', () => {
  it('opens the evidence drawer with cluster chips and the evidence chain for targeting suggestions', async () => {
    render(<SuggestionCard suggestion={TARGETING_SUGGESTION_FIXTURE} />);

    await userEvent.click(screen.getByRole('button', { name: 'Targeting evidence' }));
    await waitFor(() => expect(screen.getByTestId('targeting-evidence-drawer')).toBeInTheDocument());

    // Cluster chips.
    expect(screen.getByText('Included clusters')).toBeInTheDocument();
    expect(screen.getByText('cluster_a')).toBeInTheDocument();
    expect(screen.getByText('Excluded clusters')).toBeInTheDocument();
    expect(screen.getAllByText('cluster_z').length).toBeGreaterThan(0);
    expect(screen.getByText('Holdout clusters')).toBeInTheDocument();

    // Evidence chain: intent → snapshot → observation → outcome.
    expect(screen.getByText('Evidence chain')).toBeInTheDocument();
    expect(screen.getByText('Intent: ti_intent_001')).toBeInTheDocument();
    expect(screen.getByText('Snapshot: ti_snap_001')).toBeInTheDocument();
    expect(screen.getByText('Observation: ti_obs_001')).toBeInTheDocument();
    expect(screen.getByText('Outcome: —')).toBeInTheDocument();

    // Evidence refs + non-execution boundary.
    expect(screen.getByText(/ev_leak_001/)).toBeInTheDocument();
    expect(screen.getByText(/Aether does not execute campaigns/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '[x] Close' }));
    expect(screen.queryByTestId('targeting-evidence-drawer')).toBeNull();
  });

  it('does not offer targeting evidence for non-targeting suggestions', () => {
    render(
      <SuggestionCard
        suggestion={{
          suggestion_id: 'sugg_plain_001',
          title: 'Reduce schema drift in ingest',
          status: 'review_required',
          priority: 'P2',
          suggestion_class: 'data_quality',
          confidence_score: 0.6,
        }}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Targeting evidence' })).toBeNull();
  });
});
