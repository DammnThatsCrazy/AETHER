import { Routes, Route, Navigate } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { RequireAuth } from '@kyber/features/auth';
import { AppShell } from '@kyber/components/layout';
import { LoadingState } from '@aether/ui';
import { CallbackPage } from '@kyber/pages/callback';
import { ErrorBoundary } from './error-boundary';

const MissionPage = lazy(() => import('@kyber/pages/mission').then(m => ({ default: m.MissionPage })));
const LivePage = lazy(() => import('@kyber/pages/live').then(m => ({ default: m.LivePage })));
const NoesisPage = lazy(() => import('@kyber/pages/noesis').then(m => ({ default: m.NoesisPage })));
const NoesisGraphExplorerPage = lazy(() => import('@kyber/pages/noesis').then(m => ({ default: m.NoesisGraphExplorerPage })));
const EntitiesPage = lazy(() => import('@kyber/pages/entities').then(m => ({ default: m.EntitiesPage })));
const CommandPage = lazy(() => import('@kyber/pages/command').then(m => ({ default: m.CommandPage })));
const DiagnosticsPage = lazy(() => import('@kyber/pages/diagnostics').then(m => ({ default: m.DiagnosticsPage })));
const ReviewPage = lazy(() => import('@kyber/pages/review').then(m => ({ default: m.ReviewPage })));
const LabPage = lazy(() => import('@kyber/pages/lab').then(m => ({ default: m.LabPage })));
const Profile360Page = lazy(() => import('@kyber/pages/profile360').then(m => ({ default: m.Profile360Page })));
const TenantsPage = lazy(() => import('@kyber/pages/tenants').then(m => ({ default: m.TenantsPage })));
const CisPage = lazy(() => import('@kyber/pages/cis').then(m => ({ default: m.CisPage })));
const InvestigationsPage = lazy(() => import('@kyber/pages/investigations').then(m => ({ default: m.InvestigationsPage })));
const SolutionPackagesPage = lazy(() => import('@kyber/pages/packages').then(m => ({ default: m.SolutionPackagesPage })));
const ImplementationPage = lazy(() => import('@kyber/pages/implementation').then(m => ({ default: m.ImplementationPage })));
const DeploymentReadinessPage = lazy(() => import('@kyber/pages/deployment-readiness').then(m => ({ default: m.DeploymentReadinessPage })));
const PricingArchitecturePage = lazy(() => import('@kyber/pages/gtm').then(m => ({ default: m.PricingArchitecturePage })));
const GTMMaterialsPage = lazy(() => import('@kyber/pages/gtm').then(m => ({ default: m.GTMMaterialsPage })));
const BuyerPersonasPage = lazy(() => import('@kyber/pages/gtm').then(m => ({ default: m.BuyerPersonasPage })));
const ROICalculatorsPage = lazy(() => import('@kyber/pages/gtm').then(m => ({ default: m.ROICalculatorsPage })));
const SalesReadinessPage = lazy(() => import('@kyber/pages/gtm').then(m => ({ default: m.SalesReadinessPage })));
const SecurityPage = lazy(() => import('@kyber/pages/security').then(m => ({ default: m.SecurityPage })));
const ReliabilityPage = lazy(() => import('@kyber/pages/reliability').then(m => ({ default: m.ReliabilityPage })));
const IntelligenceQualityPage = lazy(() => import('@kyber/pages/intelligence-quality').then(m => ({ default: m.IntelligenceQualityPage })));
const ConnectorsPage = lazy(() => import('@kyber/pages/connectors').then(m => ({ default: m.ConnectorsPage })));
const DuneFeederPage = lazy(() => import('@kyber/pages/dune-feeder').then(m => ({ default: m.DuneFeederPage })));
const RevenueOperationsPage = lazy(() => import('@kyber/pages/revenue-operations').then(m => ({ default: m.RevenueOperationsPage })));
const JourneyHealthPage = lazy(() => import('@kyber/pages/journey-health').then(m => ({ default: m.JourneyHealthPage })));
const RewardsHealthPage = lazy(() => import('@kyber/pages/rewards').then(m => ({ default: m.RewardsHealthPage })));
const RewardsDrilldownPage = lazy(() => import('@kyber/pages/rewards').then(m => ({ default: m.RewardsDrilldownPage })));
const SuggestionsPage = lazy(() => import('@kyber/pages/suggestions').then(m => ({ default: m.SuggestionsPage })));
const ReviewQueuePage = lazy(() => import('@kyber/pages/suggestions').then(m => ({ default: m.ReviewQueuePage })));
const MLAdminPage = lazy(() => import('@kyber/pages/ml').then(m => ({ default: m.MLAdminPage })));
const FraudNetworksPage = lazy(() => import('@kyber/pages/fraud/fraud-networks-page').then(m => ({ default: m.FraudNetworksPage })));
const FraudNetworkDetailPage = lazy(() => import('@kyber/pages/fraud/fraud-network-detail-page').then(m => ({ default: m.FraudNetworkDetailPage })));
const FlowTracePage = lazy(() => import('@kyber/pages/fraud/flow-trace-page').then(m => ({ default: m.FlowTracePage })));
const MeasurementOverviewPage = lazy(() => import('@kyber/pages/measurement/measurement-overview-page').then(m => ({ default: m.MeasurementOverviewPage })));
const AttributionStudioPage = lazy(() => import('@kyber/pages/measurement/attribution-studio-page').then(m => ({ default: m.AttributionStudioPage })));
const JourneyExplorerPage = lazy(() => import('@kyber/pages/measurement/journey-explorer-page').then(m => ({ default: m.JourneyExplorerPage })));
const ConversionExplorerPage = lazy(() => import('@kyber/pages/measurement/conversion-explorer-page').then(m => ({ default: m.ConversionExplorerPage })));
const CampaignIntelligencePage = lazy(() => import('@kyber/pages/measurement/campaign-intelligence-page').then(m => ({ default: m.CampaignIntelligencePage })));
const KyberMeasurementOpsPage = lazy(() => import('@kyber/pages/measurement/kyber-measurement-ops-page').then(m => ({ default: m.KyberMeasurementOpsPage })));
const Campaign360Page = lazy(() => import('@kyber/pages/measurement/campaign-360-page').then(m => ({ default: m.Campaign360Page })));

