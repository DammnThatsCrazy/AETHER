import type { ComponentType } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { ConnectorsPage } from '@kyber/pages/connectors';
import { CommandPage } from '@kyber/pages/command';
import { DiagnosticsPage } from '@kyber/pages/diagnostics';
import { EntitiesPage } from '@kyber/pages/entities';
import { ImportOpsDetailPage } from '@kyber/pages/imports-ops/import-detail-page';
import { IntelligenceQualityPage } from '@kyber/pages/intelligence-quality';
import { InvestigationsPage } from '@kyber/pages/investigations';
import { LivePage } from '@kyber/pages/live';
import { MissionPage } from '@kyber/pages/mission';
import { Profile360Page } from '@kyber/pages/profile360';
import { ReliabilityPage } from '@kyber/pages/reliability';
import { ReviewPage } from '@kyber/pages/review';
import { CisPage } from '@kyber/pages/cis';
import { TenantsPage } from '@kyber/pages/tenants';
import {
  AccessPage,
  AuditPage,
  DevicesPage,
  InvitationsPage,
  RolesPage,
  SecurityPage,
  SessionsPage,
  WorkforcePage,
} from '@kyber/pages/security';

const state = vi.hoisted(() => ({
  connectors: 'empty' as 'empty' | 'error',
  command: 'empty' as 'empty' | 'error',
  diagnostics: 'empty' as 'empty' | 'error',
  entities: 'empty' as 'empty' | 'error',
  intelligence: 'empty' as 'empty' | 'error',
  live: 'empty' as 'empty' | 'error',
  mission: 'empty' as 'empty' | 'error',
  profile: 'empty' as 'empty' | 'error',
  query: 'empty' as 'empty' | 'error',
  reliability: 'empty' as 'empty' | 'error',
  review: 'empty' as 'empty' | 'error',
  security: 'empty' as 'empty' | 'error',
  securityChild: 'empty' as 'empty' | 'error',
}));

vi.mock('@aether/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aether/ui')>();
  return {
    ...actual,
    useQuery: () => ({
      data: null,
      error: state.query === 'error' ? 'kyber backend offline' : null,
      isLoading: false,
      refetch: vi.fn(),
    }),
  };
});

const mocks = vi.hoisted(() => ({
  catalogResponse: vi.fn(),
  connectorsOverview: vi.fn(),
  securityAuditEvents: vi.fn(),
  securityBreakGlassList: vi.fn(),
  securityDataRequests: vi.fn(),
  securityDataRetention: vi.fn(),
  securityEvidencePacks: vi.fn(),
  securityOperatorAccess: vi.fn(),
  securityOverview: vi.fn(),
  securityPolicyDecisions: vi.fn(),
  securityTenantIsolation: vi.fn(),
  solutionPackage: vi.fn(),
}));

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    auditExportHealth: mocks.catalogResponse,
    buyerPersonas: mocks.catalogResponse,
    connectorsOverview: mocks.connectorsOverview,
    deploymentReadiness: mocks.catalogResponse,
    gtmMaterials: mocks.catalogResponse,
    pricingModels: mocks.catalogResponse,
    revopsContracts: mocks.catalogResponse,
    revopsExpansionBillingOpportunities: mocks.catalogResponse,
    revopsInvoicePreviews: mocks.catalogResponse,
    revopsOverview: mocks.catalogResponse,
    revopsRevenueLeakage: mocks.catalogResponse,
    revopsUsage: mocks.catalogResponse,
    revopsValueCreated: mocks.catalogResponse,
    roiCalculators: mocks.catalogResponse,
    salesReadiness: mocks.catalogResponse,
    securityAuditEvents: mocks.securityAuditEvents,
    securityBreakGlassList: mocks.securityBreakGlassList,
    securityDataRequests: mocks.securityDataRequests,
    securityDataRetention: mocks.securityDataRetention,
    securityEvidencePacks: mocks.securityEvidencePacks,
    securityOperatorAccess: mocks.securityOperatorAccess,
    securityOverview: mocks.securityOverview,
    securityPolicyDecisions: mocks.securityPolicyDecisions,
    securityTenantIsolation: mocks.securityTenantIsolation,
    solutionPackage: mocks.solutionPackage,
    solutionPackages: mocks.catalogResponse,
  } } },
}));


