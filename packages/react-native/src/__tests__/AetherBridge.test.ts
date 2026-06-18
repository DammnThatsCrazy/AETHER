import { describe, it, expect, vi, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mock react-native before importing anything that depends on it.
// vi.hoisted() keeps the references stable after hoisting.
// ---------------------------------------------------------------------------
const { nativeMethods, platformRef } = vi.hoisted(() => ({
  nativeMethods: {
    walletConnect:              vi.fn(),
    walletDisconnect:           vi.fn(),
    walletTransaction:          vi.fn(),
    contractAction:             vi.fn(),
    trackWalletConnectSession:  vi.fn(),
    getWalletCapabilities:      vi.fn(async () => ({
      connected: true,
      addresses: [{ address: '0xabc', vm: 'evm' }],
      supportedVMs: ['evm'],
    })),
    trackApplePayPayment:       vi.fn(),
    trackGooglePayPayment:      vi.fn(),
    paymentInitiated:           vi.fn(),
    paymentCompleted:           vi.fn(),
    paymentFailed:              vi.fn(),
    approvalRequested:          vi.fn(),
    approvalResolved:           vi.fn(),
    entitlementGranted:         vi.fn(),
    entitlementRevoked:         vi.fn(),
    getCurrentJourney:          vi.fn(async () => ({ name: 'onboarding' })),
    getIdentity:                vi.fn(async () => ({ anonymousId: 'anon-1', traits: {} })),
    accessGranted:              vi.fn(),
    accessDenied:               vi.fn(),
    agentTask:                  vi.fn(),
    agentDecision:              vi.fn(),
    a2hInteraction:             vi.fn(),
    x402Payment:                vi.fn(),
    initialize:                 vi.fn(),
    track:                      vi.fn(),
    screenView:                 vi.fn(),
    conversion:                 vi.fn(),
    getFingerprint:             vi.fn(async () => 'fp-abc123'),
    handleDeepLink:             vi.fn(),
    trackPushOpened:            vi.fn(),
    runExperiment:              vi.fn(async (_id: string, variants: string[]) => variants[0]),
    getExperimentAssignment:    vi.fn(async () => 'variant_a'),
    hydrateIdentity:            vi.fn(),
    startJourney:               vi.fn(),
    pauseJourney:               vi.fn(),
    resumeJourney:              vi.fn(),
    continueJourney:            vi.fn(),
    completeJourney:            vi.fn(),
    abandonJourney:             vi.fn(),
    checkpointJourney:          vi.fn(),
    flush:                      vi.fn(),
    reset:                      vi.fn(),
    getConsentState:            vi.fn(async () => ({
      analytics: true, marketing: false, web3: false, agent: false, commerce: false,
      updatedAt: '', policyVersion: '',
    })),
    grantConsent:               vi.fn(),
    revokeConsent:              vi.fn(),
    // Agent lifecycle new methods
    agentRegistered:            vi.fn(),
    agentUpdated:               vi.fn(),
    agentAuthorized:            vi.fn(),
    agentDeauthorized:          vi.fn(),
    agentCapabilityGranted:     vi.fn(),
    agentCapabilityRevoked:     vi.fn(),
    agentTaskCreated:           vi.fn(),
    agentTaskDecomposed:        vi.fn(),
    agentTaskStarted:           vi.fn(),
    agentTaskCompleted:         vi.fn(),
    agentTaskFailed:            vi.fn(),
    agentToolCalled:            vi.fn(),
    agentResourceRequested:     vi.fn(),
    agentDelegatedTask:         vi.fn(),
    agentSubagentSpawned:       vi.fn(),
    agentPolicyEvaluated:       vi.fn(),
    agentHandoff:               vi.fn(),
    agentEscalatedToHuman:      vi.fn(),
    agentOutcomeRecorded:       vi.fn(),
    // x402 new methods
    x402ResourceRequested:      vi.fn(),
    x402PaymentRequired:        vi.fn(),
    x402QuoteReceived:          vi.fn(),
    x402AuthorizationRequested: vi.fn(),
    x402AuthorizationResolved:  vi.fn(),
    x402PaymentIntentCreated:   vi.fn(),
    x402PaymentSubmitted:       vi.fn(),
    x402PaymentSettled:         vi.fn(),
    x402PaymentFailed:          vi.fn(),
    x402PaymentTimeout:         vi.fn(),
    x402ReceiptVerified:        vi.fn(),
    x402AccessGranted:          vi.fn(),
    x402AccessDenied:           vi.fn(),
    x402RefundOrReversal:       vi.fn(),
    // Rewards
    rewardActionQueued:         vi.fn(),
    rewardProofGenerated:       vi.fn(),
    rewardDelivered:            vi.fn(),
    rewardClaimSubmitted:       vi.fn(),
    // Ecommerce additions
    trackRemoveFromCart:        vi.fn(),
    trackApplyCoupon:           vi.fn(),
    trackBeginCheckout:         vi.fn(),
  },
  platformRef: { OS: 'ios' as string },
}));

vi.mock('react-native', () => ({
  NativeModules: { AetherNative: nativeMethods },
  NativeEventEmitter: class { addListener = vi.fn(() => ({ remove: vi.fn() })); },
  Platform: platformRef,
}));

// Import the pure bridge (no JSX) after the mock is in place.
import Aether from '../bridge';

describe('Aether RN bridge — wallet methods', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('wallet.connect delegates to walletConnect', () => {
    Aether.wallet.connect('0xABC', { type: 'metamask', chainId: 1 });
    expect(nativeMethods.walletConnect).toHaveBeenCalledWith('0xABC', { type: 'metamask', chainId: 1 });
  });

  it('wallet.disconnect delegates to walletDisconnect', () => {
    Aether.wallet.disconnect('0xABC');
    expect(nativeMethods.walletDisconnect).toHaveBeenCalledWith('0xABC');
  });

  it('wallet.transaction delegates to walletTransaction', () => {
    Aether.wallet.transaction('0xTX', { gas: 21000 });
    expect(nativeMethods.walletTransaction).toHaveBeenCalledWith('0xTX', { gas: 21000 });
  });

  it('wallet.walletConnectSession calls trackWalletConnectSession', () => {
    Aether.wallet.walletConnectSession('topic-abc', { address: '0xabc', chainId: '1' });
    expect(nativeMethods.trackWalletConnectSession).toHaveBeenCalledWith(
      'topic-abc',
      { address: '0xabc', chainId: '1' },
    );
  });

  it('wallet.walletConnectSession passes empty options when none provided', () => {
    Aether.wallet.walletConnectSession('topic-xyz');
    expect(nativeMethods.trackWalletConnectSession).toHaveBeenCalledWith('topic-xyz', {});
  });

  it('wallet.getCapabilities resolves with native payload', async () => {
    const caps = await Aether.wallet.getCapabilities();
    expect(caps).toMatchObject({ connected: true, supportedVMs: ['evm'] });
  });

  it('wallet.getCapabilities falls back to empty payload when native returns nothing', async () => {
    nativeMethods.getWalletCapabilities.mockResolvedValueOnce(null);
    const caps = await Aether.wallet.getCapabilities();
    expect(caps).toEqual({ connected: false, addresses: [], supportedVMs: [] });
  });
});

