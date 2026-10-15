import type { BuildInfo } from '@aether/ui';
import { env } from '@aether-app/lib/env/config';

/**
 * Frontend build identity for the tenant app diagnostics badge. Populated by
 * vite `define` at build time (version from the workspace package.json,
 * SHA/profile from CI env); falls back to 'dev' locally.
 */
export const BUILD_INFO: BuildInfo = {
  version: env.VITE_APP_VERSION,
  gitSha: env.VITE_GIT_SHA,
  profile: env.VITE_RELEASE_PROFILE || env.VITE_AETHER_ENV,
  environment: env.VITE_AETHER_ENV,
};
