import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';
import { CampaignTargetingIntelligenceTab, ClusterTargetingImpactTab } from '@aether-app/features/targeting-intelligence';
import { TenantSuggestionCard } from '@aether-app/features/suggestions/components/TenantSuggestionCard';

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

const mocks = vi.hoisted(() => ({
  fetchCampaignTargetingIntelligence: vi.fn(),
  fetchClusterTargetingImpact: vi.fn(),
  fetchJourneyDeltas: vi.fn(),
  fetchTargetingExports: vi.fn(),
  fetchTargetingHoldouts: vi.fn(),
  createTargetingExport: vi.fn(),
}));

vi.mock('@aether-app/features/targeting-intelligence/api', () => mocks);

// Normative execution-boundary copy — asserted verbatim.
const CAMPAIGN_BOUNDARY_COPY =
  'Aether does not execute this campaign. Execution happens in your external platforms.';
const EXPORT_BOUNDARY_COPY =
  'This package is for your external platform. Aether does not execute it.';

// ── Fixtures: one full evidence chain (intent → snapshot → observation with
// leakage → impact → export) ────────────────────────────────────────────────

const INTENT_FIXTURE = {
  id: 'ti_intent_001',
  tenantId: 'tenant_demo_001',
  campaignId: 'camp_spring_launch_001',
  source: 'tenant_declared',
  executionBoundary: 'external_execution_required',
  executionByAether: false as const,
  externalExecutionRequired: true as const,
  includeClusters: ['cluster_a', 'cluster_b'],
  referenceClusters: ['cluster_c'],
  excludeClusters: ['cluster_z'],
  holdoutClusters: ['cluster_h'],
  rules: [],
  maxHopDepth: 2,
  graphMode: 'multi_source',
  createdAt: '2026-07-01T09:00:00.000Z',
  updatedAt: '2026-07-01T09:00:00.000Z',
  evidenceRefs: [],
};

const SNAPSHOT_FIXTURE = {
  snapshotId: 'ti_snap_001',
  tenantId: 'tenant_demo_001',
  campaignId: 'camp_spring_launch_001',
  targetingIntentId: 'ti_intent_001',
  asOf: '2026-07-02T00:00:00.000Z',
  eligibleClusters: ['cluster_a', 'cluster_b'],
  excludedClusters: ['cluster_z'],
  holdoutClusters: ['cluster_h'],
  identityConfidenceThreshold: 0.7,
  clusterMembershipThreshold: 0.6,
  pathConfidenceThreshold: 0.5,
  evidenceCoverageThreshold: 0.5,
  clusterMemberCounts: { cluster_a: 1240, cluster_b: 860 },
  evidenceRefs: [],
  createdAt: '2026-07-02T00:00:00.000Z',
};

const MAPPING_QUALITY_FIXTURE = {
  campaignId: 'camp_spring_launch_001',
  provider: 'meta_ads',
  mappingRate: 0.92,
  providerSyncFreshness: 'recent',
  unresolvedAliasCount: 14,
  touchpointResolutionRate: 0.88,
  identityResolutionRate: 0.81,
  clusterAssignmentRate: 0.86,
  qualityScore: 0.87,
  blocksSuggestions: false,
  reasons: [],
  computedAt: '2026-07-08T12:00:00.000Z',
};

const OBSERVATION_FIXTURE = {
  observationId: 'ti_obs_001',
  tenantId: 'tenant_demo_001',
  campaignId: 'camp_spring_launch_001',
  targetingIntentId: 'ti_intent_001',
  eligibilitySnapshotId: 'ti_snap_001',
  sourceProvider: 'meta_ads',
  reachedClusters: ['cluster_a', 'cluster_c', 'cluster_z'],
  reachedIncludedClusters: ['cluster_a'],
  reachedReferenceClusters: ['cluster_c'],
  reachedExcludedClusters: ['cluster_z'],
  reachedHoldoutClusters: [],
  providerMappingQuality: MAPPING_QUALITY_FIXTURE,
  observedAt: '2026-07-08T11:00:00.000Z',
  computedAt: '2026-07-08T12:00:00.000Z',
  evidenceRefs: [],
};

