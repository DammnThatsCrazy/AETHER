import type { ComponentType } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { BillingPage } from '@aether-app/pages/billing/billing-page';
import { AuditExportsPage } from '@aether-app/pages/audit-exports';
import { CampaignsPage } from '@aether-app/pages/campaigns';
import { Campaign360Page } from '@aether-app/pages/campaigns/campaign-360-page';
import { CampaignQualityPage } from '@aether-app/pages/campaigns/campaign-quality-page';
import { CampaignRegistryPage } from '@aether-app/pages/campaigns/campaign-registry-page';
import { CampaignSourcesPage } from '@aether-app/pages/campaigns/campaign-sources-page';
import { MappingReviewPage } from '@aether-app/pages/campaigns/mapping-review-page';
import { ConnectorsPage } from '@aether-app/pages/connectors';
import { DeliveryHistoryPage } from '@aether-app/pages/connectors';
import { DataQualityPage } from '@aether-app/pages/data-quality';
import { DeploymentDetailPage } from '@aether-app/pages/deployments';
import { DerivativesAccountPage, DerivativesPage } from '@aether-app/pages/derivatives';
import { GraphPage } from '@aether-app/pages/graph';
import { ImportDetailPage } from '@aether-app/pages/imports';
import { InteropMessagePage, InteropPage } from '@aether-app/pages/interop';
import { OnboardingPage } from '@aether-app/pages/onboarding';
import {
  RewardApprovalQueuePage, RewardDecisionsPage, RewardRailSetupPage,
} from '@aether-app/pages/rewards';
import { SecurityPage } from '@aether-app/pages/security';
import { SettingsPage } from '@aether-app/pages/settings/settings-page';
import { StablecoinAssetPage, StablecoinsPage } from '@aether-app/pages/stablecoins';
import { SystemStatusPage } from '@aether-app/pages/system-status';
import { UsagePlanPage } from '@aether-app/pages/usage-plan';
import { UserProfilePage } from '@aether-app/pages/user-profile';
import { UsersPage } from '@aether-app/pages/users';
import { ValueReviewPage } from '@aether-app/pages/value-review';

const providerState = vi.hoisted(() => ({
  account: 'empty' as 'empty' | 'error',
  campaigns: 'empty' as 'empty' | 'error',
  campaignDetail: 'empty' as 'empty' | 'error',
  onboarding: 'empty' as 'empty' | 'error',
  deployment: 'empty' as 'empty' | 'error',
  domain: 'empty' as 'empty' | 'error',
  graph: 'empty' as 'empty' | 'error',
  import: 'empty' as 'empty' | 'error',
  settings: 'empty' as 'empty' | 'error',
  userProfile: 'empty' as 'empty' | 'error',
  rewards: 'empty' as 'empty' | 'error',
}));

const mocks = vi.hoisted(() => ({
  billingEntitlements: vi.fn(),
  billingInvoicePreviews: vi.fn(),
  billingPlan: vi.fn(),
  billingUsageSummary: vi.fn(),
  billingValueCreated: vi.fn(),
  campaignGet: vi.fn(),
  deliveryList: vi.fn(),
  connectors: vi.fn(),
  entitiesList: vi.fn(),
  entitiesSearch: vi.fn(),
  meProfile: vi.fn(),
  auditExportTypes: vi.fn(),
  qualityOverview: vi.fn(),
  qualityEvents: vi.fn(),
  qualityRecommendations: vi.fn(),
  qualityGraph: vi.fn(),
  statusOverview: vi.fn(),
  statusIncidents: vi.fn(),
  valueReview: vi.fn(),
  securityAuditEvents: vi.fn(),
  securityDataRequests: vi.fn(),
  securityDataRetention: vi.fn(),
  securityMyPermissions: vi.fn(),
  securityPolicies: vi.fn(),
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    billing: {
      entitlements: mocks.billingEntitlements,
      invoicePreviews: mocks.billingInvoicePreviews,
      plan: mocks.billingPlan,
      usageSummary: mocks.billingUsageSummary,
      valueCreated: mocks.billingValueCreated,
    },
    campaigns: { get: mocks.campaignGet },
    delivery: { listIntents: mocks.deliveryList },
    connectors: { list: mocks.connectors },
    entities: {
      list: mocks.entitiesList,
      search: mocks.entitiesSearch,
    },
    dataQuality: {
      overview: mocks.qualityOverview,
      events: mocks.qualityEvents,
      recommendations: mocks.qualityRecommendations,
      graph: mocks.qualityGraph,
    },
    status: {
      overview: mocks.statusOverview,
      incidents: mocks.statusIncidents,
    },
    intelligence: { auditExportTypes: mocks.auditExportTypes },
    me: { profile: mocks.meProfile },
    security: {
      auditEvents: mocks.securityAuditEvents,
      dataRequests: mocks.securityDataRequests,
      dataRetention: mocks.securityDataRetention,
      myPermissions: mocks.securityMyPermissions,
      policies: mocks.securityPolicies,
    },
    valueReview: { overview: mocks.valueReview },
  },
}));

