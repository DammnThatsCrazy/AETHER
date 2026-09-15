// =============================================================================
// Aether SDK — ONE-TAG AUTO-INIT
//
// Turns the snippet's data-* attributes into a validated SDK config. This is
// the only place the attribute contract is interpreted, so a typo in the
// snippet is reported once, in one place, instead of surfacing as a mysterious
// "no events arrived" in the tenant's install verifier.
// =============================================================================

export type AutocaptureMode = 'off' | 'safe' | 'custom';
export type ConsentMode = 'none' | 'callback' | 'deferred' | 'required';
export type ReleaseChannel =
  | 'managed_stable'
  | 'security_auto'
  | 'compatible_auto'
  | 'patch_auto'
  | 'pinned';
/** How the SDK got onto the page. Reported to the fleet for drift analysis. */
export type InstallMode = 'cdn_auto' | 'cdn_loader' | 'npm';

export interface AutoInitConfig {
  sdkKey: string;
  siteId: string;
  endpoint: string;
  autocapture: AutocaptureMode;
  consentMode: ConsentMode;
  debug: boolean;
  releaseChannel: ReleaseChannel;
}

export const DEFAULT_AUTO_INIT: Omit<AutoInitConfig, 'sdkKey' | 'siteId'> = {
  endpoint: 'https://api.aether.network',
  autocapture: 'safe',
  consentMode: 'deferred',
  debug: false,
  releaseChannel: 'managed_stable',
};

const AUTOCAPTURE_MODES: readonly AutocaptureMode[] = ['off', 'safe', 'custom'];
const CONSENT_MODES: readonly ConsentMode[] = ['none', 'callback', 'deferred', 'required'];
const RELEASE_CHANNELS: readonly ReleaseChannel[] = [
  'managed_stable',
  'security_auto',
  'compatible_auto',
  'patch_auto',
  'pinned',
];

/** data-* attribute name -> config field. */
const ATTRIBUTE_MAP = {
  'data-key': 'sdkKey',
  'data-site': 'siteId',
  'data-endpoint': 'endpoint',
  'data-autocapture': 'autocapture',
  'data-consent': 'consentMode',
  'data-debug': 'debug',
  'data-channel': 'releaseChannel',
} as const;

export type RawAttributes = Partial<Record<keyof typeof ATTRIBUTE_MAP, string>>;

export interface ResolveOptions {
  /** Overrides merged over the defaults; wins over attributes when set. */
  overrides?: Partial<AutoInitConfig>;
  /** Where the config came from, recorded for fleet attribution. */
  installMode?: InstallMode;
}

export interface ResolveResult {
  config: AutoInitConfig | null;
  installMode: InstallMode;
  /** Fatal problems. A non-empty list means `config` is null. */
  errors: string[];
  /** Non-fatal problems worth surfacing in debug mode. */
  warnings: string[];
}

/**
 * Read data-* attributes from a <script> element.
 *
 * Accepts a plain record as well so the contract is testable without a DOM.
 */
export function readScriptAttributes(
  script: HTMLScriptElement | Record<string, string | undefined>,
): RawAttributes {
  const attrs: RawAttributes = {};
  for (const attribute of Object.keys(ATTRIBUTE_MAP) as Array<keyof typeof ATTRIBUTE_MAP>) {
    const value = (script as { getAttribute?(name: string): string | null } & Record<string, string | undefined>)
      .getAttribute?.(attribute)
      ?? (script as Record<string, string | undefined>)[attribute];
    if (typeof value === 'string' && value.length > 0) {
      attrs[attribute] = value;
    }
  }
  return attrs;
}

/** Parse the boolean-ish values an HTML attribute can carry. */
function parseBoolean(value: string): boolean | undefined {
  const normalized = value.trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
  if (['0', 'false', 'no', 'off'].includes(normalized)) return false;
  return undefined;
}

/**
 * Normalize an ingest endpoint.
 *
 * Trailing slashes are stripped so path joins cannot produce `//v1/batch`.
 * Plain http is rejected outside localhost: publishing keys over cleartext
 * would leak the key to anyone on the path.
 */
export function normalizeEndpoint(endpoint: string): { endpoint: string | null; error: string | null } {
  let url: URL;
  try {
    url = new URL(endpoint.trim());
  } catch {
    return { endpoint: null, error: `endpoint is not a valid URL: ${endpoint}` };
  }

  const isLocalhost = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && isLocalhost)) {
    return {
      endpoint: null,
      error: `endpoint must use https (got ${url.protocol}//${url.hostname})`,
    };
  }

  const path = url.pathname.replace(/\/+$/, '');
  return { endpoint: `${url.origin}${path}`, error: null };
}

