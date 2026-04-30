import { Routes, Route, Navigate } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { RequireAuth } from '@kyber/features/auth';
import { AppShell } from '@kyber/components/layout';
import { LoadingState } from '@kyber/components/system';
import { ErrorBoundary } from './error-boundary';

const MissionPage = lazy(() => import('@kyber/pages/mission').then(m => ({ default: m.MissionPage })));
const LivePage = lazy(() => import('@kyber/pages/live').then(m => ({ default: m.LivePage })));
const NoesisPage = lazy(() => import('@kyber/pages/noesis').then(m => ({ default: m.NoesisPage })));
const EntitiesPage = lazy(() => import('@kyber/pages/entities').then(m => ({ default: m.EntitiesPage })));
const CommandPage = lazy(() => import('@kyber/pages/command').then(m => ({ default: m.CommandPage })));
const DiagnosticsPage = lazy(() => import('@kyber/pages/diagnostics').then(m => ({ default: m.DiagnosticsPage })));
const ReviewPage = lazy(() => import('@kyber/pages/review').then(m => ({ default: m.ReviewPage })));
const LabPage = lazy(() => import('@kyber/pages/lab').then(m => ({ default: m.LabPage })));

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
    <RequireAuth>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to="/mission" replace />} />
          <Route path="/mission" element={<PageSuspense><MissionPage /></PageSuspense>} />
          <Route path="/live" element={<PageSuspense><LivePage /></PageSuspense>} />
          <Route path="/noesis" element={<PageSuspense><NoesisPage /></PageSuspense>} />
          <Route path="/entities" element={<PageSuspense><EntitiesPage /></PageSuspense>} />
          <Route path="/entities/:type/:id" element={<PageSuspense><EntitiesPage /></PageSuspense>} />
          <Route path="/command" element={<PageSuspense><CommandPage /></PageSuspense>} />
          <Route path="/diagnostics" element={<PageSuspense><DiagnosticsPage /></PageSuspense>} />
          <Route path="/review" element={<PageSuspense><ReviewPage /></PageSuspense>} />
          <Route path="/review/:batchId" element={<PageSuspense><ReviewPage /></PageSuspense>} />
          <Route path="/lab" element={<PageSuspense><LabPage /></PageSuspense>} />
          <Route path="*" element={<Navigate to="/mission" replace />} />
        </Routes>
      </AppShell>
    </RequireAuth>
  );
}
