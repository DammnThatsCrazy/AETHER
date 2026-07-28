import type { ReactNode } from 'react';
import { BrowserRouter, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from '@kyber/features/auth';
import { NotificationProvider } from '@kyber/features/notifications';
import { CapabilityProvider, ThemeProvider, TimeProvider } from '@aether/ui';
import { ExplorationProvider } from '@aether/ui/exploration';
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

/**
 * Mount canonical exploration inside workforce authentication and capability
 * boundaries. Tenant-scoped state exists only while the backend-authoritative
 * scope is active; fleet state is isolated per operator session.
 */
export function ExplorationGate({ children }: { readonly children: ReactNode }) {
  const { isAuthenticated, principal } = useAuth();
  const location = useLocation();
  if (!isAuthenticated || !principal) return children;

  const tenantId = principal.active_scope?.status === 'active'
    ? principal.active_scope.tenant_id
    : `operator:${principal.operator_id}:${principal.session_id}`;
  const authorityKey = principal.active_scope?.status === 'active'
    ? principal.active_scope.scope_id
    : principal.session_id;

  return (
    <ExplorationProvider
      key={authorityKey}
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
      <BrowserRouter>
        <ThemeProvider storageKey="kyber-theme">
          <TimeProvider>
            <AuthProvider>
              <CapabilityGate>
                <ExplorationGate>
                  <JourneyProvider>
                    <NotificationProvider>
                      {children}
                    </NotificationProvider>
                  </JourneyProvider>
                </ExplorationGate>
              </CapabilityGate>
            </AuthProvider>
          </TimeProvider>
        </ThemeProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
