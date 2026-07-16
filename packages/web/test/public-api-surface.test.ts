// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import aether from '../src/index';

const COMMERCE_EMITTERS = {
  paymentInitiated: 'payment_initiated',
  paymentCompleted: 'payment_completed',
  paymentFailed: 'payment_failed',
  approvalRequested: 'approval_requested',
  approvalResolved: 'approval_resolved',
  entitlementGranted: 'entitlement_granted',
  entitlementRevoked: 'entitlement_revoked',
  accessGranted: 'access_granted',
  accessDenied: 'access_denied',
} as const;

const AGENT_EMITTERS = {
  registered: 'agent_registered',
  updated: 'agent_updated',
  authorized: 'agent_authorized',
  deauthorized: 'agent_deauthorized',
  capabilityGranted: 'agent_capability_granted',
  capabilityRevoked: 'agent_capability_revoked',
  taskCreated: 'agent_task_created',
  taskDecomposed: 'agent_task_decomposed',
  taskStarted: 'agent_task_started',
  taskCompleted: 'agent_task_completed',
  taskFailed: 'agent_task_failed',
  toolCalled: 'agent_tool_called',
  resourceRequested: 'agent_resource_requested',
  delegatedTask: 'agent_delegated_task',
  subagentSpawned: 'agent_subagent_spawned',
  policyEvaluated: 'agent_policy_evaluated',
  handoff: 'agent_handoff',
  escalatedToHuman: 'agent_escalated_to_human',
  outcomeRecorded: 'agent_outcome_recorded',
  task: 'agent_task',
  decision: 'agent_decision',
  interaction: 'a2h_interaction',
} as const;

const X402_EMITTERS = {
  resourceRequested: 'x402_resource_requested',
  paymentRequired: 'x402_payment_required',
  quoteReceived: 'x402_quote_received',
  authorizationRequested: 'x402_authorization_requested',
  authorizationResolved: 'x402_authorization_resolved',
  paymentIntentCreated: 'x402_payment_intent_created',
  paymentSubmitted: 'x402_payment_submitted',
  paymentSettled: 'x402_payment_settled',
  paymentFailed: 'x402_payment_failed',
  paymentTimeout: 'x402_payment_timeout',
  receiptVerified: 'x402_receipt_verified',
  accessGranted: 'x402_access_granted',
  accessDenied: 'x402_access_denied',
  refundOrReversal: 'x402_refund_or_reversal',
  payment: 'x402_payment',
} as const;

function installFetchCapture() {
  const sent: Array<{ type: string }> = [];
  globalThis.fetch = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
    if (typeof init?.body === 'string') {
      const body = JSON.parse(init.body);
      if (Array.isArray(body.batch)) sent.push(...body.batch);
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ accepted: 200, duplicates: 0, rejected: 0, events: [] }),
      text: async () => '{}',
    } as Response;
  });
  return sent;
}

function initialize() {
  aether.init({
    apiKey: 'test-key',
    endpoint: 'https://api.test',
    advanced: { batchSize: 200, flushInterval: 60_000 },
    modules: { autoDiscovery: false, performance: false, ecommerce: false },
  });
  aether.consent.grant([
    'analytics',
    'marketing',
    'agent',
    'commerce',
  ]);
}

