/**
 * Typed Aether mobile API client.
 *
 * Wraps the flag-gated mobile/continuity/sync backend surfaces (all snake_case
 * wire contracts) behind typed methods. Every response type is the corresponding
 * `@aether/shared` contract twin, so the client cannot drift from the backend
 * without the parity tests catching it.
 */
import type {
  ClientSyncResponse,
  ContinuationContext,
  InstallationPlatform,
  MobileInstallation,
  PushProvider,
  PushSubscription,
} from '@aether/shared';

import type { MobileConfig } from './config';
import { normalizeBaseUrl } from './config';
import { HttpClient, type HttpClientDeps } from './http';

/** Body of `POST /v1/mobile/installations` (the server forces `app_kind`). */
export interface InstallationRegisterInput {
  installation_id?: string;
  platform: InstallationPlatform;
  bundle_id: string;
  environment: string;
  device_name?: string;
  push_token?: string;
  push_provider?: PushProvider;
}

export interface RegistrationResult {
  installation: MobileInstallation;
  subscription: PushSubscription | null;
}

/** Body of `POST /v1/mobile/installations/{id}/subscriptions`. */
export interface SubscriptionInput {
  platform: InstallationPlatform;
  provider: PushProvider;
  push_token: string;
  environment: string;
}

/** Bounded, reference-only projection returned by deep-link resolution. */
export interface DeepLinkContinuation {
  id: string;
  app_kind: string;
  surface: string;
  summary: unknown;
  canonical_context: unknown;
  sensitivity: string;
  freshness?: string | null;
  state_revision?: number;
  updated_at?: string;
  expires_at?: string | null;
}

export interface DeepLinkResolution {
  resolved: boolean;
  reason?: string;
  requires_step_up?: boolean;
  continuation?: DeepLinkContinuation;
}

export class AetherMobileClient {
  private readonly http: HttpClient;

  constructor(private readonly config: MobileConfig, deps: HttpClientDeps) {
    this.http = new HttpClient(normalizeBaseUrl(config.apiBaseUrl), deps);
  }

  // ── Installations & push ──────────────────────────────────────────────
  registerInstallation(input: InstallationRegisterInput): Promise<RegistrationResult> {
    return this.http.request<RegistrationResult>('POST', '/v1/mobile/installations', input);
  }

  async listInstallations(): Promise<MobileInstallation[]> {
    const data = await this.http.request<{ installations: MobileInstallation[] }>(
      'GET',
      '/v1/mobile/installations',
    );
    return data.installations;
  }

  getInstallation(id: string): Promise<MobileInstallation> {
    return this.http.request<MobileInstallation>('GET', `/v1/mobile/installations/${encodeURIComponent(id)}`);
  }

  revokeInstallation(id: string): Promise<MobileInstallation> {
    return this.http.request<MobileInstallation>('DELETE', `/v1/mobile/installations/${encodeURIComponent(id)}`);
  }

  addSubscription(installationId: string, input: SubscriptionInput): Promise<PushSubscription> {
    return this.http.request<PushSubscription>(
      'POST',
      `/v1/mobile/installations/${encodeURIComponent(installationId)}/subscriptions`,
      input,
    );
  }

  // ── Deep links ────────────────────────────────────────────────────────
  resolveDeepLink(installationId: string, continuationId: string): Promise<DeepLinkResolution> {
    return this.http.request<DeepLinkResolution>('POST', '/v1/mobile/deep-links/resolve', {
      installation_id: installationId,
      continuation_id: continuationId,
    });
  }

  // ── Continuity ────────────────────────────────────────────────────────
  async recentContinuations(): Promise<ContinuationContext[]> {
    const data = await this.http.request<{ continuations: ContinuationContext[] }>(
      'GET',
      '/v1/continuations/recent',
    );
    return data.continuations;
  }

  getContinuation(id: string): Promise<ContinuationContext> {
    return this.http.request<ContinuationContext>('GET', `/v1/continuations/${encodeURIComponent(id)}`);
  }

  // ── Client-sync feed ──────────────────────────────────────────────────
  clientSync(cursor?: string): Promise<ClientSyncResponse> {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
    return this.http.request<ClientSyncResponse>('GET', `/v1/client-sync${query}`);
  }
}
