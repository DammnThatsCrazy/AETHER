/**
 * Test doubles for the Kyber auth/authz surface.
 *
 * Deliberately lives under `src/test/` and NOT in a `mocks/` or `fixtures/`
 * directory — `scripts/validate_frontend_data_truth.py` bans those names from
 * shipped source in this app and scans production bundles for them.
 */

import type { ReactElement, ReactNode } from 'react';
import { render, type RenderResult } from '@testing-library/react';
import { vi, type Mock } from 'vitest';

/** Loosely typed mock alias: vitest's `Mock` is invariant in its signature. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyMock = Mock<any[], any>;
import { AuthProvider } from '@kyber/features/auth';
import type {
  AccessScope,
  KyberDevice,
  KyberPrincipalView,
  KyberSessionView,
  WebAuthnRegistrationOptions,
} from '@kyber/types';

export function makePrincipal(overrides: Partial<KyberPrincipalView> = {}): KyberPrincipalView {
  return {
    operator_id: 'op_test_001',
    email: 'operator@aether.dev',
    display_name: 'Test Operator',
    employment_status: 'active',
    environment: 'test',
    session_id: 'sess_test_001',
    session_status: 'active',
    authentication_strength: 'device_bound',
    device_id: 'dev_test_001',
    device_approval_state: 'approved',
    role_template_ids: ['kyber.role.support'],
    capabilities: ['kyber.tenant.mirror.read'],
    max_disclosure: 2,
    max_action_class: 2,
    presence_expires_at: null,
    authority_expires_at: null,
    idle_expires_at: null,
    step_up_expires_at: null,
    active_scope: null,
    may_approve_devices: false,
    ...overrides,
  };
}

export function makeSession(overrides: Partial<KyberSessionView> = {}): KyberSessionView {
  return {
    session_id: 'sess_test_001',
    operator_id: 'op_test_001',
    status: 'active',
    authentication_strength: 'device_bound',
    environment: 'test',
    device_id: 'dev_test_001',
    device_approval_state: 'approved',
    issued_at: '2026-07-25T00:00:00Z',
    presence_expires_at: null,
    authority_expires_at: null,
    idle_expires_at: null,
    step_up_expires_at: null,
    step_up_required: false,
    risk_reasons: [],
    ...overrides,
  };
}

export function makeScope(overrides: Partial<AccessScope> = {}): AccessScope {
  return {
    scope_id: 'scope_test_001',
    operator_id: 'op_test_001',
    session_id: 'sess_test_001',
    device_id: 'dev_test_001',
    environment: 'test',
    tenant_id: 'tenant_acme',
    purpose: 'customer_support',
    reason: 'ticket 4711',
    ticket_reference: 'SUP-4711',
    disclosure_level: 1,
    status: 'active',
    entered_at: '2026-07-25T00:00:00Z',
    expires_at: new Date(Date.now() + 90_000).toISOString(),
    exited_at: null,
    ...overrides,
  };
}

export function makeDevice(overrides: Partial<KyberDevice> = {}): KyberDevice {
  return {
    device_id: 'dev_test_001',
    operator_id: 'op_test_001',
    display_name: 'Test laptop',
    approval_state: 'pending',
    platform: 'macOS',
    browser: 'Chrome',
    user_agent: 'test-agent',
    requested_by: 'operator@aether.dev',
    requested_at: '2026-07-25T00:00:00Z',
    approved_by: null,
    approved_at: null,
    last_seen_at: null,
    has_proof_key: true,
    is_current_device: true,
    ...overrides,
  };
}

export function makeRegistrationOptions(
  overrides: Partial<WebAuthnRegistrationOptions> = {},
): WebAuthnRegistrationOptions {
  return {
    challenge: 'Y2hhbGxlbmdl',
    rp: { id: 'kyber.test', name: 'Kyber' },
    user: { id: 'dXNlcg', name: 'operator@aether.dev', displayName: 'Test Operator' },
    pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
    timeout: 60_000,
    attestation: 'none',
    excludeCredentials: [],
    userVerification: 'required',
    residentKey: 'preferred',
    ...overrides,
  };
}

export interface StubRoute {
  readonly status?: number;
  readonly body?: unknown;
}

/**
 * Installs a `fetch` stub that answers by URL substring. Anything unmatched
 * resolves 404 so a forgotten route shows up as a test failure, not a hang.
 */
export function stubFetch(routes: Record<string, StubRoute>): AnyMock {
  const impl = vi.fn(async (input: unknown) => {
    const url = typeof input === 'string' ? input : String((input as { url?: string }).url ?? '');
    for (const [pattern, route] of Object.entries(routes)) {
      if (url.includes(pattern)) {
        const status = route.status ?? 200;
        return {
          ok: status >= 200 && status < 300,
          status,
          statusText: String(status),
          headers: { get: () => null },
          json: async () => route.body ?? null,
        } as unknown as Response;
      }
    }
    return {
      ok: false,
      status: 404,
      statusText: 'Not Found',
      headers: { get: () => null },
      json: async () => ({ detail: `no stub for ${url}` }),
    } as unknown as Response;
  });
  vi.stubGlobal('fetch', impl);
  return impl;
}

