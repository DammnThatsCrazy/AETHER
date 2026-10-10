/**
 * FPS — React Native SDK Identity Late Binding Test
 */
import { AetherRN } from '@aether/react-native';

export function runIdentityTests() {
  const sdk = new AetherRN({ apiKey: 'ak_test_key' });
  
  const results: string[] = [];
  
  sdk.heartbeat().then(() => results.push('heartbeat: OK')).catch(() => results.push('heartbeat: FAIL'));
  sdk.track('page_view', { url: '/' }).then(() => results.push('track: OK'));
  sdk.identify('user_123', { email: 'test@example.com' }).then(() => results.push('identify: OK'));
  sdk.alias('old_anon', 'user_123').then(() => results.push('alias: OK'));
  sdk.reset().then(() => results.push('reset: OK'));
  sdk.setConsent({ purposes: { identity: true } }).then(() => results.push('consent: OK'));
  
  return results;
}