describe('Aether RN bridge — commerce Apple/Google Pay', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('commerce.applePayPayment calls trackApplePayPayment on iOS', () => {
    platformRef.OS = 'ios';
    Aether.commerce.applePayPayment('completed', { amount: 9.99, currency: 'USD' });
    expect(nativeMethods.trackApplePayPayment).toHaveBeenCalledWith('completed', { amount: 9.99, currency: 'USD' });
  });

  it('commerce.applePayPayment is a no-op on Android', () => {
    platformRef.OS = 'android';
    Aether.commerce.applePayPayment('completed', { amount: 9.99, currency: 'USD' });
    expect(nativeMethods.trackApplePayPayment).not.toHaveBeenCalled();
  });

  it('commerce.googlePayPayment calls trackGooglePayPayment on Android', () => {
    platformRef.OS = 'android';
    Aether.commerce.googlePayPayment('initiated', { amount: 5.00, currency: 'EUR' });
    expect(nativeMethods.trackGooglePayPayment).toHaveBeenCalledWith('initiated', { amount: 5.00, currency: 'EUR' });
  });

  it('commerce.googlePayPayment is a no-op on iOS', () => {
    platformRef.OS = 'ios';
    Aether.commerce.googlePayPayment('initiated', { amount: 5.00, currency: 'EUR' });
    expect(nativeMethods.trackGooglePayPayment).not.toHaveBeenCalled();
  });

  it('commerce.applePayPayment passes empty options when none provided', () => {
    platformRef.OS = 'ios';
    Aether.commerce.applePayPayment('failed');
    expect(nativeMethods.trackApplePayPayment).toHaveBeenCalledWith('failed', {});
  });
});

