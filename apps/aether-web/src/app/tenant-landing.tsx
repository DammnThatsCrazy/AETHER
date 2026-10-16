import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { LoadingState } from '@aether/ui';
import { GlassPage } from '@aether-app/components/app-shell';
import { PrimaryButton } from '@aether-app/components/ae-ui';
import { useActivationStatus } from '@aether-app/features/activation/use-activation';
import { useOnboardingStatus } from '@aether-app/features/onboarding/use-onboarding';
import { HomePage } from '@aether-app/pages/home/home-page';
import { isRestartRequested } from '@aether-app/pages/onboarding/onboarding-model';
import { getEnvironment } from '@aether-app/lib/env';

// A tenant is "activated" once the self-serve activation lifecycle reaches
// `complete`, or (for operator-onboarded tenants) once the implementation plan
// reaches a live or value-proven status.
const COMPLETE_PLAN_STATUSES = new Set(['live', 'value_proven', 'expansion_ready']);

/**
 * Canonical post-auth resolver order:
 *
 *   ?onboarding=restart (non-production) → onboarding from step 1 (tester walk-through)
 *   activation incomplete               → /activation (workspace onboarding)
 *   requested protected destination     → (handled by RequireAuth: the guarded deep
 *                                          link renders directly, so this resolver
 *                                          never runs for it)
 *   otherwise                           → /home
 */
export const INCOMPLETE_ACTIVATION_ROUTE = '/activation';
export const DEFAULT_WORKSPACE_ROUTE = '/home';
export type LandingTarget = typeof DEFAULT_WORKSPACE_ROUTE | typeof INCOMPLETE_ACTIVATION_ROUTE;

/** Post-auth decision for the onboarding completion axis alone. */
export function resolveLandingTarget(input: {
  readonly activationState?: string | null | undefined;
  readonly planStatus?: string | null | undefined;
}): LandingTarget {
  if (input.activationState === 'complete') return DEFAULT_WORKSPACE_ROUTE;
  if (input.planStatus && COMPLETE_PLAN_STATUSES.has(input.planStatus)) return DEFAULT_WORKSPACE_ROUTE;
  return INCOMPLETE_ACTIVATION_ROUTE;
}

/**
 * Tenant root ("/") gate. Decides the landing surface from real activation
 * truth and NEVER falls back to the operator-oriented /settings page, and never
 * misroutes to /activation before a decision can be made.
 *
 *   loading    -> LoadingState (no premature navigation)
 *   complete   -> /home
 *   incomplete -> /activation (workspace onboarding)
 *   error      -> HomePage (safe landing; never /settings)
 */
export function TenantLanding() {
  const location = useLocation();
  const activation = useActivationStatus();
  const onboarding = useOnboardingStatus();

  if (isRestartRequested(location.search, getEnvironment())) {
    return <Navigate to={`${INCOMPLETE_ACTIVATION_ROUTE}?onboarding=restart`} replace />;
  }

  const activationState = activation.data?.state ?? null;
  const planStatus = onboarding.data?.plan?.status ?? null;

  // A completion signal from either axis is enough to decide.
  if (resolveLandingTarget({ activationState, planStatus }) === DEFAULT_WORKSPACE_ROUTE) {
    return <Navigate to={DEFAULT_WORKSPACE_ROUTE} replace />;
  }

  // Hold on a skeleton until the activation read settles, so we never
  // navigate before the completion signal exists.
  if (activation.isLoading && !activation.data) return <LoadingState lines={6} className="p-8" />;

  // The activation read failed: never strand the tenant on a redirect loop or
  // the operator /settings page — show the safe workspace landing.
  if (!activation.data && activation.error) {
    if (onboarding.isLoading && !onboarding.data) return <LoadingState lines={6} className="p-8" />;
    return <HomePage />;
  }

  if (!activation.data) return <LoadingState lines={6} className="p-8" />;

  // Either axis can establish completion, so an incomplete activation record
  // is not enough on its own: hold until the operator-plan read has settled
  // (data or error) before sending the tenant to onboarding.
  if (!onboarding.data && !onboarding.error) return <LoadingState lines={6} className="p-8" />;

  return <Navigate to={INCOMPLETE_ACTIVATION_ROUTE} replace />;
}

/** Router entry for "/". Kept as a named export for existing importers. */
export function AuthenticatedTenantLanding() {
  return <TenantLanding />;
}

/**
 * Tenant-safe catch-all. The tenant app must never redirect unknown paths to
 * the operator /settings surface; it shows a plain not-found with a route back
 * to the workspace root.
 */
export function TenantNotFound() {
  const navigate = useNavigate();
  return (
    <GlassPage>
      <div className="m-auto flex max-w-md flex-col items-center gap-3 text-center">
        <h1 className="text-[22px] font-medium tracking-[-0.4px]">Page not found</h1>
        <p className="text-[14px]" style={{ color: 'var(--ae-mute)' }}>That route is not part of your workspace.</p>
        <PrimaryButton onClick={() => void navigate('/')}>Back to workspace</PrimaryButton>
      </div>
    </GlassPage>
  );
}