vi.mock('@kyber/features/mission', () => ({
  useMissionData: () => ({
    data: null,
    isLoading: false,
    error: state.mission === 'error' ? 'mission backend offline' : null,
  }),
}));

vi.mock('@kyber/features/diagnostics', () => ({
  useDiagnosticsData: () => ({
    health: null,
    isLoading: false,
    error: state.diagnostics === 'error' ? 'diagnostics backend offline' : null,
    suppressError: vi.fn(),
  }),
}));

vi.mock('@kyber/features/live', () => ({
  useLiveEvents: () => ({
    allEvents: [],
    error: state.live === 'error' ? 'live backend offline' : null,
    events: [],
    filter: {},
    isLoading: false,
    isPaused: false,
    pinnedEvents: [],
    setFilter: vi.fn(),
    setIsPaused: vi.fn(),
    totalCount: 0,
    wsStatus: 'disconnected',
  }),
}));

vi.mock('@kyber/features/command', () => ({
  useCommandData: () => ({
    charStatus: state.command === 'error' ? null : {
      activePriorities: [],
      briefSummary: 'No runtime activity was returned.',
      coordinationState: 'nominal',
      escalations: [],
      lastBriefAt: '',
      overallDirective: 'No directive returned',
    },
    controllers: [],
    displayMode: 'functional',
    error: state.command === 'error' ? 'command backend offline' : null,
    isLoading: false,
    objectives: [],
    schedules: [],
    setDisplayMode: vi.fn(),
  }),
}));

vi.mock('@kyber/features/review', () => ({
  useReviewData: () => ({
    auditTrail: [],
    batches: [],
    error: state.review === 'error' ? 'review backend offline' : null,
    isLoading: false,
    resolveItem: vi.fn(),
    selectedBatch: null,
    selectedBatchId: null,
    setSelectedBatchId: vi.fn(),
  }),
}));

vi.mock('@kyber/features/profile360', () => ({
  useProfile360: () => ({
    actions: {},
    entity: undefined,
    error: state.profile === 'error' ? 'profile backend offline' : null,
    graph: { edges: [], nodes: [] },
    highlightedNodeIds: [],
    isLoading: false,
    sections: {},
    timeline: [],
    websocketStatus: 'disconnected',
  }),
}));

vi.mock('@kyber/features/entities', () => ({
  useEntityData: () => ({
    entities: [],
    isLoading: false,
    error: state.entities === 'error' ? 'entities backend offline' : null,
  }),
}));

vi.mock('@kyber/features/reliability', () => ({
  useReliability: () => ({
    data: {
      overview: { service_health_summary: {}, slo_status: {}, error_budget_status: [] },
      services: [],
      pipelines: [],
      queues: [],
      slos: [],
      incidents: [],
      runbooks: [],
      postmortems: [],
    },
    loading: false,
    error: state.reliability === 'error' ? 'reliability backend offline' : null,
  }),
}));

vi.mock('@kyber/features/intelligence-quality', () => ({
  useIntelligenceQuality: () => ({
    data: {
      overview: { score: {}, dimensions: {} },
      tenants: [],
      driftEvents: [],
      contamination: {},
      recommendations: {},
      graph: {},
      identity: {},
    },
    loading: false,
    error: state.intelligence === 'error' ? 'intelligence backend offline' : null,
  }),
}));

vi.mock('@kyber/features/security', () => ({
  useSecurity: () => ({
    data: {
      overview: {},
      policies: { items: [] },
      audit: { items: [] },
      isolation: { checks: [] },
      operator: {},
      breakglass: { items: [] },
      retention: { items: [] },
      requests: { items: [] },
      evidence: { items: [] },
    },
    loading: false,
    error: state.security === 'error' ? 'security backend offline' : null,
  }),
}));