vi.mock('@aether-app/features/account', () => ({
  useBillingPlans: () => ({
    data: providerState.account === 'empty' ? [] : undefined,
    isLoading: false,
    error: providerState.account === 'error' ? new Error('billing offline') : null,
  }),
  useInvoices: () => ({
    data: providerState.account === 'empty' ? [] : undefined,
    isLoading: false,
    error: providerState.account === 'error' ? new Error('billing offline') : null,
  }),
  useMeProfile: () => ({ data: undefined, isLoading: false, error: null }),
  useCreateCheckout: () => ({ mutate: vi.fn(), isLoading: false }),
  useBillingPortal: () => ({ mutate: vi.fn(), isLoading: false }),
  useEnterpriseContact: () => ({ mutate: vi.fn(), isLoading: false }),
  useApiKeys: () => ({
    data: providerState.settings === 'empty' ? [] : undefined,
    isLoading: false,
    error: providerState.settings === 'error' ? 'settings backend offline' : null,
    refetch: vi.fn(),
  }),
  useCreateApiKey: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
  useRevokeApiKey: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
}));

vi.mock('@aether-app/features/campaigns/use-campaigns', () => ({
  useCampaigns: () => ({
    data: providerState.campaigns === 'empty' ? { campaigns: [] } : undefined,
    isLoading: false,
    error: providerState.campaigns === 'error' ? new Error('campaigns offline') : null,
  }),
  usePlatformOverview: () => ({
    data: providerState.campaigns === 'empty' ? {} : undefined,
    isLoading: false,
    error: providerState.campaigns === 'error' ? new Error('campaigns offline') : null,
  }),
  useAutomationInsights: () => ({ data: [], isLoading: false, error: null }),
}));

vi.mock('@aether-app/features/campaigns/use-campaign-quality', () => ({
  useCampaignQuality: () => ({
    data: providerState.campaigns === 'empty' ? {} : undefined,
    isLoading: false,
    error: providerState.campaigns === 'error' ? new Error('campaigns offline') : null,
  }),
}));

vi.mock('@aether-app/features/campaigns/use-mapping-review', () => ({
  useMappingReviews: () => ({
    data: providerState.campaigns === 'empty' ? { items: [], total: 0 } : undefined,
    isLoading: false,
    error: providerState.campaigns === 'error' ? new Error('campaigns offline') : null,
  }),
  useResolveReview: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
  useIgnoreReview: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
}));

vi.mock('@aether-app/features/campaigns/use-campaign-sources', () => ({
  useCampaignSources: () => ({
    data: providerState.campaigns === 'empty' ? { items: [] } : undefined,
    isLoading: false,
    error: providerState.campaigns === 'error' ? new Error('campaigns offline') : null,
    refetch: vi.fn(),
  }),
  useSyncCampaignSource: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
}));

vi.mock('@aether-app/features/campaigns/use-campaign-360', () => {
  const query = (data: Record<string, unknown>) => ({
    data,
    loading: false,
    error: null,
    refetch: vi.fn(),
  });
  return {
    useCampaign360Overview: () => query({}),
    useCampaign360Population: () => query({ entities: [], total: 0 }),
    useCampaign360Clusters: () => query({ clusters: [], total: 0 }),
    useCampaign360Conversions: () => query({ conversions: [], total: 0 }),
    useCampaign360Attribution: () => query({}),
  };
});

vi.mock('@aether-app/features/graph/use-graph-data', () => ({
  useGraphData: () => ({
    nodes: [],
    edges: [],
    clusters: [],
    isLoading: false,
    error: providerState.graph === 'error' ? 'graph offline' : null,
    activeLayer: 'all',
    setActiveLayer: vi.fn(),
    overlay: 'none',
    setOverlay: vi.fn(),
    getNeighbors: vi.fn(() => []),
  }),
}));

