/// <reference types="vite/client" />

/** Build-time variables the site reads (frontend/site/README.md). */
interface ImportMetaEnv {
  /** Force one site regardless of hostname: 'olympus' | 'aether'. */
  readonly VITE_SITE?: string;
  readonly VITE_SITE_OLYMPUS_URL?: string;
  readonly VITE_SITE_AETHER_URL?: string;
  /** Public API origin for the contact form. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
