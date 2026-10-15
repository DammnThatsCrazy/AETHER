import { useState, useCallback, useEffect } from 'react';
import type { ReactElement } from 'react';
import {
  initSDK,
  emitHeartbeat,
  trackPageView,
  trackEvent,
  identifyUser,
  simulateConversion,
  toggleConsent,
  simulateOffline,
  flushQueue,
  resetSession,
  getDebugState,
} from './sdk';
import { DebugPanel } from './debug-panel';

export function App(): ReactElement {
  const [sdkState, setSdkState] = useState(getDebugState());
  const [actionResult, setActionResult] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

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

  useEffect(() => {
    const interval = setInterval(refreshState, 2000);
    return () => clearInterval(interval);
  }, [refreshState]);

  const handleInitSDK = useCallback(async () => {
    try {
      await initSDK({ tenantId: 'demo-tenant' });
      setResult('SDK initialized');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setResult, setError]);

  const handleEmitHeartbeat = useCallback(async () => {
    try {
      const result = await emitHeartbeat();
      setResult(`Heartbeat queued — eventId: ${result.eventId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setResult, setError]);

  const handleTrackPageView = useCallback(async () => {
    try {
      const result = await trackPageView('/demo/page');
      setResult(`Page view queued — eventId: ${result.eventId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setResult, setError]);

  const handleTrackCustomEvent = useCallback(async () => {
    try {
      const result = await trackEvent('demo_event', { source: 'proof-web' });
      setResult(`Custom event queued — eventId: ${result.eventId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setResult, setError]);

  const handleIdentifyUser = useCallback(async () => {
    try {
      const result = await identifyUser('user-123', { email: 'demo@example.com' });
      setResult(`User identified — userId: ${result.userId}, anonymousId: ${result.anonymousId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setResult, setError]);

  const handleSimulateConversion = useCallback(async () => {
    try {
      const result = await simulateConversion(29.99);
      setResult(`Conversion queued — eventId: ${result.eventId}, revenue: $${result.revenue}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setResult, setError]);

  const handleToggleConsent = useCallback(async () => {
    try {
      const result = await toggleConsent('granted');
      setResult(`Consent granted — state: ${result.consentState}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setResult, setError]);

  const handleSimulateOffline = useCallback(async () => {
    try {
      const result = await simulateOffline();
      setResult(`Offline simulated — wasOnline: ${result.wasOnline}, status: ${result.status}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setResult, setError]);

  const handleFlushQueue = useCallback(async () => {
    try {
      const result = await flushQueue();
      setResult(`Queue flushed — status: ${result.status}, apiResponse: ${result.apiResponse ?? '—'}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setResult, setError]);

  const handleResetSession = useCallback(async () => {
    try {
      const result = await resetSession();
      setResult(`Session reset — newSessionId: ${result.newSessionId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setResult, setError]);

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ margin: '0 0 24px 0' }}>Aether Proof Web</h1>

      <div style={{ display: 'grid', gap: 12 }}>
        <button onClick={handleInitSDK}>Initialize SDK</button>
        <button onClick={handleEmitHeartbeat}>Emit Heartbeat</button>
        <button onClick={handleTrackPageView}>Track Page View</button>
        <button onClick={handleTrackCustomEvent}>Track Custom Event</button>
        <button onClick={handleIdentifyUser}>Identify User</button>
        <button onClick={handleSimulateConversion}>Simulate Conversion</button>
        <button onClick={handleToggleConsent}>Toggle Consent (Grant)</button>
        <button onClick={handleSimulateOffline}>Simulate Offline</button>
        <button onClick={handleFlushQueue}>Flush Queue</button>
        <button onClick={handleResetSession}>Reset Session</button>
      </div>

      {actionResult && (
        <div style={{ marginTop: 12, padding: '8px 12px', background: '#1a3a1a', color: '#8f8', borderRadius: 4, fontSize: 13 }}>
          {actionResult}
        </div>
      )}

      {actionError && (
        <div style={{ marginTop: 12, padding: '8px 12px', background: '#3a1a1a', color: '#f88', borderRadius: 4, fontSize: 13 }}>
          Error: {actionError}
        </div>
      )}

      <div style={{ marginTop: 32 }}>
        <DebugPanel state={sdkState} />
      </div>
    </div>
  );
}