vi.mock('@aether-app/features/stablecoins', () => {
  const result = () => providerState.domain === 'empty'
    ? { data: { items: [], count: 0 }, isLoading: false, error: null, refetch: vi.fn() }
    : { data: undefined, isLoading: false, error: 'domain backend offline', refetch: vi.fn() };
  return {
    useStablecoinAssets: result,
    useStablecoinFlows: result,
    useStablecoinValuations: result,
    useStablecoinDeployments: result,
    useStablecoinObservations: result,
  };
});

vi.mock('@aether-app/features/derivatives', () => {
  const result = () => providerState.domain === 'empty'
    ? { data: { items: [], count: 0 }, isLoading: false, error: null, refetch: vi.fn() }
    : { data: undefined, isLoading: false, error: 'domain backend offline', refetch: vi.fn() };
  return {
    useDerivativesAccounts: result,
    useDerivativesFills: result,
    useDerivativesOrders: result,
    useDerivativesPnl: result,
    useDerivativesPositions: result,
    useDerivativesVariances: result,
    useDerivativesVenues: result,
  };
});

vi.mock('@aether-app/features/interop', () => {
  const result = () => providerState.domain === 'empty'
    ? { data: { items: [], count: 0 }, isLoading: false, error: null, refetch: vi.fn() }
    : { data: undefined, isLoading: false, error: 'domain backend offline', refetch: vi.fn() };
  const detail = () => providerState.domain === 'empty'
    ? {
        data: { message: {}, transitions: [], delivery_attempts: [], asset_legs: [] },
        isLoading: false, error: null, refetch: vi.fn(),
      }
    : { data: undefined, isLoading: false, error: 'domain backend offline', refetch: vi.fn() };
  return {
    useInteropMessages: result,
    useInteropPaths: result,
    useInteropProviders: result,
    useInteropMessageDetail: detail,
  };
});

vi.mock('@aether-app/features/deployments', () => ({
  useAgentDeployment: () => ({
    deployment: null,
    loading: false,
    error: providerState.deployment === 'error' ? 'deployment backend offline' : null,
    refresh: vi.fn(),
  }),
  useAgentDeploymentHealth: () => ({ health: null, loading: false, error: null }),
  useAgentDeploymentActivity: () => ({ activity: [], loading: false, error: null }),
  useDeploymentLifecycle: () => ({ run: vi.fn(), loading: false, error: null }),
}));

vi.mock('@aether-app/features/imports', () => {
  const mutation = (name: string) => ({ [name]: vi.fn(), loading: false, error: null });
  return {
    useImportDetail: () => ({
      detail: null,
      loading: false,
      error: providerState.import === 'error' ? 'import backend offline' : null,
      refresh: vi.fn(),
    }),
    useImportCommits: () => ({ commits: [], count: 0, loading: false, error: null }),
    useUploadImportFile: () => mutation('upload'),
    useAnalyzeImport: () => mutation('analyze'),
    useSaveImportMapping: () => mutation('save'),
    useValidateImport: () => mutation('validate'),
    useApproveImport: () => mutation('approve'),
    useCancelImport: () => mutation('cancel'),
    useCommitImport: () => mutation('commit'),
    useReplayImport: () => mutation('replay'),
    useRollbackImport: () => mutation('rollback'),
  };
});

vi.mock('@aether-app/features/intelligence', () => {
  const result = () => ({ data: {}, isLoading: false, error: null, refetch: vi.fn() });
  return { useOutcomeLedger: result, useProfileOutcomeLedger: result };
});

vi.mock('@aether-app/features/sdk', () => {
  const query = () => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn() });
  const mutation = () => ({ mutate: vi.fn(), isLoading: false, error: null });
  return {
    useSdkFleet: query,
    useSilentSdks: query,
    useSdkManifest: query,
    useSdkRollout: query,
    useRollbackManifest: mutation,
    usePublishManifest: mutation,
  };
});

vi.mock('@aether-app/features/notifications/use-notification-channels', () => ({
  useNotificationChannels: () => ({
    data: providerState.settings === 'empty' ? [] : undefined,
    isLoading: false,
    error: providerState.settings === 'error' ? 'settings backend offline' : null,
    refetch: vi.fn(),
  }),
  useTestChannel: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
  useRemoveChannel: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
}));

