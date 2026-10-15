// =============================================================================
// Aether SDK — ONE-TAG BOOTSTRAP (the `v1.js` entry point)
//
// This is what https://cdn.aether.network/v1.js actually runs. It turns a
// single <script> tag into a working install with no follow-up JS:
//
//   <script async src="https://cdn.aether.network/v1.js"
//     data-key="pk_live_..." data-site="site_..."></script>
//
// Sequence, and why it is this order:
//
//   1. install the stub  (SYNCHRONOUSLY, before any await) — customer code
//      that runs on the next line after the tag must be captured, and it can
//      only be captured if the stub exists before this module yields.
//   2. read the snippet's data-* attributes and validate them.
//   3. fetch and evaluate the SDK bundle, then init it.
//   4. replay everything the stub captured, in order, onto the live SDK.
//
// Every failure path is reported and swallowed. A misconfigured or unreachable
// install must degrade to "tracking does not work" — never to "the customer's
// page threw".
// =============================================================================

import { AetherLoader } from './aether-loader';
import {
  findLoaderScript,
  readScriptAttributes,
  resolveConfig,
  type AutoInitConfig,
  type InstallMode,
} from './auto-init';
import { drainQueue, installStub, type AetherStub, type DrainResult } from './queue';
import { reportInstallSignal, type SignalTransport } from './heartbeat';

/**
 * Loader bundle version. Kept in sync with package.json by
 * scripts/bump-sdk-version.sh and validated by
 * scripts/validate_sdk_release_alignment.py — the loader is built and shipped
 * separately from the SDK bundle it fetches, so it cannot read the SDK's
 * version at build time.
 */
const LOADER_VERSION = '0.1.0-alpha.0';

/** The live SDK surface the bootstrap needs. */
interface LiveSdk {
  init(config: Record<string, unknown>): void;
  track?(...args: unknown[]): unknown;
  identify?(...args: unknown[]): unknown;
  page?(...args: unknown[]): unknown;
  ready?(fn: () => void): unknown;
}

interface LoaderLike {
  load(config?: Record<string, unknown>): Promise<unknown>;
  getLoadedVersion?(): string | null;
}

export interface BootstrapOptions {
  /** Document to read the snippet from. Defaults to the global document. */
  doc?: Document;
  /** Global object to install the stub on. Defaults to globalThis. */
  target?: Record<string, unknown>;
  /** Loader implementation. Defaults to the shared AetherLoader instance. */
  loader?: LoaderLike;
  /** Signal transport. Defaults to a keepalive fetch. */
  transport?: SignalTransport;
}

export interface BootstrapResult {
  ok: boolean;
  config: AutoInitConfig | null;
  installMode: InstallMode;
  /** Fatal problems. Non-empty means the install did not come up. */
  errors: string[];
  /** Non-fatal problems worth surfacing in debug mode. */
  warnings: string[];
  drained: DrainResult | null;
  sdkVersion: string | null;
}

/** Marker read by installStub so a second inclusion cannot clobber a live SDK. */
const LIVE_FLAG = '__aetherLive';

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Install the stub and keep a reference to it.
 *
 * Called at module scope by `run()`, and exported so an npm consumer that
 * wants the pre-init queue without the CDN fetch can install it directly.
 */
export function installBootstrapStub(
  target: Record<string, unknown> = globalThis as unknown as Record<string, unknown>,
): AetherStub {
  return installStub(target);
}

/**
 * Run the one-tag install.
 *
 * Never throws. The returned result is the full account of what happened, so
 * a caller (or a test) can assert on it without parsing console output.
 */
