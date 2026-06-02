import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { LoadingState } from '@aether/ui';
import { RequireAuth } from '@aether-app/features/auth';
import { AppShell } from '@aether-app/components/app-shell';
import { CallbackPage } from '@aether-app/pages/callback';
import { LoginPage } from '@aether-app/pages/login/login-page';
import { DataRetentionPage } from '@aether-app/pages/legal/data-retention-page';
import { ErrorBoundary } from './error-boundary';

const SignupPage = lazy(() => import('@aether-app/pages/signup/signup-page').then(m => ({ default: m.SignupPage })));
const UsersPage = lazy(() => import('@aether-app/pages/users').then(m => ({ default: m.UsersPage })));
const UserProfilePage = lazy(() => import('@aether-app/pages/user-profile').then(m => ({ default: m.UserProfilePage })));
const CampaignsPage = lazy(() => import('@aether-app/pages/campaigns').then(m => ({ default: m.CampaignsPage })));
const GraphPage = lazy(() => import('@aether-app/pages/graph').then(m => ({ default: m.GraphPage })));
const SettingsPage = lazy(() => import('@aether-app/pages/settings/settings-page').then(m => ({ default: m.SettingsPage })));
const BillingPage = lazy(() => import('@aether-app/pages/billing/billing-page').then(m => ({ default: m.BillingPage })));
const UsagePlanPage = lazy(() => import('@aether-app/pages/usage-plan').then(m => ({ default: m.UsagePlanPage })));
const MePage = lazy(() => import('@aether-app/pages/me/me-page').then(m => ({ default: m.MePage })));
const GeoPage = lazy(() => import('@aether-app/pages/geo').then(m => ({ default: m.GeoPage })));
const OnboardingPage = lazy(() => import('@aether-app/pages/onboarding').then(m => ({ default: m.OnboardingPage })));
const AuditExportsPage = lazy(() => import('@aether-app/pages/audit-exports').then(m => ({ default: m.AuditExportsPage })));
const ValueReviewPage = lazy(() => import('@aether-app/pages/value-review').then(m => ({ default: m.ValueReviewPage })));
const SecurityPage = lazy(() => import('@aether-app/pages/security').then(m => ({ default: m.SecurityPage })));

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
      {/* Auth callback — outside RequireAuth */}
      <Route path="/callback" element={<CallbackPage />} />

      {/* Public auth routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/signup"
        element={
          <PageSuspense>
            <SignupPage />
          </PageSuspense>
        }
      />

      {/* Public legal pages */}
      <Route path="/legal/data-retention" element={<DataRetentionPage />} />

      {/* All authenticated routes */}
      <Route
        path="*"
        element={
          <RequireAuth>
            <AppShell>
              <Routes>
                <Route path="/" element={<Navigate to="/settings" replace />} />
                <Route path="/users" element={<PageSuspense><UsersPage /></PageSuspense>} />
                <Route path="/users/:id" element={<PageSuspense><UserProfilePage /></PageSuspense>} />
                <Route path="/campaigns" element={<PageSuspense><CampaignsPage /></PageSuspense>} />
                <Route path="/graph" element={<PageSuspense><GraphPage /></PageSuspense>} />
                <Route path="/settings" element={<PageSuspense><SettingsPage /></PageSuspense>} />
                <Route path="/onboarding" element={<PageSuspense><OnboardingPage /></PageSuspense>} />
                <Route path="/billing" element={<PageSuspense><BillingPage /></PageSuspense>} />
                <Route path="/usage-plan" element={<PageSuspense><UsagePlanPage /></PageSuspense>} />
                <Route path="/me" element={<PageSuspense><MePage /></PageSuspense>} />
                <Route path="/geo" element={<PageSuspense><GeoPage /></PageSuspense>} />
                <Route path="/geo/:level/:geoId" element={<PageSuspense><GeoPage /></PageSuspense>} />
                <Route path="/audit-exports" element={<PageSuspense><AuditExportsPage /></PageSuspense>} />
                <Route path="/value-review" element={<PageSuspense><ValueReviewPage /></PageSuspense>} />
                <Route path="/security" element={<PageSuspense><SecurityPage /></PageSuspense>} />
                <Route path="*" element={<Navigate to="/settings" replace />} />
              </Routes>
            </AppShell>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
