/**
 * E2E-only host for the identity continuity components. These surfaces are
 * not registered in the production router yet, so this page mounts the real
 * components with the real auth/query/API clients while keeping the fixture
 * host out of the tenant navigation and production entrypoint.
 */
import { StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider, RequireAuth, useAuth } from '@aether-app/features/auth';
import {
  IdentityReviewQueue,
  Profile360IdentityPanel,
  TenantActivationDashboard,
} from '@aether-app/features/identity';
import { CapabilityProvider, ThemeProvider } from '@aether/ui';
import { GraphContextProvider } from '@aether/ui/exploration';
import { fetchTenantCapabilities } from '@aether-app/lib/api/capabilities';
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

/** Bind the test-only graph host to the tenant returned by the authenticated fixture. */
function HarnessGraphScope({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, user } = useAuth();
  if (isLoading) return null;
  if (!isAuthenticated || !user) return <div role="alert">Fixture authentication required</div>;
  return (
    <GraphContextProvider
      scope={{ tenant_id: user.id, workspace_id: `workspace-${user.id}`, environment_id: 'test' }}
    >
      {children}
    </GraphContextProvider>
  );
}

function HarnessCapabilities({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  return (
    <CapabilityProvider fetchCapabilities={fetchTenantCapabilities} enabled={isAuthenticated}>
      {children}
    </CapabilityProvider>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Identity continuity E2E root is missing');

createRoot(root).render(
  <StrictMode>
    <ThemeProvider storageKey="aether-identity-e2e-theme" defaultTheme="dark">
      <BrowserRouter>
        <AuthProvider>
          <HarnessCapabilities>
            <HarnessGraphScope>
              <HarnessSurface />
            </HarnessGraphScope>
          </HarnessCapabilities>
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
);
