/**
 * Build-time site topology for the Aether public marketing site
 * (aether.olympuslabs.com).
 *
 * The Aether marketing site, the protected Aether tenant application, and Kyber
 * are separate deployables. Public marketing links outward to the application
 * origin and documentation; it never shares a session with them.
 */

const meta = import.meta as unknown as { env?: Record<string, string | undefined> };
const env = meta.env ?? {};

/** Olympus Labs corporate marketing origin (olympuslabs.com). */
export const OLYMPUS_SITE_URL = env.VITE_OLYMPUS_SITE_URL ?? 'https://olympuslabs.com';

/** This Aether public marketing origin. */
export const AETHER_MARKETING_URL = env.VITE_AETHER_MARKETING_URL ?? 'https://aether.olympuslabs.com';

/** Protected Aether tenant application origin (app.olympuslabs.com). */
export const AETHER_APP_URL = env.VITE_AETHER_APP_URL ?? 'https://app.olympuslabs.com';

/** Olympus Labs internal Kyber origin (kyber.olympuslabs.com). Never linked from public marketing. */
export const KYBER_URL = env.VITE_KYBER_URL ?? 'https://kyber.olympuslabs.com';

/** Aether documentation origin (docs.olympuslabs.com). */
export const AETHER_DOCS_URL = env.VITE_AETHER_DOCS_URL ?? 'https://docs.olympuslabs.com';

/** Aether public service status origin (status.olympuslabs.com). */
export const AETHER_STATUS_URL = env.VITE_AETHER_STATUS_URL ?? 'https://status.olympuslabs.com';
