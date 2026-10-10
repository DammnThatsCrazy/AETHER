import type { ReactElement } from 'react';
import { useState, useCallback } from 'react';
import {
  AetherProvider,
  useAether,
  useAetherConsent,
  getDebugState,
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
} from './sdk';

function UseAetherDemo(): ReactElement {
  const sdk = useAether();
  const consent = useAetherConsent();
  const [localState, setLocalState] = useState(getDebugState());

  const refresh = useCallback(() => setLocalState(getDebugState()), []);

  return (
    <div style={{ marginTop: 24, padding: 16, border: '1px solid #333', borderRadius: 8, background: '#111', color: '#ddd', fontFamily: 'monospace', fontSize: 13 }}>
      <h3 style={{ margin: '0 0 12px 0' }}>useAether / useAetherConsent Demo</h3>
      <p style={{ margin: '4px 0' }}>initialized: {String(sdk.initialized)}</p>
      <p style={{ margin: '4px 0' }}>sessionId: {sdk.sessionId ?? '—'}</p>
      <p style={{ margin: '4px 0' }}>consentState: {consent.consentState}</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
        <button onClick={() => { sdk.trackEvent('hook_event'); refresh(); }}>Track Event (hook)</button>
        <button onClick={() => { sdk.identifyUser('hook-user-456'); refresh(); }}>Identify (hook)</button>
        <button onClick={() => { sdk.trackPageView('/hook/page'); refresh(); }}>Track Page (hook)</button>
        <button onClick={() => { consent.toggleConsent('granted'); refresh(); }}>Toggle Consent (hook)</button>
      </div>
    </div>
  );
}

export function App(): ReactElement {
  const [sdkState, setSdkState] = useState(getDebugState());

  const refreshState = useCallback(() => setSdkState(getDebugState()), []);

  const handleInitSDK = useCallback(() => {
    initSDK({ tenantId: 'demo-tenant', workspaceId: 'demo-workspace', platformId: 'react' });
    refreshState();
  }, [refreshState]);

  const handleEmitHeartbeat = useCallback(() => {
    emitHeartbeat();
    refreshState();
  }, [refreshState]);

  const handleTrackPageView = useCallback(() => {
    trackPageView('/demo/page');
    refreshState();
  }, [refreshState]);

  const handleTrackCustomEvent = useCallback(() => {
    trackEvent('demo_event', { source: 'proof-react' });
    refreshState();
  }, [refreshState]);

  const handleIdentifyUser = useCallback(() => {
    identifyUser('user-123', { email: 'demo@example.com' });
    refreshState();
  }, [refreshState]);

  const handleSimulateConversion = useCallback(() => {
    simulateConversion(29.99);
    refreshState();
  }, [refreshState]);

  const handleToggleConsent = useCallback(() => {
    toggleConsent('granted');
    refreshState();
  }, [refreshState]);

  const handleSimulateOffline = useCallback(() => {
    simulateOffline();
    refreshState();
  }, [refreshState]);

  const handleFlushQueue = useCallback(() => {
    flushQueue();
    refreshState();
  }, [refreshState]);

  const handleResetSession = useCallback(() => {
    resetSession();
    refreshState();
  }, [refreshState]);

  return (
    <AetherProvider>
      <div style={{ maxWidth: 800, margin: '0 auto', padding: 24, fontFamily: 'system-ui, sans-serif' }}>
        <h1 style={{ margin: '0 0 24px 0' }}>Aether Proof React</h1>

        <div style={{ display: 'grid', gap: 12 }}>
          <button onClick={handleInitSDK}>Initialize SDK</button>
          <button onClick={handleEmitHeartbeat}>Emit Heartbeat</button>
          <button onClick={handleTrackPageView}>Track Page View</button>
          <button onClick={handleTrackCustomEvent}>Track Custom Event</button>
          <button onClick={handleIdentifyUser}>Identify User</button>
          <button onClick={handleSimulateConversion}>Simulate Conversion</button>
          <button onClick={handleToggleConsent}>Toggle Consent</button>
          <button onClick={handleSimulateOffline}>Simulate Offline</button>
          <button onClick={handleFlushQueue}>Flush Queue</button>
          <button onClick={handleResetSession}>Reset Session</button>
        </div>

        <div style={{ marginTop: 32 }}>
          <section
            style={{
              border: '1px solid #333',
              borderRadius: 8,
              padding: 16,
              fontFamily: 'monospace',
              fontSize: 13,
              background: '#111',
              color: '#ddd',
              maxWidth: 600,
            }}
          >
            <h2 style={{ margin: '0 0 12px 0', fontSize: 16 }}>SDK Debug State</h2>
            <dl style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: '4px 12px' }}>
              <div>initialized</div><div>{String(sdkState.initialized)}</div>
              <div>version</div><div>{sdkState.version}</div>
              <div>tenantId</div><div>{sdkState.tenantId ?? '—'}</div>
              <div>workspaceId</div><div>{sdkState.workspaceId ?? '—'}</div>
              <div>platformId</div><div>{sdkState.platformId ?? '—'}</div>
              <div>sessionId</div><div>{sdkState.sessionId ?? '—'}</div>
              <div>anonymousId</div><div>{sdkState.anonymousId ?? '—'}</div>
              <div>knownUserId</div><div>{sdkState.knownUserId ?? '—'}</div>
              <div>consentState</div><div>{sdkState.consentState}</div>
              <div>queueSize</div><div>{sdkState.queueSize}</div>
              <div>lastDeliveryStatus</div><div>{sdkState.lastDeliveryStatus}</div>
              <div>lastApiResponse</div><div>{sdkState.lastApiResponse ?? '—'}</div>
              <div>lastError</div><div>{sdkState.lastError ?? '—'}</div>
            </dl>
          </section>
        </div>

        <div style={{ marginTop: 24 }}>
          <UseAetherDemo />
        </div>
      </div>
    </AetherProvider>
  );
}