describe('Aether RN bridge — x402', () => {
  it('x402.payment delegates with all parameters', () => {
    Aether.x402.payment('pay_1', '1.50', 'USDC', 'base', { orderId: 'ord_1' });
    expect(nativeMethods.x402Payment).toHaveBeenCalledWith('pay_1', '1.50', 'USDC', 'base', { orderId: 'ord_1' });
  });
});

describe('Aether RN bridge — core API', () => {
  beforeEach(() => vi.clearAllMocks());

  it('track delegates event and properties', () => {
    Aether.track('purchase', { amount: 10 });
    expect(nativeMethods.track).toHaveBeenCalledWith('purchase', { amount: 10 });
  });

  it('track uses empty properties when none provided', () => {
    Aether.track('view');
    expect(nativeMethods.track).toHaveBeenCalledWith('view', {});
  });

  it('flush delegates to native flush', () => {
    Aether.flush();
    expect(nativeMethods.flush).toHaveBeenCalled();
  });

  it('reset delegates to native reset', () => {
    Aether.reset();
    expect(nativeMethods.reset).toHaveBeenCalled();
  });

  it('hydrateIdentity delegates IdentityData', () => {
    const data = { userId: 'u1', walletAddress: '0xabc' };
    Aether.hydrateIdentity(data);
    expect(nativeMethods.hydrateIdentity).toHaveBeenCalledWith(data);
  });

  it('screenView delegates screen name', () => {
    Aether.screenView('HomeScreen', { source: 'push' });
    expect(nativeMethods.screenView).toHaveBeenCalledWith('HomeScreen', { source: 'push' });
  });

  it('conversion delegates event and value', () => {
    Aether.conversion('signup', 0, { plan: 'pro' });
    expect(nativeMethods.conversion).toHaveBeenCalledWith('signup', 0, { plan: 'pro' });
  });

  it('handleDeepLink delegates url', () => {
    Aether.handleDeepLink('myapp://promo?code=ABC');
    expect(nativeMethods.handleDeepLink).toHaveBeenCalledWith('myapp://promo?code=ABC');
  });

  it('trackPushOpened delegates notification data', () => {
    Aether.trackPushOpened({ campaign: 'promo_1' });
    expect(nativeMethods.trackPushOpened).toHaveBeenCalledWith({ campaign: 'promo_1' });
  });

  it('getFingerprint resolves with native fingerprint', async () => {
    const fp = await Aether.getFingerprint();
    expect(fp).toBe('fp-abc123');
  });

  it('getFingerprint returns empty string when native throws', async () => {
    nativeMethods.getFingerprint.mockRejectedValueOnce(new Error('not available'));
    const fp = await Aether.getFingerprint();
    expect(fp).toBe('');
  });
});

