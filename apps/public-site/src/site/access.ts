/**
 * Production runs the public site before its backend exists: pilots are sold
 * from the marketing pages and fund the production backend. That build sets
 * VITE_PILOT_ONLY=true, so links into the product (/app sign-in, sign-up and
 * plan checkout) and the live status page give way to a pilot request, and
 * the status page says status is shared with pilot partners. Staging and
 * preview builds leave it unset and keep the full journey.
 */
type AccessEnv = { VITE_PILOT_ONLY?: string };

export function pilotOnly(env: AccessEnv = import.meta.env): boolean {
  return env.VITE_PILOT_ONLY === 'true';
}

/** Whether this build serves the page a site path leads to. */
export function pathOffered(path: string, env: AccessEnv = import.meta.env): boolean {
  if (!pilotOnly(env)) return true;
  return !(path === '/status' || path === '/app' || path.startsWith('/app/'));
}

/** Where a self-serve plan choice goes: checkout in the product, or a pilot request. */
export function planChoicePath(planId: string, interval: string, env: AccessEnv = import.meta.env): string {
  return pilotOnly(env) ? `/contact?type=pilot&plan=${planId}` : `/app/signup?plan=${planId}&interval=${interval}`;
}