vi.mock('@kyber/features/auth', () => {
  const loadCollection = () => state.securityChild === 'error'
    ? Promise.reject(new Error('security backend offline'))
    : Promise.resolve([]);
  return {
    KyberSessionBanners: () => null,
    SCOPE_PURPOSES: ['customer_support'],
    createInvitation: vi.fn(),
    describePurpose: () => 'Customer support',
    enterScope: vi.fn(),
    exitScope: vi.fn(),
    fetchAuditEvents: loadCollection,
    fetchInvitations: loadCollection,
    fetchScopeHistory: loadCollection,
    fetchWorkforcePrincipals: loadCollection,
    formatCountdown: () => 'unavailable',
    revokeInvitation: vi.fn(),
    useAuth: () => ({
      error: state.securityChild === 'error' ? 'security backend offline' : null,
      isLoading: false,
      lastSyncedAt: null,
      logout: vi.fn(),
      principal: null,
      refresh: vi.fn(),
      status: state.securityChild === 'error' ? 'error' : 'unauthenticated',
    }),
    useKyberDevice: () => ({ mayApproveDevices: false }),
    useKyberPrincipal: () => null,
    useKyberScope: () => ({ isActive: false, scope: null }),
    useKyberSession: () => null,
    useKyberStepUp: () => null,
  };
});

vi.mock('@kyber/features/permissions', () => ({
  PermissionGate: ({ fallback }: { readonly fallback: React.ReactNode }) => fallback,
  useCapabilities: () => ({
    capabilities: [],
    roleTemplateIds: [],
    maxActionClass: 0,
    maxDisclosure: 0,
    isLoading: false,
    has: () => false,
    hasAny: () => false,
    hasAll: () => false,
    canPerformAction: () => false,
    canDisclose: () => false,
    checkAction: () => ({ allowed: false, requiresApproval: false }),
    checkDisclosure: () => ({ allowed: false, requiresApproval: false }),
  }),
  usePermissions: () => ({
    canApprove: false,
    canCommand: false,
    canDiagnose: false,
    canViewPII: false,
    capabilities: [],
    role: '',
  }),
}));

vi.mock('@kyber/features/device-trust', () => ({
  useDeviceAdmin: () => ({ approve: vi.fn(), error: null, isBusy: false, revoke: vi.fn(), suspend: vi.fn() }),
  useDeviceEnrolment: () => ({
    enrol: vi.fn(),
    error: null,
    isSupported: false,
    state: 'idle',
    unsupportedReason: 'Device enrolment unavailable in this test browser.',
  }),
  useDeviceList: () => ({
    devices: [],
    error: state.securityChild === 'error' ? 'security backend offline' : null,
    isForbidden: false,
    isLoading: false,
    refresh: vi.fn(),
  }),
  useDeviceProof: () => ({
    clear: vi.fn(),
    error: null,
    keyState: 'missing',
    lastProvedAt: null,
    prove: vi.fn(),
  }),
}));