describe('Aether RN bridge — journey API', () => {
  beforeEach(() => vi.clearAllMocks());

  it('startJourney delegates name and properties', () => {
    Aether.startJourney('onboarding', { step: 1 });
    expect(nativeMethods.startJourney).toHaveBeenCalledWith('onboarding', { step: 1 });
  });

  it('pauseJourney delegates reason', () => {
    Aether.pauseJourney('user_inactive');
    expect(nativeMethods.pauseJourney).toHaveBeenCalledWith('user_inactive', {});
  });

  it('resumeJourney delegates reason', () => {
    Aether.resumeJourney('push_notification');
    expect(nativeMethods.resumeJourney).toHaveBeenCalledWith('push_notification', {});
  });

  it('continueJourney delegates step name', () => {
    Aether.continueJourney('step_2');
    expect(nativeMethods.continueJourney).toHaveBeenCalledWith('step_2', {});
  });

  it('completeJourney delegates reason', () => {
    Aether.completeJourney('success');
    expect(nativeMethods.completeJourney).toHaveBeenCalledWith('success', {});
  });

  it('abandonJourney delegates reason', () => {
    Aether.abandonJourney('user_quit');
    expect(nativeMethods.abandonJourney).toHaveBeenCalledWith('user_quit', {});
  });

  it('checkpointJourney delegates step name', () => {
    Aether.checkpointJourney('payment_entered');
    expect(nativeMethods.checkpointJourney).toHaveBeenCalledWith('payment_entered', {});
  });
});

describe('Aether RN bridge — consent API', () => {
  beforeEach(() => vi.clearAllMocks());

  it('consent.getState resolves with native state', async () => {
    const state = await Aether.consent.getState();
    expect(state.analytics).toBe(true);
  });

  it('consent.grant delegates purposes array', () => {
    Aether.consent.grant(['analytics', 'marketing']);
    expect(nativeMethods.grantConsent).toHaveBeenCalledWith(['analytics', 'marketing']);
  });

  it('consent.revoke delegates purposes array', () => {
    Aether.consent.revoke(['marketing']);
    expect(nativeMethods.revokeConsent).toHaveBeenCalledWith(['marketing']);
  });

  it('consent.getState falls back when native returns nothing', async () => {
    nativeMethods.getConsentState.mockReturnValueOnce(undefined);
    const state = await Aether.consent.getState();
    expect(state.analytics).toBe(false);
    expect(state.marketing).toBe(false);
    expect(state.web3).toBe(false);
  });
});

describe('Aether RN bridge — commerce (standard payments)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('commerce.paymentInitiated delegates all params', () => {
    Aether.commerce.paymentInitiated('p1', 29.99, 'USD', { orderId: 'o1' });
    expect(nativeMethods.paymentInitiated).toHaveBeenCalledWith('p1', 29.99, 'USD', { orderId: 'o1' });
  });

  it('commerce.paymentCompleted delegates all params', () => {
    Aether.commerce.paymentCompleted('p1', 29.99, 'USD');
    expect(nativeMethods.paymentCompleted).toHaveBeenCalledWith('p1', 29.99, 'USD', {});
  });

  it('commerce.paymentFailed delegates paymentId and reason', () => {
    Aether.commerce.paymentFailed('p1', 'declined');
    expect(nativeMethods.paymentFailed).toHaveBeenCalledWith('p1', 'declined', {});
  });

  it('commerce.approvalRequested delegates id and scope', () => {
    Aether.commerce.approvalRequested('apr1', 'erc20_spend');
    expect(nativeMethods.approvalRequested).toHaveBeenCalledWith('apr1', 'erc20_spend', {});
  });

  it('commerce.approvalResolved delegates id and approved flag', () => {
    Aether.commerce.approvalResolved('apr1', true);
    expect(nativeMethods.approvalResolved).toHaveBeenCalledWith('apr1', true, {});
  });

  it('commerce.accessGranted delegates resource', () => {
    Aether.commerce.accessGranted('premium_content');
    expect(nativeMethods.accessGranted).toHaveBeenCalledWith('premium_content', {});
  });

  it('commerce.accessDenied delegates resource and reason', () => {
    Aether.commerce.accessDenied('premium_content', 'no_subscription');
    expect(nativeMethods.accessDenied).toHaveBeenCalledWith('premium_content', 'no_subscription', {});
  });

  it('commerce.entitlementGranted delegates entitlementId', () => {
    Aether.commerce.entitlementGranted('ent_pro');
    expect(nativeMethods.entitlementGranted).toHaveBeenCalledWith('ent_pro', {});
  });

  it('commerce.entitlementRevoked delegates entitlementId', () => {
    Aether.commerce.entitlementRevoked('ent_pro');
    expect(nativeMethods.entitlementRevoked).toHaveBeenCalledWith('ent_pro', {});
  });
});

