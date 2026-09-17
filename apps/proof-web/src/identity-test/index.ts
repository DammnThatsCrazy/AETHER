/**
 * FPS — Web SDK Identity Late Binding Test
 * Demonstrates: heartbeat, anonymous event, identify, alias, reset, consent
 */
import { AetherSDK } from '@aether/web';

const sdk = new AetherSDK({
  apiKey: 'ak_test_key',
  endpoint: 'http://localhost:8000',
});

const status = document.getElementById('status')!;

async function runTests() {
  const results: string[] = [];
  
  // 1. Heartbeat
  try {
    const hb = await sdk.heartbeat();
    results.push('heartbeat: OK');
  } catch (e) {
    results.push('heartbeat: FAIL — ' + (e as Error).message);
  }

  // 2. Anonymous event
  try {
    await sdk.track('page_view', { url: '/' });
    results.push('anonymous_event: OK');
  } catch (e) {
    results.push('anonymous_event: FAIL — ' + (e as Error).message);
  }

  // 3. Identify
  try {
    await sdk.identify('user_123', { email: 'test@example.com', name: 'Test User' });
    results.push('identify: OK');
  } catch (e) {
    results.push('identify: FAIL — ' + (e as Error).message);
  }

  // 4. Alias
  try {
    await sdk.alias('old_anon_id', 'user_123');
    results.push('alias: OK');
  } catch (e) {
    results.push('alias: FAIL — ' + (e as Error).message);
  }

  // 5. Reset
  try {
    await sdk.reset();
    results.push('reset: OK');
  } catch (e) {
    results.push('reset: FAIL — ' + (e as Error).message);
  }

  // 6. Consent
  try {
    await sdk.setConsent({ purposes: { identity: true, analytics: true } });
    results.push('consent: OK');
  } catch (e) {
    results.push('consent: FAIL — ' + (e as Error).message);
  }

  status.innerHTML = results.map(r => '<div>' + r + '</div>').join('');
}

runTests();
