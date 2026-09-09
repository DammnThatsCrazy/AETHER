import type { ReactNode } from 'react';
import { BrowserRouter, useLocation } from 'react-router-dom';
import { CapabilityProvider, ErrorState, LoadingState, ThemeProvider, TimeProvider, ToastProvider, useQuery } from '@aether/ui';
import { GraphContextProvider } from '@aether/ui/exploration';
import { AuthProvider, useAuth } from '@aether-app/features/auth';
import { AetherAuth0Provider } from '@aether-app/lib/auth/auth0-provider';
import { JourneyProvider } from '@aether-app/features/journey';
import { fetchTenantCapabilities } from '@aether-app/lib/api/capabilities';
import { explorationClient } from '@aether-app/lib/api/exploration';
import { api } from '@aether-app/lib/api/endpoints';
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
 * Binds the router's shareable URL state to the backend-authoritative graph
 * scope. The profile is fetched only for authenticated users; until it is
 * available and complete, the gate renders an explicit loading/unavailable
 * state rather than exposing graph-native children without graph authority.
 *
 * The provider key includes every scope coordinate so no graph state can
 * survive a tenant, workspace, or logical-environment transition. URL values
 * are view/query state only and never supply scope coordinates.
 */
export function ExplorationGate({ children }: { readonly children: ReactNode }) {
  const { isAuthenticated, user } = useAuth();
  const location = useLocation();
  const profileQuery = useQuery({
    key: `me-profile:${user?.id ?? 'anonymous'}`,
    fetcher: () => api.me.profile(),
    enabled: isAuthenticated,
  });
  const graphScope = profileQuery.data?.graph_scope;
  const hasCompleteScope = Boolean(
    isAuthenticated
      && !profileQuery.isLoading
      && !profileQuery.error
      && profileQuery.data?.tenant_id === graphScope?.tenant_id
      && graphScope
      && graphScope.scope_model === 'single_workspace_tenant_v1'
      && graphScope.tenant_id
      && graphScope.workspace_id
      && graphScope.environment_id,
  );

  if (!isAuthenticated) return children;
  if (profileQuery.isLoading) return <LoadingState lines={6} />;
  if (!hasCompleteScope || !graphScope) {
    return (
      <ErrorState
        title="Graph context unavailable"
        message={profileQuery.error ?? 'Authenticated graph scope is unavailable.'}
      />
    );
  }

  const scopeKey = JSON.stringify([
    graphScope.tenant_id,
    graphScope.workspace_id,
    graphScope.environment_id,
  ]);

  return (
    <GraphContextProvider
      key={scopeKey}
      scope={graphScope}
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
