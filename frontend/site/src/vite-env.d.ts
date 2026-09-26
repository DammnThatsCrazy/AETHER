/// <reference types="vite/client" />

/** Build-time variables the site reads (frontend/site/README.md). */
interface ImportMetaEnv {
  /** Force one site regardless of hostname: 'olympus' | 'aether'. */
  readonly VITE_SITE?: string;
  readonly VITE_SITE_OLYMPUS_URL?: string;
  readonly VITE_SITE_AETHER_URL?: string;
  /** Public API origin for the contact form. */
  readonly VITE_API_BASE_URL?: string;
  /** Existing health endpoint for /status. */
  readonly VITE_STATUS_API_URL?: string;
  /** 90-day history feed for /status (GET ?days=90). */
  readonly VITE_STATUS_HISTORY_URL?: string;
  /** 'true' shows plan prices; otherwise pricing reads "on request". */
  readonly VITE_PUBLISH_PRICES?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** Platform version from pyproject.toml, injected at build time. */
declare const __PLATFORM_VERSION__: string;
