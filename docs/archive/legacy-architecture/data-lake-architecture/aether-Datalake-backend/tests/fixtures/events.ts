// =============================================================================
// TEST FIXTURES — Mock data for ingestion layer testing
// =============================================================================

import type { BaseEvent, BatchPayload, ApiKeyRecord, RateLimitConfig } from '@aether/common';
import { sha256 } from '@aether/common';

// =============================================================================
// VALID EVENTS
// =============================================================================

export function createValidEvent(overrides?: Partial<BaseEvent>): BaseEvent {
  return {
    id: `evt_${Math.random().toString(36).slice(2, 10)}`,
    type: 'track',
    timestamp: new Date().toISOString(),
    sessionId: 'sess_abc123',
    anonymousId: 'anon_xyz789',
    event: 'button_click',
    properties: {
      buttonId: 'cta-signup',
      page: '/landing',
      value: 42,
    },
    context: {
      library: { name: '@aether/sdk', version: '4.0.0' },
      page: {
        url: 'https://example.com/landing',
        path: '/landing',
        title: 'Landing Page',
        referrer: 'https://google.com',
        search: '?utm_source=google',
        hash: '',
      },
      device: {
        type: 'desktop',
        browser: 'Chrome',
        browserVersion: '122.0',
        os: 'macOS',
        osVersion: '14.3',
        screenWidth: 2560,
        screenHeight: 1440,
        viewportWidth: 1920,
        viewportHeight: 1080,
        pixelRatio: 2,
        language: 'en-US',
        cookieEnabled: true,
        online: true,
      },
      campaign: {
        source: 'google',
        medium: 'cpc',
        campaign: 'spring_2024',
      },
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    },
    ...overrides,
  };
}

export function createPageEvent(url: string = 'https://example.com/pricing'): BaseEvent {
  return createValidEvent({
    type: 'page',
    event: undefined,
    properties: {
      url,
      path: '/pricing',
      title: 'Pricing',
      referrer: 'https://example.com/',
    },
  });
}

export function createIdentifyEvent(): BaseEvent {
  return createValidEvent({
    type: 'identify',
    userId: 'user_001',
    event: undefined,
    properties: {
      email: 'user@example.com',
      name: 'Test User',
      plan: 'pro',
    },
  });
}

export function createConversionEvent(): BaseEvent {
  return createValidEvent({
    type: 'conversion',
    event: 'purchase',
    properties: {
      value: 99.99,
      currency: 'USD',
      orderId: 'order_123',
    },
  });
}

export function createWalletEvent(): BaseEvent {
  return createValidEvent({
    type: 'wallet',
    event: undefined,
    properties: {
      action: 'connect',
      address: '0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18',
      chainId: 1,
      walletType: 'MetaMask',
    },
  });
}

export function createPerformanceEvent(): BaseEvent {
  return createValidEvent({
    type: 'performance',
    event: undefined,
    properties: {
      lcp: 1250,
      fid: 18,
      cls: 0.05,
      ttfb: 180,
      fcp: 800,
    },
  });
}

// =============================================================================
// BATCH PAYLOADS
// =============================================================================

export function createValidBatch(size: number = 5): BatchPayload {
  return {
    batch: Array.from({ length: size }, () => createValidEvent()),
    sentAt: new Date().toISOString(),
    context: { library: { name: '@aether/sdk', version: '4.0.0' } },
  };
}

export function createMixedBatch(): BatchPayload {
  return {
    batch: [
      createValidEvent(),
      createPageEvent(),
      createIdentifyEvent(),
      createConversionEvent(),
      createWalletEvent(),
      createPerformanceEvent(),
    ],
    sentAt: new Date().toISOString(),
  };
}

// =============================================================================
// INVALID EVENTS
// =============================================================================

export function createInvalidEvent_MissingId(): Record<string, unknown> {
  return {
    type: 'track',
    timestamp: new Date().toISOString(),
    sessionId: 'sess_abc',
    anonymousId: 'anon_xyz',
    properties: {},
    context: { library: { name: '@aether/sdk', version: '4.0.0' } },
  };
}

export function createInvalidEvent_BadType(): Record<string, unknown> {
  return {
    id: 'evt_123',
    type: 'INVALID_TYPE',
    timestamp: new Date().toISOString(),
    sessionId: 'sess_abc',
    anonymousId: 'anon_xyz',
  };
}

export function createInvalidEvent_FutureTimestamp(): Record<string, unknown> {
  const future = new Date(Date.now() + 600_000).toISOString(); // 10 min ahead
  return {
    id: 'evt_future',
    type: 'track',
    timestamp: future,
    sessionId: 'sess_abc',
    anonymousId: 'anon_xyz',
  };
}

export function createEventWithPII(): BaseEvent {
  return createValidEvent({
    properties: {
      note: 'Card number 4111-1111-1111-1111 used for payment',
      ssn: 'SSN is 123-45-6789',
      normalField: 'safe value',
    },
  });
}

export function createEventWithConsent(consent: { analytics: boolean; marketing: boolean; web3: boolean }): BaseEvent {
  return createValidEvent({
    context: {
      ...createValidEvent().context,
      consent: {
        ...consent,
        updatedAt: new Date().toISOString(),
        policyVersion: '1.0',
      },
    },
  });
}

// =============================================================================
// API KEY RECORDS
// =============================================================================

export const TEST_API_KEY = 'ak_test_key_abcdefghijklmnop';

export function createTestApiKeyRecord(overrides?: Partial<ApiKeyRecord>): ApiKeyRecord {
  return {
    key: TEST_API_KEY,
    keyHash: sha256(TEST_API_KEY),
    projectId: 'proj_test_001',
    projectName: 'Test Project',
    organizationId: 'org_test',
    environment: 'development',
    permissions: { write: true, read: true, admin: false },
    rateLimits: {
      eventsPerSecond: 100,
      eventsPerMinute: 5000,
      batchSizeLimit: 500,
      dailyEventLimit: 1_000_000,
    },
    createdAt: new Date().toISOString(),
    isActive: true,
    ...overrides,
  };
}

export function createRateLimits(overrides?: Partial<RateLimitConfig>): RateLimitConfig {
  return {
    eventsPerSecond: 100,
    eventsPerMinute: 5000,
    batchSizeLimit: 500,
    dailyEventLimit: 1_000_000,
    ...overrides,
  };
}