function PageSuspense({ children }: { readonly children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={<LoadingState lines={5} className="p-8" />}>
        {children}
      </Suspense>
    </ErrorBoundary>
  );
}

export function AppRouter() {
  return (
    <Routes>
      {/* Auth0 callback — outside RequireAuth so it's accessible during the login flow */}
      <Route path="/callback" element={<CallbackPage />} />

      {/* All other routes require authentication */}
      <Route
        path="*"
        element={
          <RequireAuth>
            <AppShell>
              <Routes>
                <Route path="/" element={<Navigate to="/mission" replace />} />
                <Route path="/mission" element={<PageSuspense><MissionPage /></PageSuspense>} />
                <Route path="/live" element={<PageSuspense><LivePage /></PageSuspense>} />
                <Route path="/noesis" element={<PageSuspense><NoesisPage /></PageSuspense>} />
                <Route path="/noesis/graph" element={<PageSuspense><NoesisGraphExplorerPage /></PageSuspense>} />
                <Route path="/entities" element={<PageSuspense><EntitiesPage /></PageSuspense>} />
                <Route path="/entities/:type/:id" element={<PageSuspense><EntitiesPage /></PageSuspense>} />
                <Route path="/profile360/:type/:id" element={<PageSuspense><Profile360Page /></PageSuspense>} />
                <Route path="/command" element={<PageSuspense><CommandPage /></PageSuspense>} />
                <Route path="/diagnostics" element={<PageSuspense><DiagnosticsPage /></PageSuspense>} />
                <Route path="/review" element={<PageSuspense><ReviewPage /></PageSuspense>} />
                <Route path="/review/:batchId" element={<PageSuspense><ReviewPage /></PageSuspense>} />
                <Route path="/lab" element={<PageSuspense><LabPage /></PageSuspense>} />
                <Route path="/tenants" element={<PageSuspense><TenantsPage /></PageSuspense>} />
                <Route path="/tenants/:tenantId" element={<PageSuspense><TenantsPage /></PageSuspense>} />
                <Route path="/implementation" element={<PageSuspense><ImplementationPage /></PageSuspense>} />
                <Route path="/implementation/:tenantId" element={<PageSuspense><ImplementationPage /></PageSuspense>} />
                <Route path="/cis" element={<PageSuspense><CisPage /></PageSuspense>} />
                <Route path="/cis/forensics/:nodeId" element={<PageSuspense><CisPage /></PageSuspense>} />
                <Route path="/investigations" element={<PageSuspense><InvestigationsPage /></PageSuspense>} />
                <Route path="/investigations/:caseId" element={<PageSuspense><InvestigationsPage /></PageSuspense>} />
                <Route path="/packages" element={<PageSuspense><SolutionPackagesPage /></PageSuspense>} />
                <Route path="/packages/:packageId" element={<PageSuspense><SolutionPackagesPage /></PageSuspense>} />
                <Route path="/deployment-readiness" element={<PageSuspense><DeploymentReadinessPage /></PageSuspense>} />
                <Route path="/reliability" element={<PageSuspense><ReliabilityPage /></PageSuspense>} />
                <Route path="/journey-health" element={<PageSuspense><JourneyHealthPage /></PageSuspense>} />
                <Route path="/reliability/incidents/:incidentId" element={<PageSuspense><ReliabilityPage /></PageSuspense>} />
                <Route path="/intelligence-quality" element={<PageSuspense><IntelligenceQualityPage /></PageSuspense>} />
                <Route path="/connectors" element={<PageSuspense><ConnectorsPage /></PageSuspense>} />
                <Route path="/dune-feeder" element={<PageSuspense><DuneFeederPage /></PageSuspense>} />
                <Route path="/revops" element={<PageSuspense><RevenueOperationsPage /></PageSuspense>} />
                <Route path="/pricing-architecture" element={<PageSuspense><PricingArchitecturePage /></PageSuspense>} />
                <Route path="/gtm-materials" element={<PageSuspense><GTMMaterialsPage /></PageSuspense>} />
                <Route path="/buyer-personas" element={<PageSuspense><BuyerPersonasPage /></PageSuspense>} />
                <Route path="/roi-calculators" element={<PageSuspense><ROICalculatorsPage /></PageSuspense>} />
                <Route path="/sales-readiness" element={<PageSuspense><SalesReadinessPage /></PageSuspense>} />
                <Route path="/security" element={<PageSuspense><SecurityPage /></PageSuspense>} />
                <Route path="/rewards" element={<PageSuspense><RewardsHealthPage /></PageSuspense>} />
                <Route path="/rewards/:tenantId" element={<PageSuspense><RewardsDrilldownPage /></PageSuspense>} />
                <Route path="/intelligence/suggestions" element={<PageSuspense><SuggestionsPage /></PageSuspense>} />
                <Route path="/intelligence/suggestions/review" element={<PageSuspense><ReviewQueuePage /></PageSuspense>} />
                <Route path="/ml" element={<PageSuspense><MLAdminPage /></PageSuspense>} />
                <Route path="/fraud-networks" element={<PageSuspense><FraudNetworksPage /></PageSuspense>} />
                <Route path="/fraud-networks/flow-trace" element={<PageSuspense><FlowTracePage /></PageSuspense>} />
                <Route path="/fraud-networks/flow-trace/:traceId" element={<PageSuspense><FlowTracePage /></PageSuspense>} />
                <Route path="/fraud-networks/:networkId" element={<PageSuspense><FraudNetworkDetailPage /></PageSuspense>} />
                <Route path="/measurement" element={<PageSuspense><MeasurementOverviewPage /></PageSuspense>} />
                <Route path="/measurement/attribution" element={<PageSuspense><AttributionStudioPage /></PageSuspense>} />
                <Route path="/measurement/journeys" element={<PageSuspense><JourneyExplorerPage /></PageSuspense>} />
                <Route path="/measurement/conversions" element={<PageSuspense><ConversionExplorerPage /></PageSuspense>} />
                <Route path="/measurement/campaigns" element={<PageSuspense><CampaignIntelligencePage /></PageSuspense>} />
                <Route path="/measurement/campaigns/:campaignId" element={<PageSuspense><Campaign360Page /></PageSuspense>} />
                <Route path="/measurement/ops" element={<PageSuspense><KyberMeasurementOpsPage /></PageSuspense>} />
                <Route path="*" element={<Navigate to="/mission" replace />} />
              </Routes>
            </AppShell>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
