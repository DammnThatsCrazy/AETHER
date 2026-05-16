import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { LoadingState } from '@aether/ui';
import { RequireAuth } from '@aether-app/features/auth';
import { ErrorBoundary } from './error-boundary';

const HomePage = lazy(() => import('@aether-app/pages/home').then(m => ({ default: m.HomePage })));

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
      <Routes>
        <Route path="/" element={<PageSuspense><HomePage /></PageSuspense>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </RequireAuth>
  );
}
