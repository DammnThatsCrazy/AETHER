/**
 * FPS — React SDK Identity Late Binding Test
 */
import { useEffect, useState } from 'react';
import { AetherReactSDK } from '@aether/react';

export default function IdentityTest() {
  const [results, setResults] = useState<string[]>([]);

  useEffect(() => {
    const sdk = new AetherReactSDK({ apiKey: 'ak_test_key' });
    const log: string[] = [];

    const run = async () => {
      try { await sdk.heartbeat(); log.push('heartbeat: OK'); } catch (e) { log.push('heartbeat: FAIL'); }
      try { await sdk.track('page_view', { url: '/' }); log.push('track: OK'); } catch (e) { log.push('track: FAIL'); }
      try { await sdk.identify('user_123', { email: 'test@example.com' }); log.push('identify: OK'); } catch (e) { log.push('identify: FAIL'); }
      try { await sdk.alias('old_id', 'user_123'); log.push('alias: OK'); } catch (e) { log.push('alias: FAIL'); }
      try { await sdk.reset(); log.push('reset: OK'); } catch (e) { log.push('reset: FAIL'); }
      try { await sdk.setConsent({ purposes: { identity: true } }); log.push('consent: OK'); } catch (e) { log.push('consent: FAIL'); }
      setResults(log);
    };

    run();
  }, []);

  return (
    <div>
      <h1>React SDK Identity Test</h1>
      {results.map((r, i) => <div key={i}>{r}</div>)}
    </div>
  );
}
