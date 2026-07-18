import type { ReactNode } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { CapabilityProvider, ThemeProvider, TimeProvider, ToastProvider } from '@aether/ui';
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
                    <JourneyProvider>
                      {children}
                    </JourneyProvider>
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