function renderRoute(Page: ComponentType, route: string, routePattern = route) {
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
    route: '/mission',
    Page: MissionPage,
    empty: () => { state.mission = 'empty'; },
    fail: () => { state.mission = 'error'; },
    emptyText: 'No data available',
    errorText: 'mission backend offline',
  },
  {
    route: '/entities',
    Page: EntitiesPage,
    empty: () => { state.entities = 'empty'; },
    fail: () => { state.entities = 'error'; },
    emptyText: 'No entities found for this type.',
    errorText: 'Entities unavailable',
  },
  {
    route: '/entities/human/entity-local',
    routePattern: '/entities/:type/:id',
    Page: EntitiesPage,
    empty: () => { state.profile = 'empty'; },
    fail: () => { state.profile = 'error'; },
    emptyText: 'Profile not found',
    errorText: 'Profile360 failed to load',
  },
  {
    route: '/profile360/human/entity-local',
    routePattern: '/profile360/:type/:id',
    Page: Profile360Page,
    empty: () => { state.profile = 'empty'; },
    fail: () => { state.profile = 'error'; },
    emptyText: 'Profile not found',
    errorText: 'Profile360 failed to load',
  },
  {
    route: '/live',
    Page: LivePage,
    empty: () => { state.live = 'empty'; },
    fail: () => { state.live = 'error'; },
    emptyText: 'No events match filters',
    errorText: 'Events unavailable',
  },
  {
    route: '/command',
    Page: CommandPage,
    empty: () => { state.command = 'empty'; },
    fail: () => { state.command = 'error'; },
    emptyText: 'No blocked items',
    errorText: 'Command data unavailable',
    enterEmptySurface: async () => { await userEvent.click(await screen.findByRole('tab', { name: 'Blocked' })); },
  },
  {
    route: '/diagnostics',
    Page: DiagnosticsPage,
    empty: () => { state.diagnostics = 'empty'; },
    fail: () => { state.diagnostics = 'error'; },
    emptyText: 'No diagnostics data available.',
    errorText: 'diagnostics backend offline',
  },
  ...([
    ['/review', '/review'],
    ['/review/batch-local', '/review/:batchId'],
  ] as const).map(([route, routePattern]): RouteStateCase => ({
    route,
    routePattern,
    Page: ReviewPage,
    empty: () => { state.review = 'empty'; },
    fail: () => { state.review = 'error'; },
    emptyText: 'No Batch Selected',
    errorText: 'review backend offline',
  })),
  {
    route: '/tenants',
    Page: TenantsPage,
    empty: () => { state.query = 'empty'; },
    fail: () => { state.query = 'error'; },
    emptyText: 'No tenants found',
    errorText: 'Tenant registry unavailable',
  },
  {
    route: '/tenants/tenant-local',
    routePattern: '/tenants/:tenantId',
    Page: TenantsPage,
    empty: () => { state.query = 'empty'; },
    fail: () => { state.query = 'error'; },
    emptyText: 'Tenant not found',
    errorText: 'Tenant unavailable',
  },
  {
    route: '/imports/import-local',
    routePattern: '/imports/:importId',
    Page: ImportOpsDetailPage,
    empty: () => { state.query = 'empty'; },
    fail: () => { state.query = 'error'; },
    emptyText: 'Import not found',
    errorText: 'Failed to load import',
  },
  {
    route: '/cis',
    Page: CisPage,
    empty: () => { state.query = 'empty'; },
    fail: () => { state.query = 'error'; },
    emptyText: 'No mutations',
    errorText: 'CIS health unavailable',
    enterEmptySurface: async () => { await userEvent.click(await screen.findByRole('button', { name: 'Mutations' })); },
  },
  {
    route: '/cis/forensics/node-local',
    routePattern: '/cis/forensics/:nodeId',
    Page: CisPage,
    empty: () => { state.query = 'empty'; },
    fail: () => { state.query = 'error'; },
    emptyText: 'Node not found',
    errorText: 'CIS forensics unavailable',
  },
  {
    route: '/investigations',
    Page: InvestigationsPage,
    empty: () => { state.query = 'empty'; },
    fail: () => { state.query = 'error'; },
    emptyText: 'No investigations',
    errorText: 'Investigations unavailable',
  },
  {
    route: '/investigations/case-local',
    routePattern: '/investigations/:caseId',
    Page: InvestigationsPage,
    empty: () => { state.query = 'empty'; },
    fail: () => { state.query = 'error'; },
    emptyText: 'Case not found',
    errorText: 'Investigation unavailable',
  },
  {
    route: '/reliability',
    Page: ReliabilityPage,
    empty: () => { state.reliability = 'empty'; },
    fail: () => { state.reliability = 'error'; },
    emptyText: 'No incidents',
    errorText: 'Unable to load reliability data',
    enterEmptySurface: async () => { await userEvent.click(await screen.findByRole('tab', { name: 'Incidents' })); },
  },
  {
    route: '/reliability/incidents/incident-local',
    routePattern: '/reliability/incidents/:incidentId',
    Page: ReliabilityPage,
    empty: () => { state.reliability = 'empty'; },
    fail: () => { state.reliability = 'error'; },
    emptyText: 'No incidents',
    errorText: 'Unable to load reliability data',
    enterEmptySurface: async () => { await userEvent.click(await screen.findByRole('tab', { name: 'Incidents' })); },
  },
  {
    route: '/intelligence-quality',
    Page: IntelligenceQualityPage,
    empty: () => { state.intelligence = 'empty'; },
    fail: () => { state.intelligence = 'error'; },
    emptyText: 'No dimensions',
    errorText: 'Unable to load intelligence quality data',
    enterEmptySurface: async () => { await userEvent.click(await screen.findByRole('tab', { name: 'Dimensions' })); },
  },
  {
    route: '/connectors',
    Page: ConnectorsPage,
    empty: () => mocks.connectorsOverview.mockResolvedValue({
      enabled_by_type: {}, enabled_by_status: {}, by_type_detail: [],
    }),
    fail: () => mocks.connectorsOverview.mockRejectedValue(new Error('connectors backend offline')),
    emptyText: 'No enabled connectors',
    errorText: 'Unable to load connector health',
  },
  {
    route: '/security',
    Page: SecurityPage,
    empty: () => {
      mocks.securityOverview.mockResolvedValue({});
      mocks.securityPolicyDecisions.mockResolvedValue({ items: [] });
      mocks.securityAuditEvents.mockResolvedValue({ items: [] });
      mocks.securityTenantIsolation.mockResolvedValue({ checks: [] });
      mocks.securityOperatorAccess.mockResolvedValue({});
      mocks.securityBreakGlassList.mockResolvedValue({ items: [] });
      mocks.securityDataRetention.mockResolvedValue({ items: [] });
      mocks.securityDataRequests.mockResolvedValue({ items: [] });
      mocks.securityEvidencePacks.mockResolvedValue({ items: [] });
    },
    fail: () => {
      mocks.securityOverview.mockRejectedValue(new Error('security backend offline'));
      mocks.securityPolicyDecisions.mockResolvedValue({ items: [] });
      mocks.securityAuditEvents.mockResolvedValue({ items: [] });
      mocks.securityTenantIsolation.mockResolvedValue({ checks: [] });
      mocks.securityOperatorAccess.mockResolvedValue({});
      mocks.securityBreakGlassList.mockResolvedValue({ items: [] });
      mocks.securityDataRetention.mockResolvedValue({ items: [] });
      mocks.securityDataRequests.mockResolvedValue({ items: [] });
      mocks.securityEvidencePacks.mockResolvedValue({ items: [] });
    },
    emptyText: 'No policy decisions yet',
    errorText: 'Unable to load security data',
    enterEmptySurface: async () => { await userEvent.click(await screen.findByRole('tab', { name: 'Policy Decision Log' })); },
  },
  ...([
    ['/security/workforce', WorkforcePage, 'No operators'],
    ['/security/invitations', InvitationsPage, 'No invitations'],
    ['/security/roles', RolesPage, 'No role templates in use'],
    ['/security/devices', DevicesPage, 'No devices registered'],
    ['/security/sessions', SessionsPage, 'No active session'],
    ['/security/access', AccessPage, 'No scope history'],
    ['/security/audit', AuditPage, 'No audit events'],
  ] as const).map(([route, Page, emptyText]): RouteStateCase => ({
    route,
    Page,
    empty: () => { state.securityChild = 'empty'; },
    fail: () => { state.securityChild = 'error'; },
    emptyText,
    errorText: 'security backend offline',
  })),
];