export interface AuthHarnessOptions {
  readonly principal?: KyberPrincipalView | null;
  readonly session?: KyberSessionView | null;
  /** HTTP status for `/v1/kyber/me` — set 401 to exercise the logout path. */
  readonly meStatus?: number;
  readonly extraRoutes?: Record<string, StubRoute>;
}

export function stubAuthRoutes(options: AuthHarnessOptions = {}): AnyMock {
  const principal = options.principal === undefined ? makePrincipal() : options.principal;
  const session = options.session === undefined ? makeSession() : options.session;
  return stubFetch({
    '/v1/kyber/me': { status: options.meStatus ?? 200, body: principal },
    '/v1/kyber/auth/session': { status: options.meStatus ?? 200, body: session },
    ...options.extraRoutes,
  });
}

export function AuthHarness({ children }: { readonly children: ReactNode }) {
  // pollIntervalMs=0 disables the background timer so tests are deterministic.
  return <AuthProvider pollIntervalMs={0}>{children}</AuthProvider>;
}

export function renderWithAuth(
  ui: ReactElement,
  options: AuthHarnessOptions = {},
): RenderResult & { fetchStub: AnyMock } {
  const fetchStub = stubAuthRoutes(options);
  const result = render(<AuthHarness>{ui}</AuthHarness>);
  return Object.assign(result, { fetchStub });
}

// ── WebCrypto / WebAuthn / IndexedDB stubs ───────────────────────────────────

export interface SubtleCryptoStub {
  readonly generateKey: AnyMock;
  readonly exportKey: AnyMock;
  readonly sign: AnyMock;
}

/** Records the exact `extractable` argument the app passed to `generateKey`. */
export function stubSubtleCrypto(): SubtleCryptoStub {
  const privateKey = { type: 'private', extractable: false } as unknown as CryptoKey;
  const publicKey = { type: 'public', extractable: true } as unknown as CryptoKey;
  const generateKey = vi.fn(async () => ({ privateKey, publicKey }));
  const exportKey = vi.fn(async () => new Uint8Array([1, 2, 3, 4]).buffer);
  const sign = vi.fn(async () => new Uint8Array([9, 9, 9]).buffer);
  vi.stubGlobal('crypto', { subtle: { generateKey, exportKey, sign }, getRandomValues: (a: Uint8Array) => a });
  return { generateKey, exportKey, sign };
}

/** In-memory IndexedDB replacement for the device-trust key store. */
export function stubIndexedDb(): Map<string, unknown> {
  const store = new Map<string, unknown>();
  vi.stubGlobal('indexedDB', {
    open: () => {
      const request: Record<string, unknown> = { result: null, error: null };
      queueMicrotask(() => {
        request['result'] = {
          objectStoreNames: { contains: () => true },
          createObjectStore: () => undefined,
          close: () => undefined,
          transaction: () => ({
            objectStore: () => ({
              get: (key: string) => makeIdbRequest(store.get(key)),
              put: (value: unknown, key: string) => {
                store.set(key, value);
                return makeIdbRequest(key);
              },
              delete: (key: string) => {
                store.delete(key);
                return makeIdbRequest(undefined);
              },
            }),
          }),
        };
        (request['onsuccess'] as (() => void) | undefined)?.();
      });
      return request;
    },
  });
  return store;
}

function makeIdbRequest(result: unknown): Record<string, unknown> {
  const request: Record<string, unknown> = { result, error: null };
  queueMicrotask(() => {
    (request['onsuccess'] as (() => void) | undefined)?.();
  });
  return request;
}

export interface CredentialsStub {
  readonly create: AnyMock;
  readonly get: AnyMock;
}

export function stubWebAuthn(overrides: { create?: unknown; get?: unknown } = {}): CredentialsStub {
  const attestation = {
    id: 'cred_test_001',
    response: {
      clientDataJSON: new Uint8Array([1, 2, 3]).buffer,
      attestationObject: new Uint8Array([4, 5, 6]).buffer,
      getTransports: () => ['internal'],
    },
  };
  const create = (overrides.create ?? vi.fn(async () => attestation)) as AnyMock;
  const get = (overrides.get ?? vi.fn(async () => null)) as AnyMock;
  vi.stubGlobal('PublicKeyCredential', function PublicKeyCredentialStub() {});
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { ...globalThis.navigator, credentials: { create, get }, userAgent: 'Mozilla/5.0 (Macintosh) Chrome/1.0' },
  });
  return { create, get };
}

/** Removes WebAuthn entirely so unsupported-browser paths can be asserted. */
export function stubWebAuthnUnsupported(): void {
  vi.stubGlobal('PublicKeyCredential', undefined);
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { ...globalThis.navigator, credentials: undefined },
  });
}
