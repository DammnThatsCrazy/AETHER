# Ecommerce Full Journey Example

A complete ecommerce flow that exercises every step of the Aether commerce event chain: product_viewed → cart_item_added → checkout_started → checkout_step_completed (shipping) → checkout_step_completed (payment) → payment_initiated → order_completed → conversion → flush.

## What it proves

| Step | Event | Proof |
|------|-------|-------|
| Product view | `product_viewed` | First touchpoint in the funnel |
| Cart add | `cart_item_added` | Intent to purchase |
| Checkout start | `checkout_started` | Funnel progression |
| Checkout step (shipping) | `checkout_step_completed` | Step completion |
| Checkout step (payment) | `checkout_step_completed` | Step completion |
| Payment initiated | `payment_initiated` | Payment intent |
| Order completed | `order_completed` | Revenue-bearing conversion event |
| Conversion | `conversion.completed` (via `aether.conversion()`) | Revenue $29.99 USD attached |
| Flush | `flush()` | Queue drained, backend acceptance proven |
| Backend acceptance | POST /v1/batch returns 200 with counters | Events visible in Aether dashboard & Kyber |
| Activation milestone | First valid event accepted → device activated | Check activation status |
| Kyber/Aether visibility | Commerce events in economic graph | Verify in Kyber observability |

## First-value journey (ecommerce path)

1. **Install** — `@aether/web` loaded via Vite+React app shell.
2. **Init** — `initSDK()` connects to the Aether ingestion endpoint.
3. **Consent** — `toggleConsent('granted')` grants analytics + commerce purposes.
4. **Product viewed** — `trackProductViewed('SKU-001', …)` fires `product_viewed`.
5. **Cart add** — `trackCartItemAdded('SKU-001', …)` fires `cart_item_added`.
6. **Checkout start** — `trackCheckoutStarted('cart_123', …)` fires `checkout_started`.
7. **Checkout steps** — two `checkout_step_completed` events (shipping, payment).
8. **Payment initiated** — `trackPaymentInitiated('cart_123', …)` fires `payment_initiated`.
9. **Order completed** — `trackOrderCompleted('ord_456', …)` fires `order_completed`.
10. **Conversion** — `trackConversion('order_completed', 29.99, 'USD', …)` fires `conversion.completed` with revenue.
11. **Flush** — `flushQueue()` drains all queued events and proves backend acceptance.
12. **Kyber/Aether visibility** — all commerce events appear in the economic graph.

## Running

1. `cd examples/ecommerce-full-journey`
2. `npm install`
3. `npm run dev`
4. Open the local dev server URL.
5. Click **▶ Run Full Ecommerce Journey** to execute the entire funnel in sequence.

The on-page DebugPanel shows the SDK state, consent state, queue size, and last delivery status. The journey steps list shows the executed funnel steps.

## Environment

- **`.env.local`** — local dev: `http://localhost:8000`.
- **`.env.staging`** — staging: `https://staging.aether.so`.

## Files

- `src/App.tsx` — the ecommerce funnel UI + "Run Full Journey" button.
- `src/sdk.ts` — the event enqueuers for each commerce step.
- `src/types.ts` — SDK state and batch health types.
- `src/debug-panel.tsx` — live SDK state display.

## Related

- `examples/web-next/` — the same SDK stack used for a simpler first-value journey.
- `examples/web-script-tag/` — the one-tag snippet path.
- `examples/server-node/` — server-side commerce observation via `@aether/server`.