describe('Aether RN bridge — consent onUpdate', () => {
  it('consent.onUpdate returns an unsubscribe function', () => {
    const callback = vi.fn();
    const unsub = Aether.consent.onUpdate(callback);
    expect(typeof unsub).toBe('function');
    unsub(); // call cleanup to cover the return function
  });
});

describe('Aether RN bridge — query APIs', () => {
  beforeEach(() => vi.clearAllMocks());

  it('getCurrentJourney resolves with native journey', async () => {
    const journey = await Aether.getCurrentJourney();
    expect(journey).toEqual({ name: 'onboarding' });
  });

  it('getIdentity resolves with native identity', async () => {
    const identity = await Aether.getIdentity();
    expect(identity.anonymousId).toBe('anon-1');
  });

  it('wallet.contractAction delegates contract and action', () => {
    Aether.wallet.contractAction('0xContract', 'mint', { tokenId: 1 });
    expect(nativeMethods.contractAction).toHaveBeenCalledWith('0xContract', 'mint', { tokenId: 1 });
  });
});

describe('Aether RN bridge — experiments API', () => {
  beforeEach(() => vi.clearAllMocks());

  it('experiments.run resolves with first variant by default', async () => {
    const variant = await Aether.experiments.run('exp_1', ['control', 'treatment']);
    expect(nativeMethods.runExperiment).toHaveBeenCalledWith('exp_1', ['control', 'treatment']);
    expect(variant).toBe('control');
  });

  it('experiments.getAssignment resolves with native assignment', async () => {
    const assignment = await Aether.experiments.getAssignment('exp_1');
    expect(nativeMethods.getExperimentAssignment).toHaveBeenCalledWith('exp_1');
    expect(assignment).toBe('variant_a');
  });
});

describe('Aether RN bridge — agent API', () => {
  beforeEach(() => vi.clearAllMocks());

  it('agent.task delegates taskId and actorId', () => {
    Aether.agent.task('t1', 'agent_1', { step: 'classify' });
    expect(nativeMethods.agentTask).toHaveBeenCalledWith('t1', 'agent_1', { step: 'classify' });
  });

  it('agent.decision delegates decisionId and actorId', () => {
    Aether.agent.decision('d1', 'agent_1');
    expect(nativeMethods.agentDecision).toHaveBeenCalledWith('d1', 'agent_1', {});
  });

  it('agent.a2hInteraction delegates interactionId and actorId', () => {
    Aether.agent.a2hInteraction('i1', 'agent_1');
    expect(nativeMethods.a2hInteraction).toHaveBeenCalledWith('i1', 'agent_1', {});
  });
});

describe('Aether RN bridge — granular agent lifecycle', () => {
  beforeEach(() => vi.clearAllMocks());

  it('agent.registered delegates agentId', () => {
    Aether.agent.registered('agent-1', { model: 'gpt-4' });
    expect(nativeMethods.agentRegistered).toHaveBeenCalledWith('agent-1', { model: 'gpt-4' });
  });
  it('agent.taskCreated delegates taskId and actorId', () => {
    Aether.agent.taskCreated('task-1', 'actor-1');
    expect(nativeMethods.agentTaskCreated).toHaveBeenCalledWith('task-1', 'actor-1', {});
  });
  it('agent.taskCompleted delegates taskId', () => {
    Aether.agent.taskCompleted('task-1');
    expect(nativeMethods.agentTaskCompleted).toHaveBeenCalledWith('task-1', {});
  });
  it('agent.taskFailed delegates taskId and reason', () => {
    Aether.agent.taskFailed('task-1', 'timeout');
    expect(nativeMethods.agentTaskFailed).toHaveBeenCalledWith('task-1', 'timeout', {});
  });
  it('agent.escalatedToHuman delegates taskId', () => {
    Aether.agent.escalatedToHuman('task-1', 'requires approval');
    expect(nativeMethods.agentEscalatedToHuman).toHaveBeenCalledWith('task-1', 'requires approval', {});
  });
  it('agent.outcomeRecorded delegates taskId and outcome', () => {
    Aether.agent.outcomeRecorded('task-1', 'success');
    expect(nativeMethods.agentOutcomeRecorded).toHaveBeenCalledWith('task-1', 'success', {});
  });
});

