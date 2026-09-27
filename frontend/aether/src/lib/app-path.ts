/**
 * The app can be served from a sub-path: on staging the product lives at
 * aether.<domain>/app, built with VITE_BASE_PATH=/app/ (Vite's `base`), next
 * to the unified site in one Amplify app. React Router links are relative to
 * the router basename; raw hrefs, window.open and full-page redirects must
 * add the prefix themselves with appHref.
 */
export const APP_BASENAME = import.meta.env.BASE_URL.replace(/\/+$/, '');

/** An in-app path ("/settings") as an absolute URL path under the app base. */
export function appHref(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${APP_BASENAME}${normalized}`;
}
