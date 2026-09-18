/**
 * FPS — React SDK Identity Late Binding Test
 */
import { useEffect, useState } from 'react';
import { AetherSDK } from '@aether/web';

export default function IdentityTest() {
  const [results, setResults] = useState<string[]>([]);

  useEffect(() => {
    const sdk = new AetherSDK();
    const log: string[] = [];

    const run = async () => {
      try { sdk.init({ apiKey: 'ak_test_key' }); log.push('init: OK'); } catch { log.push('init: FAIL'); }
      try { sdk.track('page_view', { url: '/' }); log.push('track: OK'); } catch { log.push('track: FAIL'); }
      try { sdk.hydrateIdentity({ userId: 'user_123', traits: { email: 'test@example.com' } }); log.push('hydrateIdentity: OK'); } catch { log.push('hydrateIdentity: FAIL'); }
      try { sdk.reset(); log.push('reset: OK'); } catch { log.push('reset: FAIL'); }
      try { await sdk.flush(); log.push('flush: OK'); } catch { log.push('flush: FAIL'); }
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
