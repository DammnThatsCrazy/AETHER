/**
 * Build-time site topology for the Olympus Labs marketing site.
 *
 * The four product-family hosts are configurable per deploy. Marketing is a
 * separate deployable from the Aether tenant application and Kyber; public
 * shells only ever link outward to those origins, never into their sessions.
 */

const meta = import.meta as unknown as { env?: Record<string, string | undefined> };
const env = meta.env ?? {};

/** Olympus Labs corporate marketing origin (this site). */
export const OLYMPUS_SITE_URL = env.VITE_OLYMPUS_SITE_URL ?? 'https://olympuslabs.com';

/** Aether public marketing origin (aether.olympuslabs.com). */
export const AETHER_MARKETING_URL = env.VITE_AETHER_MARKETING_URL ?? 'https://aether.olympuslabs.com';

/** Protected Aether tenant application origin (app.olympuslabs.com). */
export const AETHER_APP_URL = env.VITE_AETHER_APP_URL ?? 'https://app.olympuslabs.com';

/** Olympus Labs internal Kyber origin (kyber.olympuslabs.com). Never linked from public marketing. */
export const KYBER_URL = env.VITE_KYBER_URL ?? 'https://kyber.olympuslabs.com';

/** Aether documentation origin (docs.olympuslabs.com). */
export const AETHER_DOCS_URL = env.VITE_AETHER_DOCS_URL ?? 'https://docs.olympuslabs.com';

/** Aether public service status origin (status.olympuslabs.com). */
export const AETHER_STATUS_URL = env.VITE_AETHER_STATUS_URL ?? 'https://status.olympuslabs.com';
