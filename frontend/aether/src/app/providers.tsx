import type { ReactNode } from 'react';
import { BrowserRouter, useLocation } from 'react-router-dom';
import { CapabilityProvider, ThemeProvider, TimeProvider, ToastProvider } from '@aether/ui';
import { ExplorationProvider } from '@aether/ui/exploration';
import { AuthProvider, useAuth } from '@aether-app/features/auth';
import { AetherAuth0Provider } from '@aether-app/lib/auth/auth0-provider';
import { JourneyProvider } from '@aether-app/features/journey';
import { fetchTenantCapabilities } from '@aether-app/lib/api/capabilities';
import { BUILD_INFO } from '@aether-app/lib/build-info';
import { ErrorBoundary } from './error-boundary';

interface ProvidersProps {
  readonly children: ReactNode;
}

/** Fetches the tenant capability contract once the user is authenticated. */
function CapabilityGate({ children }: { readonly children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  return (
    <CapabilityProvider
      fetchCapabilities={fetchTenantCapabilities}
      buildInfo={BUILD_INFO}
      enabled={isAuthenticated}
    >
      {children}
    </CapabilityProvider>
  );
}

/**
 * Binds the router's authoritative URL to the shared exploration store.
 *
 * The provider is deliberately created only after backend authentication has
 * established the tenant.  Its key clears all query and selection state when
 * that authority changes; tenant identity is never accepted from the URL.
 */
export function ExplorationGate({ children }: { readonly children: ReactNode }) {
  const { isAuthenticated, user } = useAuth();
  const location = useLocation();
  const tenantId = isAuthenticated ? user?.id : undefined;

  if (!tenantId) return children;

  return (
    <ExplorationProvider
      key={tenantId}
      tenantId={tenantId}
      surface={location.pathname}
      query={location.search}
    >
      {children}
    </ExplorationProvider>
  );
}

export function Providers({ children }: ProvidersProps) {
  return (
    <ErrorBoundary>
      <AetherAuth0Provider>
        <BrowserRouter>
          <ThemeProvider storageKey="aether-theme">
            <TimeProvider>
              <ToastProvider>
                <AuthProvider>
                  <CapabilityGate>
                    <ExplorationGate>
                      <JourneyProvider>
                        {children}
                      </JourneyProvider>
                    </ExplorationGate>
                  </CapabilityGate>
                </AuthProvider>
              </ToastProvider>
            </TimeProvider>
          </ThemeProvider>
        </BrowserRouter>
      </AetherAuth0Provider>
    </ErrorBoundary>
  );
}
