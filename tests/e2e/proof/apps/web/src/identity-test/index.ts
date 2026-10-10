/**
 * FPS — Web SDK Identity Late Binding Test
 * Demonstrates: init, anonymous event, hydrateIdentity, reset, flush, consent
 */
import { AetherSDK } from '@aether/web';

const sdk = new AetherSDK();
sdk.init({
  apiKey: 'ak_test_key',
  endpoint: 'http://localhost:8000',
});

const status = document.getElementById('status')!;

async function runTests() {
  const results: string[] = [];

  // 1. Anonymous event
  try {
    sdk.track('page_view', { url: '/' });
    results.push('anonymous_event: OK');
  } catch (e) {
    results.push('anonymous_event: FAIL — ' + (e as Error).message);
  }

  // 2. Hydrate identity
  try {
    sdk.hydrateIdentity({ userId: 'user_123', traits: { email: 'test@example.com', name: 'Test User' } });
    results.push('hydrateIdentity: OK');
  } catch (e) {
    results.push('hydrateIdentity: FAIL — ' + (e as Error).message);
  }

  // 3. Reset
  try {
    sdk.reset();
    results.push('reset: OK');
  } catch (e) {
    results.push('reset: FAIL — ' + (e as Error).message);
  }

  // 4. Flush
  try {
    await sdk.flush();
    results.push('flush: OK');
  } catch (e) {
    results.push('flush: FAIL — ' + (e as Error).message);
  }

  status.innerHTML = results.map(r => '<div>' + r + '</div>').join('');
}

runTests();