/**
 * Build a validated config from snippet attributes.
 *
 * Returns errors rather than throwing: a misconfigured snippet must not break
 * the customer's page. The loader decides what to do with the errors.
 */
export function resolveConfig(
  attrs: RawAttributes,
  options: ResolveOptions = {},
): ResolveResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const overrides = options.overrides ?? {};

  const sdkKey = (overrides.sdkKey ?? attrs['data-key'] ?? '').trim();
  const siteId = (overrides.siteId ?? attrs['data-site'] ?? '').trim();

  if (!sdkKey) errors.push('missing data-key (publishable SDK key)');
  if (!siteId) errors.push('missing data-site (site id)');

  const rawEndpoint = overrides.endpoint ?? attrs['data-endpoint'] ?? DEFAULT_AUTO_INIT.endpoint;
  const { endpoint, error: endpointError } = normalizeEndpoint(rawEndpoint);
  if (endpointError) errors.push(endpointError);

  const rawAutocapture = (overrides.autocapture ?? attrs['data-autocapture'] ?? DEFAULT_AUTO_INIT.autocapture)
    .trim()
    .toLowerCase();
  let autocapture: AutocaptureMode = DEFAULT_AUTO_INIT.autocapture;
  if ((AUTOCAPTURE_MODES as readonly string[]).includes(rawAutocapture)) {
    autocapture = rawAutocapture as AutocaptureMode;
  } else {
    warnings.push(
      `unknown data-autocapture "${rawAutocapture}"; falling back to "${DEFAULT_AUTO_INIT.autocapture}"`,
    );
  }

  const rawConsent = (overrides.consentMode ?? attrs['data-consent'] ?? DEFAULT_AUTO_INIT.consentMode)
    .trim()
    .toLowerCase();
  let consentMode: ConsentMode = DEFAULT_AUTO_INIT.consentMode;
  if ((CONSENT_MODES as readonly string[]).includes(rawConsent)) {
    consentMode = rawConsent as ConsentMode;
  } else {
    warnings.push(
      `unknown data-consent "${rawConsent}"; falling back to "${DEFAULT_AUTO_INIT.consentMode}"`,
    );
  }

  const rawChannel = (overrides.releaseChannel ?? attrs['data-channel'] ?? DEFAULT_AUTO_INIT.releaseChannel)
    .trim()
    .toLowerCase();
  let releaseChannel: ReleaseChannel = DEFAULT_AUTO_INIT.releaseChannel;
  if ((RELEASE_CHANNELS as readonly string[]).includes(rawChannel)) {
    releaseChannel = rawChannel as ReleaseChannel;
  } else {
    warnings.push(
      `unknown data-channel "${rawChannel}"; falling back to "${DEFAULT_AUTO_INIT.releaseChannel}"`,
    );
  }

  let debug = overrides.debug ?? DEFAULT_AUTO_INIT.debug;
  const rawDebug = attrs['data-debug'];
  if (rawDebug !== undefined) {
    const parsed = parseBoolean(rawDebug);
    if (parsed === undefined) {
      warnings.push(`data-debug "${rawDebug}" is not a boolean; ignoring`);
    } else {
      debug = parsed;
    }
  }

  if (errors.length > 0) {
    return { config: null, installMode: options.installMode ?? 'cdn_auto', errors, warnings };
  }

  return {
    config: {
      sdkKey,
      siteId,
      endpoint: endpoint as string,
      autocapture,
      consentMode,
      debug,
      releaseChannel,
    },
    installMode: options.installMode ?? 'cdn_auto',
    errors,
    warnings,
  };
}

/**
 * Locate the script tag that loaded the loader.
 *
 * document.currentScript is null inside async callbacks, so fall back to
 * matching on the loader filename.
 */
export function findLoaderScript(
  doc: Document | undefined = typeof document === 'undefined' ? undefined : document,
): HTMLScriptElement | null {
  if (!doc) return null;
  const current = doc.currentScript as HTMLScriptElement | null;
  if (current) return current;
  const scripts = Array.from(doc.getElementsByTagName('script'));
  return scripts.find((s) => /(?:^|\/)v1\.js(?:\?|$)/.test(s.src)) ?? null;
}