describe('public SDK surface', () => {
  beforeEach(() => {
    localStorage.clear();
    installFetchCapture();
  });

  afterEach(() => {
    aether.destroy();
    vi.restoreAllMocks();
  });

  it('emits every thin commerce, agent, and x402 event through the canonical queue', async () => {
    const sent = installFetchCapture();
    initialize();

    for (const method of Object.keys(COMMERCE_EMITTERS)) {
      (aether.commerce as any)[method]({ id: method });
    }
    for (const method of Object.keys(AGENT_EMITTERS)) {
      (aether.agent as any)[method]({ id: method });
    }
    for (const method of Object.keys(X402_EMITTERS)) {
      (aether.x402 as any)[method]({ id: method });
    }

    await aether.flush();

    const eventTypes = new Set(sent.map((event) => event.type));
    for (const expected of [
      ...Object.values(COMMERCE_EMITTERS),
      ...Object.values(AGENT_EMITTERS),
      ...Object.values(X402_EMITTERS),
    ]) {
      expect(eventTypes).toContain(expected);
    }
  });

  it('keeps pre-initialization wallet, consent, reward, and module proxies safe', async () => {
    expect(() => aether.init({ apiKey: '' } as any)).toThrow(/apiKey is required/);
    aether.pauseJourney();
    aether.continueJourney('step');
    aether.completeJourney();
    aether.abandonJourney();
    aether.checkpointJourney('step');

    const walletMethods = [
      'connect', 'connectSVM', 'connectBTC', 'connectSUI', 'connectNEAR',
      'connectTRON', 'connectCosmos', 'connectAptos', 'connectTON',
      'connectStarknet', 'connectCardano', 'connectSubstrate',
      'connectAlgorand', 'connectHedera', 'connectStellar', 'connectICP',
    ];
    for (const method of walletMethods) {
      expect(() => (aether.wallet as any)[method]('test-address')).not.toThrow();
    }
    aether.wallet.disconnect();
    aether.wallet.transaction('0xtest');
    expect(aether.wallet.getInfo()).toBeNull();
    expect(aether.wallet.getWallets()).toEqual([]);
    expect(aether.wallet.getWalletsByVM('evm')).toEqual([]);
    expect(typeof aether.wallet.onWalletChange(() => {})).toBe('function');

    expect(aether.consent.getState().analytics).toBe(false);
    aether.consent.grant(['analytics']);
    aether.consent.revoke(['analytics']);
    aether.consent.showBanner();
    aether.consent.hideBanner();
    expect(typeof aether.consent.onUpdate(() => {})).toBe('function');

    expect((aether.ecommerce as any).trackAddToCart({ sku: 'A-1' })).toBeUndefined();
    expect((aether.featureFlag as any).isEnabled('flag')).toBeUndefined();
    expect((aether.heatmap as any).start()).toBeUndefined();
    expect((aether.funnel as any).tagEvent('event')).toBeUndefined();
    expect((aether.forms as any).trackForm('form')).toBeUndefined();

    await expect(aether.rewards.checkEligibility('user', 'reward')).rejects.toThrow(/not initialized/);
    await expect(aether.rewards.getClaimPayload('user', 'reward')).rejects.toThrow(/not initialized/);
    await expect(aether.rewards.submitClaim('0xtest', 'reward')).rejects.toThrow(/not initialized/);
  });

  it('tracks the complete public journey lifecycle and plugin hooks', async () => {
    const sent = installFetchCapture();
    initialize();

    const plugin = { name: 'surface-test', init: vi.fn(), destroy: vi.fn() };
    aether.use(plugin);
    expect(plugin.init).toHaveBeenCalledWith(aether);

    expect(aether.startJourney('checkout', { journeyId: 'journey-1' })?.journeyStatus).toBe('started');
    aether.pauseJourney('hidden');
    aether.resumeJourney('visible');
    aether.continueJourney('payment');
    aether.checkpointJourney('confirm');
    expect(aether.getCurrentJourney()?.journeyId).toBe('journey-1');
    aether.completeJourney('paid');
    expect(aether.getCurrentJourney()).toBeNull();

    aether.startJourney('support', { journeyId: 'journey-2' });
    aether.abandonJourney('closed');
    aether.resumeJourney('cross-device', { journeyId: 'journey-3' });
    const unsubscribe = aether.onJourneyResumed(() => {});
    unsubscribe();

    aether.track('custom-event', { source: 'surface-test' });
    aether.conversion('signup', 1);
    aether.error('problem', new Error('boom'));
    await aether.flush();

    const eventTypes = new Set(sent.map((event) => event.type));
    for (const expected of [
      'journey_started',
      'journey_paused',
      'journey_resumed',
      'journey_continued',
      'journey_checkpoint',
      'journey_completed',
      'journey_abandoned',
      'track',
      'conversion',
      'error',
    ]) {
      expect(eventTypes).toContain(expected);
    }

    aether.destroy();
    expect(plugin.destroy).toHaveBeenCalledOnce();
  });
});
