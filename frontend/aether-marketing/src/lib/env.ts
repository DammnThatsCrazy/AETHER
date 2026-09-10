/**
 * Build-time site topology for the Aether public marketing site
 * (aether.olympuslabsml.com).
 *
 * The Aether marketing site, the protected Aether tenant application, and Kyber
 * are separate deployables. Public marketing links outward to the application
 * origin and documentation; it never shares a session with them.
 */

const meta = import.meta as unknown as { env?: Record<string, string | undefined> };
const env = meta.env ?? {};

/** Olympus Labs corporate marketing origin (olympuslabsml.com). */
export const OLYMPUS_SITE_URL = env.VITE_OLYMPUS_SITE_URL ?? 'https://olympuslabsml.com';

/** This Aether public marketing origin. */
export const AETHER_MARKETING_URL = env.VITE_AETHER_MARKETING_URL ?? 'https://aether.olympuslabsml.com';

/** Protected Aether tenant application origin (app.olympuslabsml.com). */
export const AETHER_APP_URL = env.VITE_AETHER_APP_URL ?? 'https://app.olympuslabsml.com';

/** Olympus Labs internal Kyber origin (kyber.olympuslabsml.com). Never linked from public marketing. */
export const KYBER_URL = env.VITE_KYBER_URL ?? 'https://kyber.olympuslabsml.com';

/** Aether documentation origin (docs.olympuslabsml.com). */
export const AETHER_DOCS_URL = env.VITE_AETHER_DOCS_URL ?? 'https://docs.olympuslabsml.com';

/** Aether public service status origin (status.olympuslabsml.com). */
export const AETHER_STATUS_URL = env.VITE_AETHER_STATUS_URL ?? 'https://status.olympuslabsml.com';
