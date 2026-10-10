import type { ReactNode } from 'react';
import { BrowserRouter, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from '@kyber/features/auth';
import { NotificationProvider } from '@kyber/features/notifications';
import { CapabilityProvider, ThemeProvider, TimeProvider } from '@aether/ui';
import { GraphContextProvider } from '@aether/ui/exploration';
import { JourneyProvider } from '@kyber/features/journey';
import { fetchOperatorCapabilities } from '@kyber/lib/api/capabilities';
import { explorationClient } from '@kyber/lib/api/exploration';
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

  const activeScope = principal.active_scope?.status === 'active' ? principal.active_scope : null;
  // Workforce responses do not expose a separate workspace coordinate. For a
  // tenant scope the backend's tenant is the workspace authority (the same
  // single-workspace model used by Aether); without one, keep fleet state
  // isolated to this authenticated operator session. Neither value comes
  // from URL/deployment labels.
  const tenantId = activeScope?.tenant_id ?? `operator:${principal.operator_id}:${principal.session_id}`;
  const scope = {
    tenant_id: tenantId,
    workspace_id: activeScope?.tenant_id ?? `operator:${principal.operator_id}`,
    environment_id: activeScope?.environment ?? principal.environment,
  } as const;
  const authorityKey = JSON.stringify([scope.tenant_id, scope.workspace_id, scope.environment_id]);

  return (
    <GraphContextProvider
      key={authorityKey}
      scope={scope}
      surface={location.pathname}
      query={location.search}
      client={explorationClient}
    >
      {children}
    </GraphContextProvider>
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
