/**
 * E2E-only host for the identity continuity components. These surfaces are
 * not registered in the production router yet, so this page mounts the real
 * components with the real auth/query/API clients while keeping the fixture
 * host out of the tenant navigation and production entrypoint.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider, RequireAuth } from '@aether-app/features/auth';
import {
  IdentityReviewQueue,
  Profile360IdentityPanel,
  TenantActivationDashboard,
} from '@aether-app/features/identity';
import { ThemeProvider } from '@aether/ui';
import '@aether-app/styles/index.css';

function HarnessSurface() {
  const surface = new URLSearchParams(window.location.search).get('surface');
  if (surface === 'review-queue') return <IdentityReviewQueue />;
  if (surface === 'profile') {
    return (
      <RequireAuth>
        <Profile360IdentityPanel userId="profile-import-sdk-late-binding" />
      </RequireAuth>
    );
  }
  return <TenantActivationDashboard />;
}

const root = document.getElementById('root');
if (!root) throw new Error('Identity continuity E2E root is missing');

createRoot(root).render(
  <StrictMode>
    <ThemeProvider storageKey="aether-identity-e2e-theme" defaultTheme="dark">
      <BrowserRouter>
        <AuthProvider>
          <HarnessSurface />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
);
