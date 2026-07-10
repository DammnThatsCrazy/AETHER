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
const CampaignDetail360Page = lazy(() => import('@aether-app/pages/campaigns/campaign-360-page').then(m => ({ default: m.Campaign360Page })));
const CampaignRegistryPage = lazy(() => import('@aether-app/pages/campaigns/campaign-registry-page').then(m => ({ default: m.CampaignRegistryPage })));
const CampaignSourcesPage = lazy(() => import('@aether-app/pages/campaigns/campaign-sources-page').then(m => ({ default: m.CampaignSourcesPage })));
const MappingReviewPage = lazy(() => import('@aether-app/pages/campaigns/mapping-review-page').then(m => ({ default: m.MappingReviewPage })));
const CampaignQualityPage = lazy(() => import('@aether-app/pages/campaigns/campaign-quality-page').then(m => ({ default: m.CampaignQualityPage })));
const CustomCampaignPage = lazy(() => import('@aether-app/pages/campaigns/custom-campaign-page').then(m => ({ default: m.CustomCampaignPage })));
const GraphPage = lazy(() => import('@aether-app/pages/graph').then(m => ({ default: m.GraphPage })));
const NoesisPage = lazy(() => import('@aether-app/pages/noesis').then(m => ({ default: m.NoesisPage })));
const SettingsPage = lazy(() => import('@aether-app/pages/settings/settings-page').then(m => ({ default: m.SettingsPage })));
const BillingPage = lazy(() => import('@aether-app/pages/billing/billing-page').then(m => ({ default: m.BillingPage })));
const UsagePlanPage = lazy(() => import('@aether-app/pages/usage-plan').then(m => ({ default: m.UsagePlanPage })));
const MePage = lazy(() => import('@aether-app/pages/me/me-page').then(m => ({ default: m.MePage })));
const GeoPage = lazy(() => import('@aether-app/pages/geo').then(m => ({ default: m.GeoPage })));
const OnboardingPage = lazy(() => import('@aether-app/pages/onboarding').then(m => ({ default: m.OnboardingPage })));
const AuditExportsPage = lazy(() => import('@aether-app/pages/audit-exports').then(m => ({ default: m.AuditExportsPage })));
const ValueReviewPage = lazy(() => import('@aether-app/pages/value-review').then(m => ({ default: m.ValueReviewPage })));
const SecurityPage = lazy(() => import('@aether-app/pages/security').then(m => ({ default: m.SecurityPage })));
const SystemStatusPage = lazy(() => import('@aether-app/pages/system-status').then(m => ({ default: m.SystemStatusPage })));
const DataQualityPage = lazy(() => import('@aether-app/pages/data-quality').then(m => ({ default: m.DataQualityPage })));
const ConnectorsPage = lazy(() => import('@aether-app/pages/connectors').then(m => ({ default: m.ConnectorsPage })));
const RewardDecisionsPage = lazy(() => import('@aether-app/pages/rewards').then(m => ({ default: m.RewardDecisionsPage })));
const RewardApprovalQueuePage = lazy(() => import('@aether-app/pages/rewards').then(m => ({ default: m.RewardApprovalQueuePage })));
const RewardRailSetupPage = lazy(() => import('@aether-app/pages/rewards').then(m => ({ default: m.RewardRailSetupPage })));
const CampaignBuilderPage = lazy(() => import('@aether-app/pages/rewards').then(m => ({ default: m.CampaignBuilderPage })));
const SuggestionsPage = lazy(() => import('@aether-app/pages/suggestions').then(m => ({ default: m.SuggestionsPage })));
const Cluster360Page = lazy(() => import('@aether-app/pages/cluster360').then(m => ({ default: m.Cluster360Page })));
const DeliveryHistoryPage = lazy(() => import('@aether-app/pages/connectors').then(m => ({ default: m.DeliveryHistoryPage })));
const StablecoinsPage = lazy(() => import('@aether-app/pages/stablecoins').then(m => ({ default: m.StablecoinsPage })));
const StablecoinAssetPage = lazy(() => import('@aether-app/pages/stablecoins').then(m => ({ default: m.StablecoinAssetPage })));
const DerivativesPage = lazy(() => import('@aether-app/pages/derivatives').then(m => ({ default: m.DerivativesPage })));
const DerivativesAccountPage = lazy(() => import('@aether-app/pages/derivatives').then(m => ({ default: m.DerivativesAccountPage })));
const InteropPage = lazy(() => import('@aether-app/pages/interop').then(m => ({ default: m.InteropPage })));
const InteropMessagePage = lazy(() => import('@aether-app/pages/interop').then(m => ({ default: m.InteropMessagePage })));

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
                <Route path="/campaigns/:id" element={<PageSuspense><CampaignDetail360Page /></PageSuspense>} />
                {/* Campaign Intelligence */}
                <Route path="/campaign-intelligence" element={<PageSuspense><CampaignsPage /></PageSuspense>} />
                <Route path="/campaign-intelligence/registry" element={<PageSuspense><CampaignRegistryPage /></PageSuspense>} />
                <Route path="/campaign-intelligence/sources" element={<PageSuspense><CampaignSourcesPage /></PageSuspense>} />
                <Route path="/campaign-intelligence/mapping-review" element={<PageSuspense><MappingReviewPage /></PageSuspense>} />
                <Route path="/campaign-intelligence/quality" element={<PageSuspense><CampaignQualityPage /></PageSuspense>} />
                <Route path="/campaign-intelligence/campaigns/new" element={<PageSuspense><CustomCampaignPage /></PageSuspense>} />
                <Route path="/graph" element={<PageSuspense><GraphPage /></PageSuspense>} />
                <Route path="/noesis" element={<PageSuspense><NoesisPage /></PageSuspense>} />
                <Route path="/settings" element={<PageSuspense><SettingsPage /></PageSuspense>} />
                <Route path="/settings/notifications" element={<PageSuspense><SettingsPage /></PageSuspense>} />
                <Route path="/onboarding" element={<PageSuspense><OnboardingPage /></PageSuspense>} />
                <Route path="/billing" element={<PageSuspense><BillingPage /></PageSuspense>} />
                <Route path="/usage-plan" element={<PageSuspense><UsagePlanPage /></PageSuspense>} />
                <Route path="/me" element={<PageSuspense><MePage /></PageSuspense>} />
                <Route path="/geo" element={<PageSuspense><GeoPage /></PageSuspense>} />
                <Route path="/geo/:level/:geoId" element={<PageSuspense><GeoPage /></PageSuspense>} />
                <Route path="/audit-exports" element={<PageSuspense><AuditExportsPage /></PageSuspense>} />
                <Route path="/value-review" element={<PageSuspense><ValueReviewPage /></PageSuspense>} />
                <Route path="/security" element={<PageSuspense><SecurityPage /></PageSuspense>} />
                <Route path="/system-status" element={<PageSuspense><SystemStatusPage /></PageSuspense>} />
                <Route path="/data-quality" element={<PageSuspense><DataQualityPage /></PageSuspense>} />
                <Route path="/integrations" element={<PageSuspense><ConnectorsPage /></PageSuspense>} />
                <Route path="/rewards" element={<PageSuspense><RewardDecisionsPage /></PageSuspense>} />
                <Route path="/rewards/decisions" element={<PageSuspense><RewardDecisionsPage /></PageSuspense>} />
                <Route path="/rewards/approval-queue" element={<PageSuspense><RewardApprovalQueuePage /></PageSuspense>} />
                <Route path="/rewards/rails" element={<PageSuspense><RewardRailSetupPage /></PageSuspense>} />
                <Route path="/rewards/campaigns/new" element={<PageSuspense><CampaignBuilderPage /></PageSuspense>} />
                <Route path="/suggestions" element={<PageSuspense><SuggestionsPage /></PageSuspense>} />
                <Route path="/clusters/:clusterId" element={<PageSuspense><Cluster360Page /></PageSuspense>} />
                <Route path="/delivery" element={<PageSuspense><DeliveryHistoryPage /></PageSuspense>} />
                <Route path="/stablecoins" element={<PageSuspense><StablecoinsPage /></PageSuspense>} />
                <Route path="/stablecoins/:assetId" element={<PageSuspense><StablecoinAssetPage /></PageSuspense>} />
                <Route path="/derivatives" element={<PageSuspense><DerivativesPage /></PageSuspense>} />
                <Route path="/derivatives/accounts/:accountId" element={<PageSuspense><DerivativesAccountPage /></PageSuspense>} />
                <Route path="/interoperability" element={<PageSuspense><InteropPage /></PageSuspense>} />
                <Route path="/interoperability/messages/:messageId" element={<PageSuspense><InteropMessagePage /></PageSuspense>} />
                <Route path="*" element={<Navigate to="/settings" replace />} />
              </Routes>
            </AppShell>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
