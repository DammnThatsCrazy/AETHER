import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { LoadingState } from '@aether/ui';
import { RequireAuth } from '@aether-app/features/auth';
import { AppShell } from '@aether-app/components/app-shell';
import { CallbackPage } from '@aether-app/pages/callback';
import { ErrorBoundary } from './error-boundary';

const UsersPage = lazy(() => import('@aether-app/pages/users').then(m => ({ default: m.UsersPage })));
const UserProfilePage = lazy(() => import('@aether-app/pages/user-profile').then(m => ({ default: m.UserProfilePage })));
const CampaignsPage = lazy(() => import('@aether-app/pages/campaigns').then(m => ({ default: m.CampaignsPage })));
const GraphPage = lazy(() => import('@aether-app/pages/graph').then(m => ({ default: m.GraphPage })));

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
                <Route path="/" element={<Navigate to="/users" replace />} />
                <Route path="/users" element={<PageSuspense><UsersPage /></PageSuspense>} />
                <Route path="/users/:id" element={<PageSuspense><UserProfilePage /></PageSuspense>} />
                <Route path="/campaigns" element={<PageSuspense><CampaignsPage /></PageSuspense>} />
                <Route path="/graph" element={<PageSuspense><GraphPage /></PageSuspense>} />
                <Route path="*" element={<Navigate to="/users" replace />} />
              </Routes>
            </AppShell>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
