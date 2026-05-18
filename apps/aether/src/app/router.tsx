import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { LoadingState } from '@aether/ui';
import { RequireAuth } from '@aether-app/features/auth';
import { AppShell } from '@aether-app/components/app-shell';
import { ErrorBoundary } from './error-boundary';
import { PlaceholderPage } from '@aether-app/pages/shared/placeholder-page';

// ── Lazy-loaded pages ────────────────────────────────────────────
const FeedPage           = lazy(() => import('@aether-app/pages/feed/feed-page').then(m => ({ default: m.FeedPage })));
const GraphWorkspacePage = lazy(() => import('@aether-app/pages/graph/graph-workspace-page').then(m => ({ default: m.GraphWorkspacePage })));
const EntitiesPage       = lazy(() => import('@aether-app/pages/entities/entities-page').then(m => ({ default: m.EntitiesPage })));
const EntityOverviewPage = lazy(() => import('@aether-app/pages/entities/entity-overview-page').then(m => ({ default: m.EntityOverviewPage })));
const JourneysPage       = lazy(() => import('@aether-app/pages/journeys/journeys-page').then(m => ({ default: m.JourneysPage })));
const ClustersPage       = lazy(() => import('@aether-app/pages/clusters/clusters-page').then(m => ({ default: m.ClustersPage })));
const InvestigationsPage = lazy(() => import('@aether-app/pages/investigations/investigations-page').then(m => ({ default: m.InvestigationsPage })));
const InvestigationWS    = lazy(() => import('@aether-app/pages/investigations/investigation-workspace-page').then(m => ({ default: m.InvestigationWorkspacePage })));
const GovernancePage     = lazy(() => import('@aether-app/pages/governance/governance-page').then(m => ({ default: m.GovernancePage })));
const AlertsPage         = lazy(() => import('@aether-app/pages/alerts/alerts-page').then(m => ({ default: m.AlertsPage })));
const MonitoringPage     = lazy(() => import('@aether-app/pages/monitoring/monitoring-page').then(m => ({ default: m.MonitoringPage })));
const DeveloperPage      = lazy(() => import('@aether-app/pages/developer/developer-page').then(m => ({ default: m.DeveloperPage })));
const SettingsPage       = lazy(() => import('@aether-app/pages/settings/settings-page').then(m => ({ default: m.SettingsPage })));

function PageSuspense({ children }: { readonly children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={
        <div className="flex items-center justify-center h-full p-12">
          <LoadingState lines={5} className="w-80" />
        </div>
      }>
        {children}
      </Suspense>
    </ErrorBoundary>
  );
}

// ── Inline placeholder factory ───────────────────────────────────
const P = (title: string, glyph = '◎', eyebrow = '', subtitle = '') => () => (
  <PlaceholderPage glyph={glyph} title={title} eyebrow={eyebrow} subtitle={subtitle} />
);

const DevicesPage       = P('Device Intelligence',    '⊡', 'Intelligence Surface', 'Device fingerprint, continuity, and behavioral analysis');
const DeviceDetailPage  = P('Device Profile',         '⊡', 'Device');
const WalletsPage       = P('Wallet Intelligence',    '⟐', 'Intelligence Surface', 'Wallet relationship and on-chain intelligence');
const WalletDetailPage  = P('Wallet Profile',         '⟐', 'Wallet');
const AgentsPage        = P('Agent Intelligence',     '⚙', 'Intelligence Surface', 'AI agent coordination and governance');
const AgentDetailPage   = P('Agent Profile',          '⚙', 'Agent');
const GeoPage           = P('Geographic Intelligence','◎', 'Intelligence Surface', 'Spatial density and operational zone analysis');
const EconomicPage      = P('Economic Intelligence',  '≈', 'Intelligence Surface', 'Revenue attribution, LTV, and economic clusters');
const Web3Page          = P('Web3 Intelligence',      '⟨⟩','Intelligence Surface', 'On-chain wallet, bridge, and protocol intelligence');
const AuditPage         = P('Audit Center',           '✓', 'Governance', 'Complete immutable audit trail and chain of custody');
const PoliciesPage      = P('Policy Management',      '≡', 'Governance', 'Policy authoring, versioning, and enforcement');
const ConsentPage       = P('Consent Management',     '◧', 'Governance', 'Entity consent status and scope management');
const RbacPage          = P('Access Control',         '⚿', 'Governance', 'RBAC and ABAC administration');
const ReportsPage       = P('Reports',                '⊟', 'Operations', 'Intelligence reports and scheduled exports');
const ReportBuilderPage = P('Report Builder',         '⊟', 'Reports');
const JourneyDetailPage = P('Journey Detail',         '↝', 'Journey Intelligence');
const ClusterDetailPage = P('Cluster Detail',         '◈', 'Cluster Intelligence');
const AlertDetailPage   = P('Alert Detail',           '△', 'Alert');