vi.mock('@aether-app/features/account/use-notification-webhooks', () => ({
  useWebhooks: () => ({ data: [], isLoading: false, error: null, refetch: vi.fn() }),
  useCreateWebhook: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
  useDeleteWebhook: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
  useTestWebhook: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
}));

vi.mock('@aether-app/features/users/use-user-profile', () => {
  const query = () => ({
    data: {},
    isLoading: false,
    error: providerState.userProfile === 'error' ? 'profile backend offline' : null,
    refetch: vi.fn(),
  });
  return {
    useUserProfile: query,
    useUserSessions: query,
    useUserDevices: query,
    useUserPlatforms: query,
    useUserJourneys: query,
    useUserWallets: query,
    useUserFinancials: query,
    useUserRewards: query,
    useUserIdentifiers: query,
    useUserIntelligence: query,
    useUserBehavioral: query,
    useUserWhyExplain: query,
    useUserGraph: query,
    useUserCluster: query,
    useUserSemantic: query,
    useUserSocialIntelligence: query,
    useUserRecommendations: query,
    useUserTier: query,
    useUserAssetComposition: query,
    useUserPnl: query,
    useUserTradingProfile: query,
    useUserFunnel: query,
    useUserTimeToConvert: query,
    useUserJourneyEconomics: query,
    useUserDevicePerformance: query,
    useUserProtocolMetrics: query,
    useUserGovernanceActivity: query,
    useUserQuality: query,
    useUserDataFreshness: query,
    useUserWeb2Profile: query,
  };
});

vi.mock('@aether-app/features/journey', () => ({
  useUnifiedJourney: () => ({ steps: [], loading: false, error: null }),
  TouchpointEvidenceInspector: () => null,
}));

vi.mock('@aether-app/features/onboarding', () => {
  const query = () => ({
    data: providerState.onboarding === 'empty' ? {} : undefined,
    isLoading: false,
    error: providerState.onboarding === 'error' ? 'onboarding backend offline' : null,
    refetch: vi.fn(),
  });
  return {
    useOnboardingStatus: query,
    useOnboardingChecklist: query,
    useSdkInstructions: query,
    useEventRequirements: query,
    useGoLiveReadiness: query,
    usePatchOnboardingStep: () => ({ mutate: vi.fn(), isLoading: false, error: null }),
  };
});

vi.mock('@aether-app/features/rewards/use-rewards', () => {
  const query = () => ({
    data: providerState.rewards === 'empty' ? { items: [] } : undefined,
    isLoading: false,
    error: providerState.rewards === 'error' ? 'rewards backend offline' : null,
    refetch: vi.fn(),
  });
  return {
    useRewardsDecisions: query,
    useRewardsApprovalQueue: query,
    useRewardsRails: query,
  };
});

vi.mock('@aether-app/components/graph/graph-canvas', () => ({
  GraphCanvas: () => <div data-testid="empty-graph-canvas" />,
}));

function renderRoute(Page: ComponentType, route = '/', routePattern = route) {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]}>
          <Routes><Route path={routePattern} element={<Page />} /></Routes>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

interface RouteStateCase {
  readonly route: string;
  readonly routePattern?: string;
  readonly Page: ComponentType;
  readonly empty: () => void;
  readonly fail: () => void;
  readonly emptyText: string;
  readonly errorText: string;
  readonly enterEmptySurface?: () => Promise<void>;
}

