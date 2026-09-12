/**
 * Build-time site topology for the Olympus Labs marketing site.
 *
 * The product-family hosts are configurable per deploy. Marketing is a
 * separate deployable from the Aether tenant application; public shells only
 * ever link outward to those origins, never into their sessions.
 */

const meta = import.meta as unknown as { env?: Record<string, string | undefined> };
const env = meta.env ?? {};

/** Olympus Labs corporate marketing origin (this site). */
export const OLYMPUS_SITE_URL = env.VITE_OLYMPUS_SITE_URL ?? 'https://olympuslabsml.com';

/** Aether public marketing origin (aether.olympuslabsml.com). */
export const AETHER_MARKETING_URL = env.VITE_AETHER_MARKETING_URL ?? 'https://aether.olympuslabsml.com';

/** Protected Aether tenant application origin (app.olympuslabsml.com). */
export const AETHER_APP_URL = env.VITE_AETHER_APP_URL ?? 'https://app.olympuslabsml.com';

/** Aether documentation origin (docs.olympuslabsml.com). */
export const AETHER_DOCS_URL = env.VITE_AETHER_DOCS_URL ?? 'https://docs.olympuslabsml.com';

/** Aether public service status origin (status.olympuslabsml.com). */
export const AETHER_STATUS_URL = env.VITE_AETHER_STATUS_URL ?? 'https://status.olympuslabsml.com';