describe('Kyber page route-state family', () => {
  beforeEach(() => {
    Object.values(mocks).forEach(mock => mock.mockReset());
    state.connectors = 'empty';
    state.command = 'empty';
    state.diagnostics = 'empty';
    state.entities = 'empty';
    state.intelligence = 'empty';
    state.live = 'empty';
    state.mission = 'empty';
    state.profile = 'empty';
    state.query = 'empty';
    state.reliability = 'empty';
    state.review = 'empty';
    state.security = 'empty';
    state.securityChild = 'empty';
  });

  it.each(cases)('$route renders successful empty from a successful provider response', async ({
    Page, route, routePattern, empty, emptyText, errorText, enterEmptySurface,
  }) => {
    empty();
    renderRoute(Page, route, routePattern);
    if (enterEmptySurface) await enterEmptySurface();
    expect(await screen.findByText(emptyText)).toBeInTheDocument();
    expect(screen.queryByText(errorText)).not.toBeInTheDocument();
  });

  it.each(cases)('$route renders unavailable and not the successful empty state', async ({
    Page, route, routePattern, fail, errorText, emptyText,
  }) => {
    fail();
    renderRoute(Page, route, routePattern);
    expect(await screen.findByText(errorText)).toBeInTheDocument();
    expect(screen.queryByText(emptyText)).not.toBeInTheDocument();
  });
});