const LEAKAGE_FIXTURE = {
  findingId: 'ti_leak_001',
  tenantId: 'tenant_demo_001',
  campaignId: 'camp_spring_launch_001',
  targetingIntentId: 'ti_intent_001',
  clusterId: 'cluster_z',
  reasonCode: 'fraud_risk',
  excludedEntityCount: 410,
  reachedEntityCount: 37,
  leakageRate: 0.09,
  likelyCauses: ['provider_ignored_exclusion', 'lookalike_expansion'],
  severity: 'high',
  evidenceRefs: ['ev_obs_001', 'ev_leak_001'],
  computedAt: '2026-07-08T12:00:00.000Z',
};

const SUMMARY_FIXTURE = {
  campaignId: 'camp_spring_launch_001',
  intents: [INTENT_FIXTURE],
  latestSnapshots: [SNAPSHOT_FIXTURE],
  observations: [OBSERVATION_FIXTURE],
  leakageFindings: [LEAKAGE_FIXTURE],
  mappingQuality: MAPPING_QUALITY_FIXTURE,
  executionByAether: false,
  externalExecutionRequired: true,
};

const JOURNEY_DELTA_FIXTURE = {
  deltaId: 'ti_delta_001',
  tenantId: 'tenant_demo_001',
  campaignId: 'camp_spring_launch_001',
  clusterId: 'cluster_a',
  comparedToClusterIds: ['cluster_c', 'cluster_d'],
  holdoutClusterIds: ['cluster_h'],
  populationStageDeltas: { engaged: 0.12, converted: 0.04 },
  reachedCount: 980,
  engagedCount: 410,
  convertedCount: 96,
  attributedCount: 74,
  nonProgressedCount: 570,
  progressedElsewhereCount: 22,
  evidenceRefs: [],
  computedAt: '2026-07-09T00:00:00.000Z',
};

const IMPACT_FIXTURE = {
  tenantId: 'tenant_demo_001',
  campaignId: 'camp_spring_launch_001',
  clusterId: 'cluster_a',
  memberCount: 1240,
  eligibleCount: 1100,
  reachedCount: 980,
  engagedCount: 410,
  convertedCount: 96,
  attributedCount: 74,
  spendUsd: 5400.5,
  revenueUsd: 12800.75,
  roas: 2.37,
  ltvDelta: 41.2,
  complaintRate: 0.004,
  unsubscribeRate: 0.011,
  churnSignalRate: 0.008,
  fraudSignalRate: 0.001,
  overexposureScore: 0.32,
  identityConfidence: 0.82,
  clusterMembershipConfidence: 0.77,
  evidenceCoverage: 0.9,
  computedAt: '2026-07-09T00:00:00.000Z',
  evidenceRefs: [],
};

const EXPORT_FIXTURE = {
  exportId: 'ti_export_001',
  tenantId: 'tenant_demo_001',
  suggestionId: 'sugg_targeting_001',
  targetingIntentId: 'ti_intent_001',
  campaignId: 'camp_spring_launch_001',
  includeClusterIds: ['cluster_a', 'cluster_b'],
  referenceClusterIds: ['cluster_c'],
  excludeClusterIds: ['cluster_z'],
  holdoutClusterIds: ['cluster_h'],
  implementationNotes: [
    'Re-apply the exclusion list for cluster_z in your external campaign platform.',
  ],
  externalExecutionRequired: true as const,
  executionByAether: false as const,
  evidenceRefs: [],
  generatedAt: '2026-07-09T08:00:00.000Z',
};

