import type { ReactNode } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider, useAuth } from '@kyber/features/auth';
import { NotificationProvider } from '@kyber/features/notifications';
import { CapabilityProvider, ThemeProvider, TimeProvider } from '@aether/ui';
import { AetherAuth0Provider } from '@kyber/lib/auth/auth0-provider';
import { JourneyProvider } from '@kyber/features/journey';
import { fetchOperatorCapabilities } from '@kyber/lib/api/capabilities';
import { BUILD_INFO } from '@kyber/lib/build-info';
import { ErrorBoundary } from './error-boundary';

interface ProvidersProps {
  readonly children: ReactNode;
}

/** Fetches the operator capability contract once the operator is authenticated. */
function CapabilityGate({ children }: { readonly children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  return (
    <CapabilityProvider
      fetchCapabilities={fetchOperatorCapabilities}
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
          <ThemeProvider storageKey="kyber-theme">
            <TimeProvider>
              <AuthProvider>
                <CapabilityGate>
                  <JourneyProvider>
                    <NotificationProvider>
                      {children}
                    </NotificationProvider>
                  </JourneyProvider>
                </CapabilityGate>
              </AuthProvider>
            </TimeProvider>
          </ThemeProvider>
        </BrowserRouter>
      </AetherAuth0Provider>
    </ErrorBoundary>
  );
}
