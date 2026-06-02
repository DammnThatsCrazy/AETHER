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
                <Route path="/pricing-architecture" element={<PageSuspense><PricingArchitecturePage /></PageSuspense>} />
                <Route path="/gtm-materials" element={<PageSuspense><GTMMaterialsPage /></PageSuspense>} />
                <Route path="/buyer-personas" element={<PageSuspense><BuyerPersonasPage /></PageSuspense>} />
                <Route path="/roi-calculators" element={<PageSuspense><ROICalculatorsPage /></PageSuspense>} />
                <Route path="/sales-readiness" element={<PageSuspense><SalesReadinessPage /></PageSuspense>} />
                <Route path="*" element={<Navigate to="/mission" replace />} />
              </Routes>
            </AppShell>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
