/**
 * Analytics configuration surface for the Aether public marketing shell.
 *
 * Honest contract: the marketing ecosystem is not deployed, and this module
 * emits NOTHING by default. Analytics is strictly opt-in — it is enabled only
 * when a build explicitly sets `VITE_ANALYTICS_PROVIDER` to `plausible` or
 * `ga4` AND `VITE_ANALYTICS_PROPERTY_ID` to a non-empty value. With no env
 * configuration (the default build) `analyticsFromEnv()` resolves to
 * `{ enabled: false, provider: 'off', propertyId: '' }` and `initAnalytics`
 * returns immediately without touching the DOM.
 *
 * This module is configuration surface for a future deployment, not a claim
 * that analytics is live anywhere. The provider script injection it describes
 * is defensive (guards `document`/`window`, dedupes, and never throws) because
 * it is intended to run only in a browser build that has been deliberately
 * configured to measure traffic.
 */

export type AnalyticsProvider = 'off' | 'plausible' | 'ga4';

/** Provider-level configuration a deployer declares at build time. */
export interface AnalyticsConfig {
  readonly provider: AnalyticsProvider;
  readonly propertyId: string;
}

/** The resolved analytics state a shell acts on (or deliberately ignores). */
export interface AnalyticsState {
  readonly enabled: boolean;
  readonly provider: AnalyticsProvider;
  readonly propertyId: string;
}

/** Read `import.meta.env` the same defensive way `env.ts` does. */
const meta = import.meta as unknown as { env?: Record<string, string | undefined> };
const env = meta.env ?? {};

/**
 * Resolve raw, untrusted env-ish input into a normalized `AnalyticsState`.
 * Enabled only when the provider is exactly `plausible` or `ga4` AND the
 * property id is non-empty (after trimming). Unknown, missing, or empty
 * providers normalize to `'off'`; a valid provider with an empty property id
 * keeps its provider label but stays disabled. Never throws.
 */
export function resolveAnalytics(raw: {
  readonly provider?: string | undefined;
  readonly propertyId?: string | undefined;
}): AnalyticsState {
  const provider: AnalyticsProvider = raw.provider === 'plausible' || raw.provider === 'ga4' ? raw.provider : 'off';
  const propertyId = (raw.propertyId ?? '').trim();
  const enabled = (provider === 'plausible' || provider === 'ga4') && propertyId.length > 0;
  return { enabled, provider, propertyId };
}

/**
 * Build the analytics state from this build's environment. Defaults are
 * `VITE_ANALYTICS_PROVIDER=off` and an empty `VITE_ANALYTICS_PROPERTY_ID`, so
 * an unconfigured build is always inert.
 */
export function analyticsFromEnv(): AnalyticsState {
  return resolveAnalytics({
    provider: env.VITE_ANALYTICS_PROVIDER,
    propertyId: env.VITE_ANALYTICS_PROPERTY_ID,
  });
}

/** Load the Plausible async script, tagged so a second call never duplicates it. */
function injectPlausible(propertyId: string): void {
  if (document.querySelector('script[data-analytics-provider="plausible"]') !== null) return;
  const script = document.createElement('script');
  script.async = true;
  script.src = 'https://plausible.io/js/script.js';
  script.dataset.domain = propertyId;
  script.dataset.analyticsProvider = 'plausible';
  document.head.appendChild(script);
}

/** Load the GA4 gtag bootstrap and queue the initial `config` event. */
function injectGa4(propertyId: string): void {
  if (typeof window === 'undefined') return;
  if (document.querySelector('script[data-analytics-provider="ga4"]') !== null) return;

  const gtagWindow = window as Window & {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  };
  const dataLayer = gtagWindow.dataLayer ?? [];
  gtagWindow.dataLayer = dataLayer;
  gtagWindow.gtag = (...args: unknown[]) => {
    dataLayer.push(args);
  };

  const script = document.createElement('script');
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(propertyId)}`;
  script.dataset.analyticsProvider = 'ga4';
  document.head.appendChild(script);

  gtagWindow.gtag('js', new Date());
  gtagWindow.gtag('config', propertyId);
}

/**
 * Initialize analytics for the page. Returns immediately when `state.enabled`
 * is false (the default build). When enabled, injects the provider script
 * defensively: `document`/`window` existence is guarded, injection is wrapped
 * in try/catch so a blocked third-party script can never break the marketing
 * shell, and every injected tag carries a `data-analytics-provider` marker to
 * make duplicate injection impossible.
 */
export function initAnalytics(state: AnalyticsState): void {
  if (!state.enabled) return;
  if (typeof document === 'undefined') return;
  try {
    if (state.provider === 'plausible') {
      injectPlausible(state.propertyId);
    } else if (state.provider === 'ga4') {
      injectGa4(state.propertyId);
    }
  } catch {
    // Analytics is best-effort. A failure here must never affect the page.
  }
}