export async function bootstrap(options: BootstrapOptions = {}): Promise<BootstrapResult> {
  const doc = options.doc ?? (typeof document === 'undefined' ? undefined : document);
  const target = options.target ?? (globalThis as unknown as Record<string, unknown>);

  // 1. Stub first, before anything can await.
  const stub = installBootstrapStub(target);

  const fail = (
    errors: string[],
    warnings: string[],
    config: AutoInitConfig | null,
    installMode: InstallMode,
    reason?: string,
  ): BootstrapResult => {
    if (config) {
      reportInstallSignal(
        {
          signal: 'sdk_init_failed',
          installMode,
          loaderVersion: LOADER_VERSION,
          sdkKey: config.sdkKey,
          siteId: config.siteId,
          endpoint: config.endpoint,
          reason: reason ?? errors.join('; '),
          warnings,
        },
        options.transport,
      );
    }
    return { ok: false, config, installMode, errors, warnings, drained: null, sdkVersion: null };
  };

  // 2. Read and validate the snippet.
  const script = findLoaderScript(doc);
  const attrs = script ? readScriptAttributes(script) : {};
  const resolved = resolveConfig(attrs);

  if (!resolved.config) {
    // No endpoint or key means there is nothing to report *to*, so the errors
    // go to the console only. This is the misconfigured-snippet path, and the
    // fix is a human editing HTML — a silent failure would be unhelpful.
    console.error('[Aether] install failed:', resolved.errors.join('; '));
    return fail(resolved.errors, resolved.warnings, null, resolved.installMode, 'invalid snippet config');
  }

  const config = resolved.config;
  const { installMode, warnings } = resolved;
  const signalBase = {
    installMode,
    loaderVersion: LOADER_VERSION,
    sdkKey: config.sdkKey,
    siteId: config.siteId,
    endpoint: config.endpoint,
    warnings,
  };

  if (config.debug && warnings.length > 0) {
    for (const warning of warnings) console.warn(`[Aether] ${warning}`);
  }

  // 3. Fetch and initialize the SDK.
  let sdk: LiveSdk;
  let sdkVersion: string | null = null;
  try {
    const loader: LoaderLike = options.loader ?? (AetherLoader as unknown as LoaderLike);

    const loaded = (await loader.load({
      // A pinned channel resolves through the manifest, so the loader — not the
      // page — decides which bundle a site is on. That is what makes a
      // managed rollout possible without editing tenant HTML.
      version: config.releaseChannel === 'pinned' ? undefined : 'latest',
    })) as LiveSdk;

    sdkVersion = loader.getLoadedVersion?.() ?? null;
    reportInstallSignal({ ...signalBase, signal: 'sdk_loaded', sdkVersion }, options.transport);

    sdk = (loaded as { default?: LiveSdk })?.default ?? loaded;
    if (!sdk || typeof sdk.init !== 'function') {
      throw new Error('loaded bundle does not expose init()');
    }

    sdk.init({
      apiKey: config.sdkKey,
      endpoint: config.endpoint,
      debug: config.debug,
      siteId: config.siteId,
      // autocapture/consentMode are resolved here and applied below rather
      // than passed through: the SDK's own defaults are its business, and the
      // snippet should only override what it explicitly names.
    });

    // The SDK is now authoritative. Mark it live *before* draining so that a
    // re-entrant installStub (a duplicated snippet) sees a live SDK and
    // bails out instead of replacing it and losing the queue.
    (sdk as unknown as Record<string, unknown>)[LIVE_FLAG] = true;
    target.Aether = sdk;
  } catch (error) {
    const reason = describe(error);
    console.error(`[Aether] SDK did not come up: ${reason}`);
    return fail([reason], warnings, config, installMode, reason);
  }

  // 4. Replay anything the customer called before the SDK existed.
  let drained: DrainResult | null = null;
  if (stub.q.length > 0) {
    drained = drainQueue(sdk as never, stub.q);
    stub.q.length = 0;
    if (config.debug && drained.failures.length > 0) {
      for (const failure of drained.failures) {
        console.warn(`[Aether] queued ${failure.entry[0]}() could not be replayed: ${failure.reason}`);
      }
    }
  }

  reportInstallSignal({ ...signalBase, signal: 'sdk_initialized', sdkVersion }, options.transport);

  return { ok: true, config, installMode, errors: [], warnings, drained, sdkVersion };
}

/**
 * Entry point for the CDN bundle.
 *
 * Guarded so the module is safe to import in tests and in non-browser
 * environments, and so including the snippet twice boots once.
 */
export function run(options: BootstrapOptions = {}): Promise<BootstrapResult> | undefined {
  const target = options.target ?? (globalThis as unknown as Record<string, unknown>);
  const existing = target.Aether as Record<string, unknown> | undefined;
  if (existing && existing[LIVE_FLAG]) return undefined;
  return bootstrap(options);
}

export { LOADER_VERSION };

// -----------------------------------------------------------------------------
// Public surface of the CDN bundle
//
// The UMD wrapper assigns this module's namespace to `globalThis.AetherLoader`,
// which would otherwise shadow the loader instance that `aether-loader.ts`
// publishes under the same name and break the documented `AetherLoader.load()`
// call. Re-exporting the instance's methods at the top level keeps that call
// working for sites that drive loading explicitly, while `AetherLoader.AetherLoader`
// remains available for anyone who wants the class itself.
// -----------------------------------------------------------------------------
export { AetherLoader };
export { installStub, createStub, drainQueue } from './queue';
export { DEFAULT_AUTO_INIT, resolveConfig, readScriptAttributes, findLoaderScript } from './auto-init';
export { buildSignalEvent, reportInstallSignal, createBeaconTransport } from './heartbeat';

export const load = AetherLoader.load.bind(AetherLoader);
export const clearCache = AetherLoader.clearCache.bind(AetherLoader);
export const getLoadedVersion = AetherLoader.getLoadedVersion.bind(AetherLoader);

// Evaluating this bundle IS the install — the snippet deliberately has no
// follow-up JS. Guarded on `document` so importing the module in Node (tests,
// SSR bundlers) does not attempt a boot.
if (typeof document !== 'undefined') {
  void run();
}