export function AppRouter() {
  return (
    <RequireAuth>
      <AppShell>
        <Routes>
          {/* Default */}
          <Route path="/" element={<Navigate to="/feed" replace />} />

          {/* Intelligence Feed */}
          <Route path="/feed" element={<PageSuspense><FeedPage /></PageSuspense>} />

          {/* Graph Workspace */}
          <Route path="/graph" element={<PageSuspense><GraphWorkspacePage /></PageSuspense>} />

          {/* Entity Intelligence */}
          <Route path="/entities"     element={<PageSuspense><EntitiesPage /></PageSuspense>} />
          <Route path="/entities/:id" element={<PageSuspense><EntityOverviewPage /></PageSuspense>} />

          {/* Device Intelligence */}
          <Route path="/devices"     element={<PageSuspense><DevicesPage /></PageSuspense>} />
          <Route path="/devices/:id" element={<PageSuspense><DeviceDetailPage /></PageSuspense>} />

          {/* Wallet Intelligence */}
          <Route path="/wallets"     element={<PageSuspense><WalletsPage /></PageSuspense>} />
          <Route path="/wallets/:id" element={<PageSuspense><WalletDetailPage /></PageSuspense>} />

          {/* Agent Intelligence */}
          <Route path="/agents"     element={<PageSuspense><AgentsPage /></PageSuspense>} />
          <Route path="/agents/:id" element={<PageSuspense><AgentDetailPage /></PageSuspense>} />

          {/* Journey Intelligence */}
          <Route path="/journeys"     element={<PageSuspense><JourneysPage /></PageSuspense>} />
          <Route path="/journeys/:id" element={<PageSuspense><JourneyDetailPage /></PageSuspense>} />

          {/* Cluster Intelligence */}
          <Route path="/clusters"     element={<PageSuspense><ClustersPage /></PageSuspense>} />
          <Route path="/clusters/:id" element={<PageSuspense><ClusterDetailPage /></PageSuspense>} />

          {/* Spatial Intelligence */}
          <Route path="/geo"      element={<PageSuspense><GeoPage /></PageSuspense>} />
          <Route path="/economic" element={<PageSuspense><EconomicPage /></PageSuspense>} />
          <Route path="/web3"     element={<PageSuspense><Web3Page /></PageSuspense>} />

          {/* Investigations */}
          <Route path="/investigations"     element={<PageSuspense><InvestigationsPage /></PageSuspense>} />
          <Route path="/investigations/new" element={<PageSuspense><InvestigationWS /></PageSuspense>} />
          <Route path="/investigations/:id" element={<PageSuspense><InvestigationWS /></PageSuspense>} />

          {/* Governance */}
          <Route path="/governance" element={<PageSuspense><GovernancePage /></PageSuspense>} />
          <Route path="/audit"      element={<PageSuspense><AuditPage /></PageSuspense>} />
          <Route path="/policies"   element={<PageSuspense><PoliciesPage /></PageSuspense>} />
          <Route path="/consent"    element={<PageSuspense><ConsentPage /></PageSuspense>} />
          <Route path="/rbac"       element={<PageSuspense><RbacPage /></PageSuspense>} />

          {/* Operations */}
          <Route path="/alerts"     element={<PageSuspense><AlertsPage /></PageSuspense>} />
          <Route path="/alerts/:id" element={<PageSuspense><AlertDetailPage /></PageSuspense>} />
          <Route path="/monitoring" element={<PageSuspense><MonitoringPage /></PageSuspense>} />

          {/* Reports */}
          <Route path="/reports"         element={<PageSuspense><ReportsPage /></PageSuspense>} />
          <Route path="/reports/builder" element={<PageSuspense><ReportBuilderPage /></PageSuspense>} />

          {/* Developer */}
          <Route path="/developer"             element={<PageSuspense><DeveloperPage /></PageSuspense>} />
          <Route path="/developer/api-console" element={<PageSuspense><DeveloperPage /></PageSuspense>} />
          <Route path="/developer/sdk"         element={<PageSuspense><DeveloperPage /></PageSuspense>} />
          <Route path="/developer/webhooks"    element={<PageSuspense><DeveloperPage /></PageSuspense>} />
          <Route path="/developer/query"       element={<PageSuspense><DeveloperPage /></PageSuspense>} />

          {/* Settings */}
          <Route path="/settings"              element={<PageSuspense><SettingsPage /></PageSuspense>} />
          <Route path="/settings/team"         element={<PageSuspense><SettingsPage /></PageSuspense>} />
          <Route path="/settings/security"     element={<PageSuspense><SettingsPage /></PageSuspense>} />
          <Route path="/settings/deployment"   element={<PageSuspense><SettingsPage /></PageSuspense>} />
          <Route path="/settings/integrations" element={<PageSuspense><SettingsPage /></PageSuspense>} />

          {/* Legacy compat */}
          <Route path="/users"     element={<Navigate to="/entities" replace />} />
          <Route path="/users/:id" element={<Navigate to="/entities" replace />} />
          <Route path="/campaigns" element={<Navigate to="/feed" replace />} />

          {/* Catch-all */}
          <Route path="*" element={<Navigate to="/feed" replace />} />
        </Routes>
      </AppShell>
    </RequireAuth>
  );
}