const TARGETING_SUGGESTION_FIXTURE = {
  id: 'sugg_targeting_001',
  title: 'Exclusion leakage observed in cluster cluster_z',
  summary: 'Cluster cluster_z was excluded but 37 reach events were observed.',
  what: 'The eligibility snapshot excluded cluster_z, yet reach was observed.',
  why: 'Observed leakage correlates with: provider_ignored_exclusion.',
  impact: 'Excluded audiences receiving campaign exposure can violate tenant policy.',
  recommended_action: 'Re-apply the exclusion lists in your external campaign platform.',
  confidence_score: 0.72,
  priority: 'P1',
  status: 'suggested',
  suggestion_class: 'retargeting',
  created_at: '2026-07-08T12:30:00.000Z',
  targeting: {
    includeClusterIds: ['cluster_a', 'cluster_b'],
    referenceClusterIds: ['cluster_c'],
    excludeClusterIds: ['cluster_z'],
    holdoutClusterIds: ['cluster_h'],
    evidenceChain: {
      targetingIntentId: 'ti_intent_001',
      eligibilitySnapshotId: 'ti_snap_001',
      observationId: 'ti_obs_001',
      outcomeSnapshotId: 'ti_outcome_001',
    },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  queryCache.invalidatePrefix('targeting-intelligence');
  mocks.fetchCampaignTargetingIntelligence.mockResolvedValue({ summary: SUMMARY_FIXTURE, notConfigured: false });
  mocks.fetchClusterTargetingImpact.mockResolvedValue({
    response: { clusterId: 'cluster_a', impact: IMPACT_FIXTURE, journeyDeltas: [JOURNEY_DELTA_FIXTURE] },
    notConfigured: false,
  });
  mocks.fetchJourneyDeltas.mockResolvedValue({ journeyDeltas: [JOURNEY_DELTA_FIXTURE], notConfigured: false });
  mocks.fetchTargetingExports.mockResolvedValue({ exports: [EXPORT_FIXTURE], notConfigured: false });
  mocks.fetchTargetingHoldouts.mockResolvedValue({ holdouts: [], notConfigured: false });
  mocks.createTargetingExport.mockResolvedValue({ ...EXPORT_FIXTURE, exportId: 'ti_export_new_001' });
});

// ── Campaign360 Targeting Intelligence tab ─────────────────────────────────────

