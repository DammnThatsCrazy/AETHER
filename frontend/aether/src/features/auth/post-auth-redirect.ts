/**
 * The post-auth destination a successful login/signup should land on. Only an
 * internal absolute path is accepted (a single leading `/`, not a
 * protocol-relative `//…`, a `/…\…` form that URL parsers normalize into an
 * authority, or any embedded backslash/control character) — RequireAuth builds
 * it from the visitor's own deep link, and anything else falls back to the
 * tenant home so a hand-built `/login?redirect=…` link can never push the
 * browser to a foreign origin.
 *
 * Shared by the login and signup pages (and re-exported from login-page for
 * back-compat with existing importers).
 */
export function resolvePostAuthRedirect(raw: string | null): string {
  if (
    raw !== null &&
    raw.startsWith("/") &&
    !raw.startsWith("//") &&
    !raw.startsWith("/\\") &&
    !raw.includes("\\") &&
    !raw.includes("\r") &&
    !raw.includes("\n")
  ) {
    return raw;
  }
  return "/settings";
}

/** Self-serve plans the pricing page can hand off (shared/plans/catalog.py). */
export const SELF_SERVE_PLAN_IDS = ["alpha", "beta", "gamma", "delta"] as const;
export type SelfServePlanId = (typeof SELF_SERVE_PLAN_IDS)[number];

export function parseSelfServePlan(raw: string | null): SelfServePlanId | null {
  const value = (raw ?? "").trim().toLowerCase();
  return (SELF_SERVE_PLAN_IDS as readonly string[]).includes(value) ? (value as SelfServePlanId) : null;
}

const DESTINATION_KEY = "aether:post-auth-destination";
/** A stored destination older than this is ignored (an abandoned sign-in). */
const DESTINATION_TTL_MS = 30 * 60 * 1000;

/**
 * Auth0 sign-in and sign-up leave the app for the hosted login page, so the
 * destination (for example the billing page with the plan chosen on the
 * pricing page) is kept in session storage and read back on /callback. Only
 * values resolvePostAuthRedirect accepts are stored or returned. Reading does
 * not remove the entry, so a repeated callback effect lands on the same page;
 * every Auth0 hand-off overwrites it, and it expires after DESTINATION_TTL_MS.
 */
export function rememberPostAuthDestination(path: string, now: number = Date.now()): void {
  const safe = resolvePostAuthRedirect(path);
  try {
    window.sessionStorage.setItem(DESTINATION_KEY, JSON.stringify({ path: safe, at: now }));
  } catch {
    // Storage can be unavailable (private mode); the callback falls back.
  }
}

export function readPostAuthDestination(now: number = Date.now()): string {
  try {
    const raw = window.sessionStorage.getItem(DESTINATION_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { path?: unknown; at?: unknown };
      if (
        typeof parsed.path === "string" &&
        typeof parsed.at === "number" &&
        now - parsed.at >= 0 &&
        now - parsed.at <= DESTINATION_TTL_MS
      ) {
        return resolvePostAuthRedirect(parsed.path);
      }
    }
  } catch {
    // Unreadable or malformed storage falls back to the tenant home.
  }
  return resolvePostAuthRedirect(null);
}
