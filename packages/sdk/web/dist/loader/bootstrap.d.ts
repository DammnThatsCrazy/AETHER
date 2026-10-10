import { AetherLoader } from './aether-loader';
import { type AutoInitConfig, type InstallMode } from './auto-init';
import { type AetherStub, type DrainResult } from './queue';
import { type SignalTransport } from './heartbeat';
/**
 * Loader bundle version. Kept in sync with package.json by
 * scripts/bump-sdk-version.sh and validated by
 * scripts/validate_sdk_release_alignment.py — the loader is built and shipped
 * separately from the SDK bundle it fetches, so it cannot read the SDK's
 * version at build time.
 */
declare const LOADER_VERSION = "0.1.0-alpha.0";
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
/**
 * Install the stub and keep a reference to it.
 *
 * Called at module scope by `run()`, and exported so an npm consumer that
 * wants the pre-init queue without the CDN fetch can install it directly.
 */
export declare function installBootstrapStub(target?: Record<string, unknown>): AetherStub;
/**
 * Run the one-tag install.
 *
 * Never throws. The returned result is the full account of what happened, so
 * a caller (or a test) can assert on it without parsing console output.
 */
export declare function bootstrap(options?: BootstrapOptions): Promise<BootstrapResult>;
/**
 * Entry point for the CDN bundle.
 *
 * Guarded so the module is safe to import in tests and in non-browser
 * environments, and so including the snippet twice boots once.
 */
export declare function run(options?: BootstrapOptions): Promise<BootstrapResult> | undefined;
export { LOADER_VERSION };
export { AetherLoader };
export { installStub, createStub, drainQueue } from './queue';
export { DEFAULT_AUTO_INIT, resolveConfig, readScriptAttributes, findLoaderScript } from './auto-init';
export { buildSignalEvent, reportInstallSignal, createBeaconTransport } from './heartbeat';
export declare const load: (config?: import("./aether-loader").LoaderConfig) => Promise<any>;
export declare const clearCache: () => void;
export declare const getLoadedVersion: () => string | null;