describe('Campaign360 Targeting Intelligence tab', () => {
  it('renders intent vs observation chips, snapshot summary, leakage severity, mapping quality, and the boundary copy', async () => {
    render(<CampaignTargetingIntelligenceTab campaignId="camp_spring_launch_001" />);
    await waitFor(() => expect(screen.getByText(CAMPAIGN_BOUNDARY_COPY)).toBeInTheDocument());

    // Intended vs observed cluster chips with reach-overlap indicators.
    expect(screen.getByText('Intended vs observed targeting')).toBeInTheDocument();
    expect(screen.getAllByText('Included clusters').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Excluded clusters').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Reference clusters').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Holdout clusters').length).toBeGreaterThan(0);
    expect(screen.getAllByText('cluster_a').length).toBeGreaterThan(0);
    // Included cluster_a was reached (expected), excluded cluster_z was reached (violation).
    expect(screen.getAllByText('· reached ✓').length).toBeGreaterThan(0);
    expect(screen.getAllByText('· reached ⚠').length).toBeGreaterThan(0);
    expect(screen.getAllByText('· not reached').length).toBeGreaterThan(0);

    // Eligibility snapshot summary: counts + thresholds.
    expect(screen.getByText('ti_snap_001')).toBeInTheDocument();
    expect(screen.getByText('Eligible members')).toBeInTheDocument();
    expect(screen.getByText('2,100')).toBeInTheDocument();
    expect(screen.getByText('Identity confidence')).toBeInTheDocument();
    expect(screen.getByText('70.0%')).toBeInTheDocument();

    // Exclusion leakage findings with severity badge, causes, evidence count.
    expect(screen.getByText('Exclusion leakage')).toBeInTheDocument();
    const severityBadge = screen.getAllByText('high').find(el => el.classList.contains('ui-badge'));
    expect(severityBadge).toBeDefined();
    expect(screen.getByText('provider ignored exclusion')).toBeInTheDocument();
    expect(screen.getByText('lookalike expansion')).toBeInTheDocument();
    expect(screen.getByText('2 evidence refs')).toBeInTheDocument();
    expect(screen.getByText('9.0%')).toBeInTheDocument();

    // Provider mapping quality panel.
    expect(screen.getByText('Provider mapping quality')).toBeInTheDocument();
    expect(screen.getByText('92.0%')).toBeInTheDocument();
    expect(screen.getByText('sync: recent')).toBeInTheDocument();

    // Journey deltas + evidence chain.
    expect(screen.getByText('Journey-stage deltas')).toBeInTheDocument();
    expect(screen.getByText('Evidence chain')).toBeInTheDocument();
    expect(screen.getByText('Intent: ti_intent_001')).toBeInTheDocument();
    expect(screen.getByText('Observation: ti_obs_001')).toBeInTheDocument();
  });

  it('warns when provider mapping quality blocks suggestions', async () => {
    mocks.fetchCampaignTargetingIntelligence.mockResolvedValue({
      summary: {
        ...SUMMARY_FIXTURE,
        mappingQuality: { ...MAPPING_QUALITY_FIXTURE, blocksSuggestions: true, qualityScore: 0.3 },
      },
      notConfigured: false,
    });
    render(<CampaignTargetingIntelligenceTab campaignId="camp_spring_launch_001" />);
    await waitFor(() =>
      expect(
        screen.getByText('Provider mapping confidence is too low — targeting suggestions are blocked until mapping quality improves.'),
      ).toBeInTheDocument(),
    );
  });

  it('exports a recommendation package and shows the export boundary copy', async () => {
    render(<CampaignTargetingIntelligenceTab campaignId="camp_spring_launch_001" />);
    await waitFor(() => expect(screen.getByText(CAMPAIGN_BOUNDARY_COPY)).toBeInTheDocument());

    // Pre-existing export for this campaign renders with the boundary copy.
    await waitFor(() => expect(screen.getByText('ti_export_001')).toBeInTheDocument());
    expect(screen.getAllByText(EXPORT_BOUNDARY_COPY).length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole('button', { name: 'Export recommendation package' }));
    await waitFor(() =>
      expect(mocks.createTargetingExport).toHaveBeenCalledWith({ targetingIntentId: 'ti_intent_001' }),
    );
    await waitFor(() => expect(screen.getByText('Recommendation package exported.')).toBeInTheDocument());
    expect(screen.getByText('ti_export_new_001')).toBeInTheDocument();
    expect(
      screen.getAllByText('Re-apply the exclusion list for cluster_z in your external campaign platform.').length,
    ).toBeGreaterThan(0);

    // The package JSON is copyable.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    await userEvent.click(screen.getByRole('button', { name: 'Copy JSON for export ti_export_new_001' }));
    await waitFor(() => expect(screen.getByText('Copied')).toBeInTheDocument());
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('ti_export_new_001'));
  });

  it('shows empty states when no targeting intelligence exists yet', async () => {
    mocks.fetchCampaignTargetingIntelligence.mockResolvedValue({
      summary: {
        campaignId: 'camp_other',
        intents: [],
        latestSnapshots: [],
        observations: [],
        leakageFindings: [],
        mappingQuality: null,
        executionByAether: false,
        externalExecutionRequired: true,
      },
      notConfigured: false,
    });
    mocks.fetchJourneyDeltas.mockResolvedValue({ journeyDeltas: [], notConfigured: false });
    mocks.fetchTargetingExports.mockResolvedValue({ exports: [], notConfigured: false });
    render(<CampaignTargetingIntelligenceTab campaignId="camp_other" />);
    await waitFor(() => expect(screen.getByText('No targeting intent declared')).toBeInTheDocument());
    expect(screen.getByText('No eligibility snapshot')).toBeInTheDocument();
    expect(screen.getByText('No exclusion leakage detected')).toBeInTheDocument();
    expect(screen.getByText('No provider mapping quality yet')).toBeInTheDocument();
    expect(screen.getByText('No journey deltas yet')).toBeInTheDocument();
    expect(screen.getByText('No export packages yet')).toBeInTheDocument();
    // The boundary copy stays visible even when empty.
    expect(screen.getByText(CAMPAIGN_BOUNDARY_COPY)).toBeInTheDocument();
  });

  it('shows the not-configured state when the targeting plane is disabled', async () => {
    mocks.fetchCampaignTargetingIntelligence.mockResolvedValue({ summary: null, notConfigured: true });
    render(<CampaignTargetingIntelligenceTab campaignId="camp_spring_launch_001" />);
    await waitFor(() =>
      expect(screen.getByText('Targeting intelligence is not configured')).toBeInTheDocument(),
    );
  });

  it('shows the error state when the summary request fails', async () => {
    mocks.fetchCampaignTargetingIntelligence.mockRejectedValue(new Error('boom'));
    render(<CampaignTargetingIntelligenceTab campaignId="camp_spring_launch_001" />);
    await waitFor(() => expect(screen.getByText('Targeting intelligence unavailable')).toBeInTheDocument());
    expect(screen.getByText('boom')).toBeInTheDocument();
  });
});

// ── Cluster360 Targeting Impact tab ────────────────────────────────────────────

