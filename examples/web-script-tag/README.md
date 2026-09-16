# Web Script Tag Example

Standalone HTML demo that loads the Aether SDK via the one-tag snippet and exercises the full first-value journey from a plain web page — no bundler, no framework.

## How it works

The `index.html` page includes:

1. **`window.aeConfig`** — the SDK configuration object (apiKey + endpoint).
2. **The one-tag snippet** — a self-loading `<script>` that pulls `https://cdn.aether.so/aether.js` asynchronously.
3. **A journey harness** — buttons that call `initSDK → emitHeartbeat → consent.grant → trackEvent → identifyUser → journey.start → commerce.track → flush`.

Open `examples/web-script-tag/index.html` in a browser to run the demo interactively. The page logs every step to an on-page event log.

## First-value journey (script-tag path)

| Step | What happens | Proof |
|------|-------------|-------|
| Install | One `<script>` tag in the page head | Script loads from CDN |
| Init | `window.aeConfig` read by the SDK on load | SDK ready, config visible in log |
| Heartbeat | SDK emits a heartbeat event | `accepted=1` in delivery log |
| Consent | `consent.grant(['analytics','commerce','marketing'])` | Consent state shown in log |
| Event | `trackEvent('demo_event')` | Custom event delivered |
| Identify | `identifyUser('user_123')` | Identity linkage sent |
| Journey | `journey.start('checkout_flow')` | Journey lifecycle started |
| Commerce | `commerce.track('order_completed', …)` | Revenue event delivered |
| Flush | `flush()` drains the queue | All events confirmed delivered |
| Backend acceptance | POST /v1/batch returns 200 with counters | Visible in Aether dashboard & Kyber |
| Activation milestone | First valid event accepted → device activated | See activation status in debug log |
| Kyber/Aether visibility | Commerce + heartbeat events appear in economic graph | Check Kyber observability |

## Environment

The snippet uses inline `window.aeConfig`. For local testing, set:

- **apiKey**: `local-dev-key-placeholder`
- **endpoint**: `http://localhost:8000`

For staging, swap the values to the staging write key and `https://staging.aether.so`.

## Files

- `index.html` — the standalone demo page (also the one-tag snippet reference).

## Related

- `examples/web-next/` — the same journey in a Vite+React app.
- `scripts/smoke/web-sdk.ts` — automated smoke tests for the web SDK.