describe('Aether RN bridge — granular x402 lifecycle', () => {
  beforeEach(() => vi.clearAllMocks());

  it('x402.resourceRequested delegates resourceId', () => {
    Aether.x402.resourceRequested('res-1');
    expect(nativeMethods.x402ResourceRequested).toHaveBeenCalledWith('res-1', {});
  });
  it('x402.paymentRequired delegates resourceId amount currency', () => {
    Aether.x402.paymentRequired('res-1', 1.5, 'USDC');
    expect(nativeMethods.x402PaymentRequired).toHaveBeenCalledWith('res-1', 1.5, 'USDC', {});
  });
  it('x402.paymentSettled delegates paymentId', () => {
    Aether.x402.paymentSettled('pay-1');
    expect(nativeMethods.x402PaymentSettled).toHaveBeenCalledWith('pay-1', {});
  });
  it('x402.accessGranted delegates resourceId', () => {
    Aether.x402.accessGranted('res-1');
    expect(nativeMethods.x402AccessGranted).toHaveBeenCalledWith('res-1', {});
  });
  it('x402.refundOrReversal delegates paymentId', () => {
    Aether.x402.refundOrReversal('pay-1');
    expect(nativeMethods.x402RefundOrReversal).toHaveBeenCalledWith('pay-1', {});
  });
});

describe('Aether RN bridge — rewards', () => {
  beforeEach(() => vi.clearAllMocks());

  it('rewards.actionQueued delegates campaignId and ruleId', () => {
    Aether.rewards.actionQueued('camp-1', 'rule-1');
    expect(nativeMethods.rewardActionQueued).toHaveBeenCalledWith('camp-1', 'rule-1', {});
  });
  it('rewards.proofGenerated delegates campaignId and proofId', () => {
    Aether.rewards.proofGenerated('camp-1', 'proof-1');
    expect(nativeMethods.rewardProofGenerated).toHaveBeenCalledWith('camp-1', 'proof-1', {});
  });
  it('rewards.delivered delegates campaignId and rewardId', () => {
    Aether.rewards.delivered('camp-1', 'reward-1');
    expect(nativeMethods.rewardDelivered).toHaveBeenCalledWith('camp-1', 'reward-1', {});
  });
  it('rewards.claimSubmitted delegates campaignId and claimId', () => {
    Aether.rewards.claimSubmitted('camp-1', 'claim-1');
    expect(nativeMethods.rewardClaimSubmitted).toHaveBeenCalledWith('camp-1', 'claim-1', {});
  });
});

describe('Aether RN bridge — commerce additions', () => {
  beforeEach(() => vi.clearAllMocks());

  it('commerce.removeFromCart delegates productId and quantity', () => {
    Aether.commerce.removeFromCart('prod-1', 2);
    expect(nativeMethods.trackRemoveFromCart).toHaveBeenCalledWith('prod-1', 2, {});
  });
  it('commerce.applyCoupon delegates couponCode', () => {
    Aether.commerce.applyCoupon('SAVE20');
    expect(nativeMethods.trackApplyCoupon).toHaveBeenCalledWith('SAVE20', {});
  });
  it('commerce.beginCheckout delegates cartValue and currency', () => {
    Aether.commerce.beginCheckout(99.99, 'USD');
    expect(nativeMethods.trackBeginCheckout).toHaveBeenCalledWith(99.99, 'USD', {});
  });
});
