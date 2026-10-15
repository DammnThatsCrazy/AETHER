import type { SDKState } from './types';
import { type ReactNode, type ReactElement, Fragment, createElement } from 'react';

interface MutableSDKState {
  initialized: boolean;
  version: string;
  tenantId: string | null;
  workspaceId: string | null;
  platformId: string | null;
  sessionId: string | null;
  anonymousId: string | null;
  knownUserId: string | null;
  consentState: 'granted' | 'denied' | 'unknown';
  queueSize: number;
  lastDeliveryStatus: 'pending' | 'delivered' | 'failed' | 'idle';
  lastApiResponse: string | null;
  lastError: string | null;
}

let state: MutableSDKState = {
  initialized: false,
  version: '0.1.0-alpha.0',
  tenantId: null,
  workspaceId: null,
  platformId: null,
  sessionId: null,
  anonymousId: null,
  knownUserId: null,
  consentState: 'unknown',
  queueSize: 0,
  lastDeliveryStatus: 'idle',
  lastApiResponse: null,
  lastError: null,
};

export function getDebugState(): SDKState {
  return state as unknown as SDKState;
}

export function initSDK(config?: Record<string, unknown>): void {
  console.log('[Aether SDK] initSDK called', config);
  state.initialized = true;
  state.tenantId = String(config?.tenantId ?? 'demo-tenant');
  state.workspaceId = String(config?.workspaceId ?? 'demo-workspace');
  state.platformId = String(config?.platformId ?? 'react');
  state.sessionId = `session-${Date.now()}`;
  state.anonymousId = `anon-${Math.random().toString(36).slice(2, 11)}`;
  state.consentState = 'unknown';
  console.log('[Aether SDK] Initialized:', state);
}

export function emitHeartbeat(): void {
  console.log('[Aether SDK] emitHeartbeat');
  if (!state.initialized) {
    console.warn('[Aether SDK] emitHeartbeat called before initSDK');
    return;
  }
  state.lastDeliveryStatus = 'pending';
}

export function trackPageView(path: string, metadata?: Record<string, unknown>): void {
  console.log('[Aether SDK] trackPageView:', path, metadata);
  if (!state.initialized) {
    console.warn('[Aether SDK] trackPageView called before initSDK');
    return;
  }
}

export function trackEvent(name: string, properties?: Record<string, unknown>): void {
  console.log('[Aether SDK] trackEvent:', name, properties);
  if (!state.initialized) {
    console.warn('[Aether SDK] trackEvent called before initSDK');
    return;
  }
  state.queueSize += 1;
}

export function identifyUser(userId: string, traits?: Record<string, unknown>): void {
  console.log('[Aether SDK] identifyUser:', userId, traits);
  if (!state.initialized) {
    console.warn('[Aether SDK] identifyUser called before initSDK');
    return;
  }
  state.knownUserId = userId;
  state.anonymousId = null;
}

export function simulateConversion(revenue?: number): void {
  console.log('[Aether SDK] simulateConversion:', revenue);
  if (!state.initialized) {
    console.warn('[Aether SDK] simulateConversion called before initSDK');
    return;
  }
}

export function toggleConsent(consent: 'granted' | 'denied'): void {
  console.log('[Aether SDK] toggleConsent:', consent);
  if (!state.initialized) {
    console.warn('[Aether SDK] toggleConsent called before initSDK');
    return;
  }
  state.consentState = consent;
}

export function simulateOffline(): void {
  console.log('[Aether SDK] simulateOffline');
  if (!state.initialized) {
    console.warn('[Aether SDK] simulateOffline called before initSDK');
    return;
  }
  state.lastDeliveryStatus = 'failed';
  state.lastError = 'Network unavailable (simulated)';
}

export function flushQueue(): void {
  console.log('[Aether SDK] flushQueue');
  if (!state.initialized) {
    console.warn('[Aether SDK] flushQueue called before initSDK');
    return;
  }
  state.lastDeliveryStatus = 'delivered';
  state.lastApiResponse = '200 OK';
  state.queueSize = 0;
  state.lastError = null;
}

export function resetSession(): void {
  console.log('[Aether SDK] resetSession');
  state.sessionId = `session-${Date.now()}`;
  state.anonymousId = `anon-${Math.random().toString(36).slice(2, 11)}`;
  state.knownUserId = null;
  state.queueSize = 0;
  state.lastDeliveryStatus = 'idle';
  state.lastApiResponse = null;
  state.lastError = null;
}

// React provider + hooks stubs (mirrored from @aether/web/react)

export function AetherProvider({ children }: { children: ReactNode }): ReactElement {
  console.log('[Aether React] AetherProvider render');
  return createElement(Fragment, null, children);
}

export function useAether(): {
  initialized: boolean;
  sessionId: string | null;
  trackEvent: (name: string, props?: Record<string, unknown>) => void;
  identifyUser: (userId: string, traits?: Record<string, unknown>) => void;
  trackPageView: (path: string, metadata?: Record<string, unknown>) => void;
  flushQueue: () => void;
} {
  return {
    initialized: state.initialized,
    sessionId: state.sessionId,
    trackEvent: (name, props) => trackEvent(name, props),
    identifyUser: (userId, traits) => identifyUser(userId, traits),
    trackPageView: (path, metadata) => trackPageView(path, metadata),
    flushQueue,
  };
}

export function useAetherConsent(): {
  consentState: 'granted' | 'denied' | 'unknown';
  toggleConsent: (consent: 'granted' | 'denied') => void;
} {
  return {
    consentState: state.consentState,
    toggleConsent,
  };
}