describe('Cluster360 Targeting Impact tab', () => {
  it('renders the funnel, currency-labelled economics, negative outcomes, journey deltas, and evidence coverage', async () => {
    render(<ClusterTargetingImpactTab clusterId="cluster_a" />);
    await waitFor(() => expect(screen.getByText('Targeting funnel')).toBeInTheDocument());

    // Funnel: members → eligible → reached → engaged → converted → attributed.
    expect(screen.getByText('Members')).toBeInTheDocument();
    expect(screen.getByText('1,240')).toBeInTheDocument();
    expect(screen.getByText('1,100')).toBeInTheDocument();
    expect(screen.getAllByText('980').length).toBeGreaterThan(0);
    expect(screen.getAllByText('410').length).toBeGreaterThan(0);
    expect(screen.getAllByText('96').length).toBeGreaterThan(0);
    expect(screen.getAllByText('74').length).toBeGreaterThan(0);

    // Economics always carry an explicit currency label — never merged.
    expect(screen.getByText('Spend (USD)')).toBeInTheDocument();
    expect(screen.getByText('5,400.50 USD')).toBeInTheDocument();
    expect(screen.getByText('Revenue (USD)')).toBeInTheDocument();
    expect(screen.getByText('12,800.75 USD')).toBeInTheDocument();
    expect(screen.getByText('2.37x')).toBeInTheDocument();

    // Negative outcome rates + overexposure.
    expect(screen.getByText('Complaint rate')).toBeInTheDocument();
    expect(screen.getByText('0.4%')).toBeInTheDocument();
    expect(screen.getByText('Unsubscribe rate')).toBeInTheDocument();
    expect(screen.getByText('1.1%')).toBeInTheDocument();
    expect(screen.getByText('Overexposure score')).toBeInTheDocument();
    expect(screen.getByText('32.0')).toBeInTheDocument();

    // Journey deltas vs compared clusters.
    expect(screen.getByText('Journey deltas vs compared clusters')).toBeInTheDocument();
    expect(screen.getByText('ti_delta_001')).toBeInTheDocument();
    expect(screen.getByText('cluster_c')).toBeInTheDocument();
    expect(screen.getByText('cluster_d')).toBeInTheDocument();
    expect(screen.getByText('engaged +12.0%')).toBeInTheDocument();

    // Evidence coverage.
    expect(screen.getByText('Evidence coverage')).toBeInTheDocument();
    expect(screen.getByText('90.0%')).toBeInTheDocument();
  });

  it('renders unknown spend as an unknown badge — never as zero', async () => {
    mocks.fetchClusterTargetingImpact.mockResolvedValue({
      response: {
        clusterId: 'cluster_a',
        impact: { ...IMPACT_FIXTURE, spendUsd: null, revenueUsd: null, roas: null, ltvDelta: null },
        journeyDeltas: [],
      },
      notConfigured: false,
    });
    render(<ClusterTargetingImpactTab clusterId="cluster_a" />);
    await waitFor(() => expect(screen.getByText('Targeting funnel')).toBeInTheDocument());
    expect(screen.getAllByText('unknown').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('0.00 USD')).toBeNull();
  });

  it('shows the empty state when the cluster has no observed targeting impact', async () => {
    mocks.fetchClusterTargetingImpact.mockResolvedValue({
      response: { clusterId: 'cluster_x', impact: null, journeyDeltas: [] },
      notConfigured: false,
    });
    render(<ClusterTargetingImpactTab clusterId="cluster_x" />);
    await waitFor(() => expect(screen.getByText('No targeting impact observed')).toBeInTheDocument());
  });

  it('shows the not-configured state when the targeting plane is disabled', async () => {
    mocks.fetchClusterTargetingImpact.mockResolvedValue({ response: null, notConfigured: true });
    render(<ClusterTargetingImpactTab clusterId="cluster_a" />);
    await waitFor(() =>
      expect(screen.getByText('Targeting intelligence is not configured')).toBeInTheDocument(),
    );
  });

  it('shows the error state when the impact request fails', async () => {
    mocks.fetchClusterTargetingImpact.mockRejectedValue(new Error('impact failed'));
    render(<ClusterTargetingImpactTab clusterId="cluster_a" />);
    await waitFor(() => expect(screen.getByText('Targeting impact unavailable')).toBeInTheDocument());
    expect(screen.getByText('impact failed')).toBeInTheDocument();
  });
});