const cases: RouteStateCase[] = [
  {
    route: '/users',
    Page: UsersPage,
    empty: () => mocks.entitiesList.mockResolvedValue({ entities: [] }),
    fail: () => mocks.entitiesList.mockRejectedValue(new Error('entities offline')),
    emptyText: 'No users found',
    errorText: 'Failed to load users',
  },
  {
    route: '/users/user-local',
    routePattern: '/users/:id',
    Page: UserProfilePage,
    empty: () => { providerState.userProfile = 'empty'; },
    fail: () => { providerState.userProfile = 'error'; },
    emptyText: 'No semantic signal yet',
    errorText: 'Failed to load user profile',
  },
  {
    route: '/campaigns',
    Page: CampaignsPage,
    empty: () => { providerState.campaigns = 'empty'; },
    fail: () => { providerState.campaigns = 'error'; },
    emptyText: 'No campaigns',
    errorText: 'Failed to load overview',
    enterEmptySurface: async () => { await userEvent.click(await screen.findByText('All campaigns')); },
  },
  {
    route: '/campaign-intelligence',
    Page: CampaignsPage,
    empty: () => { providerState.campaigns = 'empty'; },
    fail: () => { providerState.campaigns = 'error'; },
    emptyText: 'No campaigns',
    errorText: 'Failed to load overview',
    enterEmptySurface: async () => { await userEvent.click(await screen.findByText('All campaigns')); },
  },
  {
    route: '/campaigns/campaign-local?tab=population',
    routePattern: '/campaigns/:id',
    Page: Campaign360Page,
    empty: () => {
      providerState.campaignDetail = 'empty';
      mocks.campaignGet.mockResolvedValue({ id: 'campaign-local', name: 'Campaign local', status: 'active' });
    },
    fail: () => {
      providerState.campaignDetail = 'error';
      mocks.campaignGet.mockRejectedValue(new Error('campaign backend offline'));
    },
    emptyText: 'No entities',
    errorText: 'Failed to load campaign',
  },
  {
    route: '/campaign-intelligence/registry',
    Page: CampaignRegistryPage,
    empty: () => { providerState.campaigns = 'empty'; },
    fail: () => { providerState.campaigns = 'error'; },
    emptyText: 'No campaigns in registry',
    errorText: 'Failed to load registry',
  },
  {
    route: '/campaign-intelligence/sources',
    Page: CampaignSourcesPage,
    empty: () => { providerState.campaigns = 'empty'; },
    fail: () => { providerState.campaigns = 'error'; },
    emptyText: 'No campaign sources connected',
    errorText: 'Failed to load sources',
  },
  {
    route: '/campaign-intelligence/mapping-review',
    Page: MappingReviewPage,
    empty: () => { providerState.campaigns = 'empty'; },
    fail: () => { providerState.campaigns = 'error'; },
    emptyText: 'No open reviews',
    errorText: 'Failed to load reviews',
  },
  {
    route: '/campaign-intelligence/quality',
    Page: CampaignQualityPage,
    empty: () => { providerState.campaigns = 'empty'; },
    fail: () => { providerState.campaigns = 'error'; },
    emptyText: 'No quality metrics available',
    errorText: 'Failed to load quality metrics',
  },
  {
    route: '/graph',
    Page: GraphPage,
    empty: () => {
      providerState.graph = 'empty';
      mocks.meProfile.mockResolvedValue({ tenant_id: 'tenant-local' });
    },
    fail: () => {
      providerState.graph = 'error';
      mocks.meProfile.mockResolvedValue({ tenant_id: 'tenant-local' });
    },
    emptyText: 'No graph data',
    errorText: 'Failed to load graph',
  },
  {
    route: '/billing',
    Page: BillingPage,
    empty: () => { providerState.account = 'empty'; },
    fail: () => { providerState.account = 'error'; },
    emptyText: 'No invoices yet.',
    errorText: 'Failed to load plans',
  },
  {
    route: '/settings',
    Page: SettingsPage,
    empty: () => { providerState.settings = 'empty'; },
    fail: () => { providerState.settings = 'error'; },
    emptyText: 'No API keys yet',
    errorText: 'Failed to load API keys',
  },
  {
    route: '/settings/notifications',
    Page: SettingsPage,
    empty: () => { providerState.settings = 'empty'; },
    fail: () => { providerState.settings = 'error'; },
    emptyText: 'No channels connected',
    errorText: 'Failed to load channels — check your connection',
  },
  {
    route: '/usage-plan',
    Page: UsagePlanPage,
    empty: () => {
      mocks.billingPlan.mockResolvedValue({ plan: null });
      mocks.billingEntitlements.mockResolvedValue({ entitlements: [] });
      mocks.billingUsageSummary.mockResolvedValue({});
      mocks.billingInvoicePreviews.mockResolvedValue({ items: [] });
      mocks.billingValueCreated.mockResolvedValue({ items: [] });
    },
    fail: () => mocks.billingPlan.mockRejectedValue(new Error('usage offline')),
    emptyText: 'Usage has not been measured',
    errorText: 'Unable to load Usage & Plan',
  },
  {
    route: '/onboarding',
    Page: OnboardingPage,
    empty: () => { providerState.onboarding = 'empty'; },
    fail: () => { providerState.onboarding = 'error'; },
    emptyText: 'No checklist yet',
    errorText: 'Onboarding status unavailable',
  },
  {
    route: '/audit-exports',
    Page: AuditExportsPage,
    empty: () => mocks.auditExportTypes.mockResolvedValue({ items: [] }),
    fail: () => mocks.auditExportTypes.mockRejectedValue(new Error('audit backend offline')),
    emptyText: 'No exports yet',
    errorText: 'Audit export error',
  },
  {
    route: '/security',
    Page: SecurityPage,
    empty: () => {
      mocks.securityMyPermissions.mockResolvedValue({ roles: [], permissions: [] });
      mocks.securityAuditEvents.mockResolvedValue({ items: [] });
      mocks.securityPolicies.mockResolvedValue({ items: [] });
      mocks.securityDataRetention.mockResolvedValue({ items: [] });
      mocks.securityDataRequests.mockResolvedValue({ items: [] });
    },
    fail: () => mocks.securityMyPermissions.mockRejectedValue(new Error('security backend offline')),
    emptyText: 'No permissions resolved',
    errorText: 'Security & Governance error',
  },
  {
    route: '/value-review',
    Page: ValueReviewPage,
    empty: () => mocks.valueReview.mockResolvedValue({}),
    fail: () => mocks.valueReview.mockRejectedValue(new Error('value review offline')),
    emptyText: 'No value evidence yet',
    errorText: 'Unable to load Value Review',
  },
  {
    route: '/integrations',
    Page: ConnectorsPage,
    empty: () => mocks.connectors.mockResolvedValue({ items: [] }),
    fail: () => mocks.connectors.mockRejectedValue(new Error('connectors offline')),
    emptyText: 'No connectors available',
    errorText: 'Unable to load connectors',
  },
  {
    route: '/data-quality',
    Page: DataQualityPage,
    empty: () => {
      mocks.qualityOverview.mockResolvedValue({ score: {}, dimensions: {} });
      mocks.qualityEvents.mockResolvedValue({});
      mocks.qualityRecommendations.mockResolvedValue({});
      mocks.qualityGraph.mockResolvedValue({});
    },
    fail: () => {
      mocks.qualityOverview.mockRejectedValue(new Error('quality offline'));
      mocks.qualityEvents.mockRejectedValue(new Error('quality offline'));
      mocks.qualityRecommendations.mockRejectedValue(new Error('quality offline'));
      mocks.qualityGraph.mockRejectedValue(new Error('quality offline'));
    },
    emptyText: 'No quality score yet',
    errorText: 'Data Quality error',
  },
  {
    route: '/system-status',
    Page: SystemStatusPage,
    empty: () => {
      mocks.statusOverview.mockResolvedValue({
        tenant_id: 'tenant-local',
        overall_status: 'operational',
        active_incidents: 0,
      });
      mocks.statusIncidents.mockResolvedValue({ active: [], resolved: [] });
    },
    fail: () => {
      mocks.statusOverview.mockRejectedValue(new Error('status offline'));
      mocks.statusIncidents.mockRejectedValue(new Error('status offline'));
    },
    emptyText: 'No active incidents',
    errorText: 'Unable to load system status',
  },
  {
    route: '/deployments/deployment-local',
    routePattern: '/deployments/:id',
    Page: DeploymentDetailPage,
    empty: () => { providerState.deployment = 'empty'; },
    fail: () => { providerState.deployment = 'error'; },
    emptyText: 'Deployment not found',
    errorText: 'Failed to load deployment',
  },
  {
    route: '/imports/import-local',
    routePattern: '/imports/:id',
    Page: ImportDetailPage,
    empty: () => { providerState.import = 'empty'; },
    fail: () => { providerState.import = 'error'; },
    emptyText: 'Import not found',
    errorText: 'Failed to load import',
  },
  {
    route: '/delivery',
    Page: DeliveryHistoryPage,
    empty: () => {
      mocks.meProfile.mockResolvedValue({ tenant_id: 'tenant-local' });
      mocks.deliveryList.mockResolvedValue({ items: [] });
    },
    fail: () => {
      mocks.meProfile.mockResolvedValue({ tenant_id: 'tenant-local' });
      mocks.deliveryList.mockRejectedValue(new Error('delivery backend offline'));
    },
    emptyText: 'No delivery records',
    errorText: 'Unable to load delivery history',
  },
  {
    route: '/rewards',
    Page: RewardDecisionsPage,
    empty: () => { providerState.rewards = 'empty'; },
    fail: () => { providerState.rewards = 'error'; },
    emptyText: 'No eligibility decisions',
    errorText: 'Failed to load decisions',
  },
  {
    route: '/rewards/decisions',
    Page: RewardDecisionsPage,
    empty: () => { providerState.rewards = 'empty'; },
    fail: () => { providerState.rewards = 'error'; },
    emptyText: 'No eligibility decisions',
    errorText: 'Failed to load decisions',
  },
  {
    route: '/rewards/approval-queue',
    Page: RewardApprovalQueuePage,
    empty: () => { providerState.rewards = 'empty'; },
    fail: () => { providerState.rewards = 'error'; },
    emptyText: 'No actions pending approval',
    errorText: 'Failed to load approval queue',
  },
  {
    route: '/rewards/rails',
    Page: RewardRailSetupPage,
    empty: () => { providerState.rewards = 'empty'; },
    fail: () => { providerState.rewards = 'error'; },
    emptyText: 'No rails returned from server',
    errorText: 'Failed to load rail configuration',
  },
  {
    route: '/stablecoins',
    Page: StablecoinsPage,
    empty: () => { providerState.domain = 'empty'; },
    fail: () => { providerState.domain = 'error'; },
    emptyText: 'No stablecoin assets registered',
    errorText: 'domain backend offline',
  },
  {
    route: '/stablecoins/usdc',
    routePattern: '/stablecoins/:assetId',
    Page: StablecoinAssetPage,
    empty: () => { providerState.domain = 'empty'; },
    fail: () => { providerState.domain = 'error'; },
    emptyText: 'No deployments',
    errorText: 'domain backend offline',
  },
  {
    route: '/derivatives',
    Page: DerivativesPage,
    empty: () => { providerState.domain = 'empty'; },
    fail: () => { providerState.domain = 'error'; },
    emptyText: 'No linked accounts',
    errorText: 'domain backend offline',
  },
  {
    route: '/derivatives/accounts/account-local',
    routePattern: '/derivatives/accounts/:accountId',
    Page: DerivativesAccountPage,
    empty: () => { providerState.domain = 'empty'; },
    fail: () => { providerState.domain = 'error'; },
    emptyText: 'No orders observed',
    errorText: 'domain backend offline',
  },
  {
    route: '/interoperability',
    Page: InteropPage,
    empty: () => { providerState.domain = 'empty'; },
    fail: () => { providerState.domain = 'error'; },
    emptyText: 'No messages observed',
    errorText: 'domain backend offline',
  },
  {
    route: '/interoperability/messages/message-local',
    routePattern: '/interoperability/messages/:messageId',
    Page: InteropMessagePage,
    empty: () => { providerState.domain = 'empty'; },
    fail: () => { providerState.domain = 'error'; },
    emptyText: 'No lifecycle transitions recorded',
    errorText: 'domain backend offline',
  },
];

