import { Navigate, useNavigate } from 'react-router-dom';
import { Button, EmptyState, LoadingState } from '@aether/ui';
import { useOnboardingStatus } from '@aether-app/features/onboarding/use-onboarding';
import { HomePage } from '@aether-app/pages/home/home-page';

// A tenant is "activated" once the operator implementation plan reaches a live
// or value-proven status. Anything before that means the self-serve activation
// flow still has work to do.
const COMPLETE_STATUSES = new Set(['live', 'value_proven', 'expansion_ready']);

/**
 * Tenant root ("/") gate. Decides the landing surface from real onboarding
 * truth and NEVER falls back to the operator-oriented /settings page, and never
 * misroutes to /activation before a decision can be made.
 *
 *   loading  -> LoadingState (no premature navigation)
 *   complete -> HomePage
 *   incomplete -> /activation
 *   error    -> HomePage (safe, read-only landing; never /settings)
 */
export function TenantLanding() {
  const { data, isLoading, error } = useOnboardingStatus();

  // Initial load with nothing cached yet: hold on a skeleton so we never
  // navigate before the completion signal exists.
  if (isLoading && !data) return <LoadingState lines={6} className="p-8" />;

  // A failed status read must not strand the tenant on a redirect loop or the
  // operator /settings page — show the safe read-only workspace landing.
  if (error) return <HomePage />;

  if (!data) return <LoadingState lines={6} className="p-8" />;

  const status = data?.plan?.status;
  if (status && COMPLETE_STATUSES.has(status)) return <HomePage />;

  return <Navigate to="/activation" replace />;
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
