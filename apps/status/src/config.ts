export interface StatusEnvironment {
  readonly VITE_STATUS_API_URL?: string;
  readonly VITE_STATUS_DOCS_URL?: string;
  readonly VITE_STATUS_AETHER_MARKETING_URL?: string;
}

export interface StatusConfig {
  readonly statusApiUrl: string;
  readonly docsUrl: string;
  readonly aetherMarketingUrl: string;
}

const DEFAULT_DOCS_URL = 'https://docs.olympuslabsml.com';
const DEFAULT_AETHER_MARKETING_URL = 'https://aether.olympuslabsml.com';

function configuredOrDefault(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed || fallback;
}

export function resolveStatusConfig(env: StatusEnvironment): StatusConfig {
  return {
    statusApiUrl: env.VITE_STATUS_API_URL?.trim() ?? '',
    docsUrl: configuredOrDefault(env.VITE_STATUS_DOCS_URL, DEFAULT_DOCS_URL),
    aetherMarketingUrl: configuredOrDefault(
      env.VITE_STATUS_AETHER_MARKETING_URL,
      DEFAULT_AETHER_MARKETING_URL,
    ),
  };
}
