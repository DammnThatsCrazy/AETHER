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
