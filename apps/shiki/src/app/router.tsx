import { Routes, Route, Navigate } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { RequireAuth } from '@shiki/features/auth';
import { AppShell } from '@shiki/components/layout';
import { LoadingState } from '@shiki/components/system';
import { ErrorBoundary } from './error-boundary';

const MissionPage = lazy(() => import('@shiki/pages/mission').then(m => ({ default: m.MissionPage })));
const LivePage = lazy(() => import('@shiki/pages/live').then(m => ({ default: m.LivePage })));
const GoufPage = lazy(() => import('@shiki/pages/gouf').then(m => ({ default: m.GoufPage })));
const EntitiesPage = lazy(() => import('@shiki/pages/entities').then(m => ({ default: m.EntitiesPage })));
const CommandPage = lazy(() => import('@shiki/pages/command').then(m => ({ default: m.CommandPage })));
const DiagnosticsPage = lazy(() => import('@shiki/pages/diagnostics').then(m => ({ default: m.DiagnosticsPage })));
const ReviewPage = lazy(() => import('@shiki/pages/review').then(m => ({ default: m.ReviewPage })));
const LabPage = lazy(() => import('@shiki/pages/lab').then(m => ({ default: m.LabPage })));

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
          <Route path="/gouf" element={<PageSuspense><GoufPage /></PageSuspense>} />
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
