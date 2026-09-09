import { Navigate, useNavigate } from 'react-router-dom';
import { Button, EmptyState, LoadingState } from '@aether/ui';
import { useOnboardingStatus } from '@aether-app/features/onboarding/use-onboarding';
import { useAuth } from '@aether-app/features/auth';
import { HomePage } from '@aether-app/pages/home/home-page';
import {
  isWorkspaceDestination,
  normalizeLastWorkspace,
  readLastWorkspace,
} from '@aether-app/features/workspace/last-workspace';

// A tenant is "activated" once the operator implementation plan reaches a live
// or value-proven status. Anything before that means the self-serve activation
// flow still has work to do.
const COMPLETE_STATUSES = new Set(['live', 'value_proven', 'expansion_ready']);

/**
 * Canonical post-auth resolver order (Phase 2):
 *
 *   activation incomplete          → /activation (guided activation)
 *   requested protected destination → (handled by RequireAuth: the guarded deep
 *                                     link renders directly, so this resolver
 *                                     never runs for it)
 *   last useful workspace exists   → last workspace
 *   otherwise                      → /explore (canonical workspace)
 *
 * /activation is the single guided-activation authority; /activate is a
 * compatibility alias that redirects here. Complete tenants are never
 * campaign-centric by default — Explore is the canonical graph-first
 * workspace, and intent may recommend a first-value destination after activation.
 */
export const INCOMPLETE_ACTIVATION_ROUTE = '/activation';
export const DEFAULT_WORKSPACE_ROUTE = '/explore';
export type LandingTarget = typeof DEFAULT_WORKSPACE_ROUTE | typeof INCOMPLETE_ACTIVATION_ROUTE;

/** Post-auth decision for the onboarding completion axis alone. */
export function resolveLandingTarget(status?: string | null): LandingTarget {
  if (status && COMPLETE_STATUSES.has(status)) return DEFAULT_WORKSPACE_ROUTE;
  return INCOMPLETE_ACTIVATION_ROUTE;
}

/**
 * Destination for a COMPLETE tenant: their persisted last useful workspace when
 * one exists and is a real workspace route, else Explore. The requested-deep-link
 * case never reaches here (the router renders it before TenantLanding).
 */
export function resolveCompleteLandingDestination(
  lastWorkspace?: string | null,
): string {
  const normalized = normalizeLastWorkspace(lastWorkspace);
  return normalized && isWorkspaceDestination(normalized) ? normalized : DEFAULT_WORKSPACE_ROUTE;
}

/**
 * Tenant root ("/") gate. Decides the landing surface from real onboarding
 * truth and NEVER falls back to the operator-oriented /settings page, and never
 * misroutes to /activation before a decision can be made.
 *
 *   loading   -> LoadingState (no premature navigation)
 *   complete  -> last useful workspace (scope-scoped) or /explore
 *   incomplete-> /activation (canonical guided activation)
 *   error     -> HomePage (safe, read-only landing; never /settings)
 */
export function TenantLanding({ scopeId }: { readonly scopeId?: string }) {
  const { data, isLoading, error } = useOnboardingStatus();

  // Initial load with nothing cached yet: hold on a skeleton so we never
  // navigate before the completion signal exists.
  if (isLoading && !data) return <LoadingState lines={6} className="p-8" />;

  // A failed status read must not strand the tenant on a redirect loop or the
  // operator /settings page — show the safe read-only workspace landing.
  if (error) return <HomePage />;

  if (!data) return <LoadingState lines={6} className="p-8" />;

  const status = data?.plan?.status;
  if (status && COMPLETE_STATUSES.has(status)) {
    const lastWorkspace = scopeId ? readLastWorkspace(scopeId) : null;
    const destination = resolveCompleteLandingDestination(lastWorkspace);
    return <Navigate to={destination} replace />;
  }

  return <Navigate to={INCOMPLETE_ACTIVATION_ROUTE} replace />;
}

/**
 * Auth-scoped landing used by the router: the last-workspace preference is
 * namespaced per user (multi-account safe), so the scope comes from the real
 * session. Kept separate so `TenantLanding` itself stays provider-free and unit
 * testable without an auth provider.
 */
export function AuthenticatedTenantLanding() {
  const { user } = useAuth();
  const email = user?.email;
  return email ? <TenantLanding scopeId={email} /> : <TenantLanding />;
}

/**
 * Tenant-safe catch-all. The tenant app must never redirect unknown paths to
 * the operator /settings surface; it shows a plain not-found with a route back
 * to the workspace root.
 */
export function TenantNotFound() {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-surface-base p-8">
      <div className="max-w-2xl mx-auto">
        <EmptyState
          title="Page not found"
          description="That route is not part of your workspace."
          action={
            <Button variant="secondary" size="sm" onClick={() => void navigate('/')}>
              Back to workspace
            </Button>
          }
        />
      </div>
    </div>
  );
}
