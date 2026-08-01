/**
 * Mobile SDK configuration.
 *
 * The core SDK is platform-agnostic: it never imports React Native or Expo. The
 * host app injects the transport (`fetch`) and an auth-token provider, so the same
 * client runs under a real device runtime, a test harness, or a Node script.
 */
import type { InstallationAppKind } from '@aether/shared';

/** Which product plane the app is bound to. An Aether token can never call Kyber. */
export type MobileAppKind = InstallationAppKind; // 'aether' | 'kyber'

export interface MobileConfig {
  /** Base URL of the backend, e.g. `https://api.aether.example`. No trailing slash. */
  apiBaseUrl: string;
  /** The product plane this build belongs to. */
  appKind: MobileAppKind;
  /** Deployment environment label the device reports (e.g. `production`, `sandbox`). */
  environment: string;
  /** Optional per-request timeout hint (ms) for host transports that honor it. */
  requestTimeoutMs?: number;
}

export function normalizeBaseUrl(url: string): string {
  return url.replace(/\/+$/, '');
}
