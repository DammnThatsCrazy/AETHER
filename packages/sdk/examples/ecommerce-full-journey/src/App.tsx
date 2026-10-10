import { useState, useCallback, useEffect } from 'react';
import type { ReactElement } from 'react';
import {
  initSDK,
  trackProductViewed,
  trackCartItemAdded,
  trackCheckoutStarted,
  trackCheckoutStepCompleted,
  trackPaymentInitiated,
  trackOrderCompleted,
  trackConversion,
  toggleConsent,
  flushQueue,
  resetSession,
  getDebugState,
} from './sdk';
import { DebugPanel } from './debug-panel';

/**
 * Complete ecommerce full-journey harness.
 *
 * Simulates a full ecommerce funnel and proves every step emits a canonical
 * event that reaches the Aether backend:
 *
 *   product_viewed → cart_item_added → checkout_started →
 *   checkout_step_completed (shipping) → checkout_step_completed (payment) →
 *   payment_initiated → order_completed → conversion →
 *   flush → backend acceptance → Kyber/Aether visibility
 */
export function App(): ReactElement {
  const [sdkState, setSdkState] = useState(getDebugState());
  const [actionResult, setActionResult] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [journeyState, setJourneyState] = useState<string[]>([]);

  const refreshState = useCallback(() => {
    setSdkState(getDebugState());
  }, []);

  const setResult = useCallback((msg: string) => {
    setActionResult(msg);
    setActionError(null);
    refreshState();
  }, [refreshState]);

  const setError = useCallback((msg: string) => {
    setActionError(msg);
    setActionResult(null);
    refreshState();
  }, [refreshState]);

  const pushJourney = useCallback((step: string) => {
    setJourneyState((prev) => [...prev, step]);
  }, []);

  useEffect(() => {
    const interval = setInterval(refreshState, 2000);
    return () => clearInterval(interval);
  }, [refreshState]);

  // --- Ecommerce full journey ---

  const handleInitSDK = useCallback(async () => {
    try {
      await initSDK({ tenantId: 'demo-tenant' });
      pushJourney('SDK initialized');
      setResult('SDK initialized — ecommerce full-journey ready');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleGrantConsent = useCallback(async () => {
    try {
      const result = await toggleConsent('granted');
      pushJourney('Consent granted: ' + result.consentState);
      setResult(`Consent granted — state: ${result.consentState}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleProductViewed = useCallback(async () => {
    try {
      const result = await trackProductViewed(
        'SKU-001',
        'Aether Analytics Pro',
        'Software',
        29.99,
      );
      pushJourney('product_viewed: SKU-001');
      setResult(`Product viewed — eventId: ${result.eventId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleCartItemAdded = useCallback(async () => {
    try {
      const result = await trackCartItemAdded(
        'SKU-001',
        'Aether Analytics Pro',
        1,
        29.99,
      );
      pushJourney('cart_item_added: SKU-001 x1');
      setResult(`Cart item added — eventId: ${result.eventId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleCheckoutStarted = useCallback(async () => {
    try {
      const result = await trackCheckoutStarted('cart_123', 1, 29.99);
      pushJourney('checkout_started: cart_123');
      setResult(`Checkout started — eventId: ${result.eventId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleCheckoutStepShipping = useCallback(async () => {
    try {
      const result = await trackCheckoutStepCompleted('cart_123', 'shipping');
      pushJourney('checkout_step_completed: shipping');
      setResult(`Shipping step completed — eventId: ${result.eventId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleCheckoutStepPayment = useCallback(async () => {
    try {
      const result = await trackCheckoutStepCompleted('cart_123', 'payment');
      pushJourney('checkout_step_completed: payment');
      setResult(`Payment step completed — eventId: ${result.eventId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handlePaymentInitiated = useCallback(async () => {
    try {
      const result = await trackPaymentInitiated(
        'cart_123',
        'card',
        29.99,
      );
      pushJourney('payment_initiated: card');
      setResult(`Payment initiated — eventId: ${result.eventId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleOrderCompleted = useCallback(async () => {
    try {
      const result = await trackOrderCompleted(
        'ord_456',
        'cart_123',
        29.99,
        'USD',
        [
          {
            sku: 'SKU-001',
            name: 'Aether Analytics Pro',
            price: 29.99,
            quantity: 1,
          },
        ],
      );
      pushJourney('order_completed: ord_456 ($29.99 USD)');
      setResult(`Order completed — eventId: ${result.eventId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleConversion = useCallback(async () => {
    try {
      const result = await trackConversion(
        'order_completed',
        29.99,
        'USD',
        'ord_456',
      );
      pushJourney('conversion: order_completed $29.99 USD');
      setResult(
        `Conversion queued — eventId: ${result.eventId}, revenue: $${result.revenue}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleFlushQueue = useCallback(async () => {
    try {
      const result = await flushQueue();
      pushJourney('Queue flushed');
      setResult(
        `Queue flushed — status: ${result.status}, apiResponse: ${result.apiResponse ?? '—'}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleResetSession = useCallback(async () => {
    try {
      const result = await resetSession();
      pushJourney('Session reset');
      setResult(`Session reset — newSessionId: ${result.newSessionId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [pushJourney, setResult, setError]);

  const handleRunFullJourney = useCallback(async () => {
    // Run the entire ecommerce funnel in sequence.
    const cartId = `cart_${Date.now()}`;
    const orderId = `ord_${Date.now()}`;
    const steps = [
      { label: 'product_viewed', fn: async () => {
        await trackProductViewed('SKU-001', 'Aether Analytics Pro', 'Software', 29.99);
        pushJourney('product_viewed');
      }},
      { label: 'cart_item_added', fn: async () => {
        await trackCartItemAdded('SKU-001', 'Aether Analytics Pro', 1, 29.99);
        pushJourney('cart_item_added');
      }},
      { label: 'checkout_started', fn: async () => {
        await trackCheckoutStarted(cartId, 1, 29.99);
        pushJourney('checkout_started');
      }},
      { label: 'checkout_step_completed (shipping)', fn: async () => {
        await trackCheckoutStepCompleted(cartId, 'shipping');
        pushJourney('checkout_step_completed: shipping');
      }},
      { label: 'checkout_step_completed (payment)', fn: async () => {
        await trackCheckoutStepCompleted(cartId, 'payment');
        pushJourney('checkout_step_completed: payment');
      }},
      { label: 'payment_initiated', fn: async () => {
        await trackPaymentInitiated(cartId, 'card', 29.99);
        pushJourney('payment_initiated');
      }},
      { label: 'order_completed', fn: async () => {
        await trackOrderCompleted(orderId, cartId, 29.99, 'USD', [
          { sku: 'SKU-001', name: 'Aether Analytics Pro', price: 29.99, quantity: 1 },
        ]);
        pushJourney('order_completed');
      }},
      { label: 'conversion', fn: async () => {
        await trackConversion('order_completed', 29.99, 'USD', orderId);
        pushJourney('conversion');
      }},
      { label: 'flush', fn: async () => {
        await flushQueue();
        pushJourney('flush');
      }},
    ];

    for (const step of steps) {
      setActionResult(`Running: ${step.label}…`);
      try {
        await step.fn();
      } catch (err) {
        setActionError(`${step.label} failed: ${err instanceof Error ? err.message : String(err)}`);
        return;
      }
      await new Promise((r) => setTimeout(r, 350));
    }

    setResult('Full ecommerce journey complete — all events delivered to backend');
  }, [pushJourney, setResult, setActionError]);

  return (
    <div
      style={{
        maxWidth: 800,
        margin: '0 auto',
        padding: 24,
        fontFamily: 'system-ui, sans-serif',
      }}
    >
      <h1 style={{ margin: '0 0 8px 0' }}>
        Aether — Ecommerce Full Journey Example
      </h1>
      <p style={{ color: '#888', margin: '0 0 24px 0', fontSize: 14 }}>
        Complete ecommerce funnel: product_viewed → cart → checkout → payment →
        order_completed → conversion → flush
      </p>

      <div style={{ display: 'grid', gap: 12, marginBottom: 16 }}>
        <button onClick={handleInitSDK}>Initialize SDK</button>
        <button onClick={handleGrantConsent}>Grant Consent</button>
        <button onClick={handleProductViewed}>1. Product Viewed</button>
        <button onClick={handleCartItemAdded}>2. Cart Item Added</button>
        <button onClick={handleCheckoutStarted}>3. Checkout Started</button>
        <button onClick={handleCheckoutStepShipping}>
          4. Checkout Step: Shipping
        </button>
        <button onClick={handleCheckoutStepPayment}>
          5. Checkout Step: Payment
        </button>
        <button onClick={handlePaymentInitiated}>6. Payment Initiated</button>
        <button onClick={handleOrderCompleted}>7. Order Completed</button>
        <button onClick={handleConversion}>8. Conversion</button>
        <button onClick={handleFlushQueue}>Flush Queue</button>
        <button onClick={handleResetSession}>Reset Session</button>
        <button
          onClick={handleRunFullJourney}
          style={{ background: '#7c3aed', padding: 12 }}
        >
          ▶ Run Full Ecommerce Journey
        </button>
      </div>

      {actionResult && (
        <div
          style={{
            marginTop: 12,
            padding: '8px 12px',
            background: '#1a3a1a',
            color: '#8f8',
            borderRadius: 4,
            fontSize: 13,
          }}
        >
          {actionResult}
        </div>
      )}

      {actionError && (
        <div
          style={{
            marginTop: 12,
            padding: '8px 12px',
            background: '#3a1a1a',
            color: '#f88',
            borderRadius: 4,
            fontSize: 13,
          }}
        >
          Error: {actionError}
        </div>
      )}

      {journeyState.length > 0 && (
        <div
          style={{
            marginTop: 16,
            padding: 12,
            background: '#111',
            border: '1px solid #333',
            borderRadius: 8,
          }}
        >
          <h3 style={{ margin: '0 0 8px 0', color: '#8af', fontSize: 14 }}>
            Journey Steps Executed
          </h3>
          <ol style={{ margin: 0, paddingLeft: 20, color: '#ccc', fontSize: 13 }}>
            {journeyState.map((step, idx) => (
              <li key={idx} style={{ marginBottom: 2 }}>
                {step}
              </li>
            ))}
          </ol>
        </div>
      )}

      <div style={{ marginTop: 32 }}>
        <DebugPanel state={sdkState} />
      </div>
    </div>
  );
}
