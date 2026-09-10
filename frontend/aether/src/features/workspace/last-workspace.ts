/**
 * Last useful workspace (Phase 2 — tenant landing resolution).
 *
 * A completed tenant should return to the workspace surface they were actually
 * using (Explore, a campaign, profiles, …) rather than always landing on a
 * generic home page. The requested-deep-link leg of the resolver is handled upstream by
 * `RequireAuth` (a guarded destination is rendered directly after auth, so the
 * resolver never runs for it); this module supplies the persistence leg.
 *
 * Storage is localStorage, namespaced per user so one shared browser never
 * leaks one account's last workspace into another's landing. Writes and reads
 * are best-effort (private-mode / disabled storage must never break landing).
 */

/** Routes that are not "workspace destinations" — never persisted, never a target. */
const NON_WORKSPACE_PREFIXES = [
  '/activation',
  '/activate',
  '/callback',
  '/login',
  '/signup',
  '/legal/',
] as const;

/** Legacy roots are aliases for the canonical graph-first Explore workspace. */
const LEGACY_EXPLORE_PATHS = new Set(['/', '/graph']);

/**
 * A stored landing target is only ever trusted when it is a clean internal
 * absolute path: a single leading "/", never "//host" (protocol-relative, an
 * open-redirect vector), never a backslash, and never a scheme-bearing string.
 * localStorage is same-origin, but a value there is still untrusted input at
 * the moment it is read back as a redirect target, so nothing that could
 * resolve off-origin is accepted.
 */
function isSafeInternalPath(pathname: string): boolean {
  return (
    pathname.startsWith('/') &&
    !pathname.startsWith('//') &&
    !pathname.includes('\\') &&
    !/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(pathname)
  );
}

export function isWorkspaceDestination(pathname: string): boolean {
  return (
    isSafeInternalPath(pathname) &&
    !NON_WORKSPACE_PREFIXES.some(
      prefix => pathname === prefix || pathname.startsWith(prefix),
    )
  );
}

/**
 * Normalize an untrusted stored destination before it is used by a router.
 * Query/hash suffixes are retained as view state, while legacy roots become
 * the canonical Explore route. Invalid, transient, and off-origin values are
 * rejected instead of being restored.
 */
export function normalizeLastWorkspace(pathname: string | null | undefined): string | null {
  if (!pathname || !isWorkspaceDestination(pathname)) return null;
  const suffixStart = pathname.search(/[?#]/);
  const base = suffixStart === -1 ? pathname : pathname.slice(0, suffixStart);
  const suffix = suffixStart === -1 ? '' : pathname.slice(suffixStart);
  return LEGACY_EXPLORE_PATHS.has(base) ? `/explore${suffix}` : pathname;
}

export function lastWorkspaceStorageKey(scopeId: string): string {
  return `aether:last-workspace:${scopeId}`;
}

export function readLastWorkspace(scopeId: string): string | null {
  try {
    return normalizeLastWorkspace(window.localStorage.getItem(lastWorkspaceStorageKey(scopeId)));
  } catch {
    return null;
  }
}

export function clearLastWorkspace(scopeId: string): void {
  try {
    window.localStorage.removeItem(lastWorkspaceStorageKey(scopeId));
  } catch {
    // best-effort only
  }
}

/** Persist a reached workspace path, ignoring non-workspace/transient routes. */
export function persistLastWorkspace(scopeId: string, pathname: string): void {
  const normalized = normalizeLastWorkspace(pathname);
  if (!normalized) return;
  try {
    window.localStorage.setItem(lastWorkspaceStorageKey(scopeId), normalized);
  } catch {
    // best-effort only
  }
}