describe('Aether page route-state family', () => {
  beforeEach(() => {
    Object.values(mocks).forEach(mock => mock.mockReset());
    providerState.account = 'empty';
    providerState.campaigns = 'empty';
    providerState.campaignDetail = 'empty';
    providerState.deployment = 'empty';
    providerState.domain = 'empty';
    providerState.graph = 'empty';
    providerState.import = 'empty';
    providerState.onboarding = 'empty';
    providerState.rewards = 'empty';
    providerState.settings = 'empty';
    providerState.userProfile = 'empty';
  });

  it.each(cases)('$route renders successful empty from a successful backend response', async ({
    Page, route, routePattern, empty, emptyText, errorText, enterEmptySurface,
  }) => {
    empty();
    renderRoute(Page, route, routePattern);
    if (enterEmptySurface) await enterEmptySurface();
    expect(await screen.findByText(emptyText)).toBeInTheDocument();
    expect(screen.queryByText(errorText)).not.toBeInTheDocument();
  });

  it.each(cases)('$route renders unavailable, never successful empty', async ({
    Page, route, routePattern, fail, errorText, emptyText,
  }) => {
    fail();
    renderRoute(Page, route, routePattern);
    expect(await screen.findByText(errorText)).toBeInTheDocument();
    expect(screen.queryByText(emptyText)).not.toBeInTheDocument();
  });
});