// ── Suggestion feed targeting cards ────────────────────────────────────────────

describe('Suggestion feed targeting cards', () => {
  it('renders cluster chips, the evidence chain, and the export action for targeting suggestions', async () => {
    render(<TenantSuggestionCard suggestion={TARGETING_SUGGESTION_FIXTURE} />);

    expect(screen.getByTestId('targeting-suggestion-section')).toBeInTheDocument();
    expect(screen.getByText('External execution required')).toBeInTheDocument();
    expect(screen.getAllByText('cluster_a').length).toBeGreaterThan(0);
    expect(screen.getAllByText('cluster_z').length).toBeGreaterThan(0);

    // Evidence chain: intent → snapshot → observation → outcome.
    expect(screen.getByText('Evidence chain')).toBeInTheDocument();
    expect(screen.getByText('Intent: ti_intent_001')).toBeInTheDocument();
    expect(screen.getByText('Snapshot: ti_snap_001')).toBeInTheDocument();
    expect(screen.getByText('Observation: ti_obs_001')).toBeInTheDocument();
    expect(screen.getByText('Outcome: ti_outcome_001')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Export implementation package' }));
    await waitFor(() =>
      expect(mocks.createTargetingExport).toHaveBeenCalledWith({ suggestionId: 'sugg_targeting_001' }),
    );
    await waitFor(() => expect(screen.getByText('Implementation package exported.')).toBeInTheDocument());
    expect(screen.getAllByText(EXPORT_BOUNDARY_COPY).length).toBeGreaterThan(0);
  });

  it('shows an error state when the export fails', async () => {
    mocks.createTargetingExport.mockRejectedValue(new Error('export denied'));
    render(<TenantSuggestionCard suggestion={TARGETING_SUGGESTION_FIXTURE} />);
    await userEvent.click(screen.getByRole('button', { name: 'Export implementation package' }));
    await waitFor(() =>
      expect(screen.getByText('Failed to export implementation package')).toBeInTheDocument(),
    );
    expect(screen.getByText('export denied')).toBeInTheDocument();
  });

  it('does not render targeting content for non-targeting suggestions', () => {
    render(
      <TenantSuggestionCard
        suggestion={{
          id: 'sugg_plain_001',
          title: 'Improve onboarding completion',
          summary: 'Completion dropped 8% this week.',
          status: 'suggested',
          priority: 'P2',
          suggestion_class: 'customer_success',
        }}
      />,
    );
    expect(screen.queryByTestId('targeting-suggestion-section')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Export implementation package' })).toBeNull();
  });
});

// ── Tab registration on the 360 pages ──────────────────────────────────────────

vi.mock('@aether-app/features/cluster360/use-cluster360', async importOriginal => {
  const original = await importOriginal<typeof import('@aether-app/features/cluster360/use-cluster360')>();
  return {
    ...original,
    useCluster360: () => ({
      cluster: {
        cluster_id: 'cluster_a',
        cluster_type: 'behavioral',
        label: 'Cluster A',
        tenant_id: 'tenant_demo_001',
        member_count: 1240,
        formation_reason: null,
        confidence: 0.9,
        lifecycle_state: 'active',
        created_at: '2026-06-01T00:00:00.000Z',
        updated_at: '2026-07-01T00:00:00.000Z',
        risk_score: null,
        properties: {},
      },
      members: [],
      timeline: [],
      economic: null,
      campaigns: null,
      risk: null,
      geography: null,
      isLoading: false,
      error: null,
    }),
  };
});

describe('Cluster360 page tab registration', () => {
  it('registers the Targeting Impact tab and renders it on click', async () => {
    const { Cluster360Page } = await import('@aether-app/pages/cluster360');
    render(
      <MemoryRouter initialEntries={['/clusters/cluster_a']}>
        <Routes>
          <Route path="/clusters/:clusterId" element={<Cluster360Page />} />
        </Routes>
      </MemoryRouter>,
    );

    const trigger = await screen.findByRole('tab', { name: 'Targeting Impact' });
    await userEvent.click(trigger);
    await waitFor(() => expect(screen.getByText('Targeting funnel')).toBeInTheDocument());
    expect(screen.getByText('Spend (USD)')).toBeInTheDocument();
  });
});
