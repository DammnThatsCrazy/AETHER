import type { SDKState } from './types';
import type { ReactElement } from 'react';
import React from 'react';
import type { ConsentState } from '@aether/shared/consent';
import { getRealConsentState, getSDKInstance } from './sdk';

interface DebugPanelProps {
  readonly state: SDKState;
}

function ConsentGrid({ consent }: { consent: ConsentState }): ReactElement {
  const purposes: Array<{ key: keyof ConsentState; label: string }> = [
    { key: 'analytics', label: 'Analytics' },
    { key: 'marketing', label: 'Marketing' },
    { key: 'personalization', label: 'Personalization' },
    { key: 'web3', label: 'Web3' },
    { key: 'agent', label: 'Agent' },
    { key: 'commerce', label: 'Commerce' },
    { key: 'financial_activity', label: 'Financial Activity' },
    { key: 'credit', label: 'Credit' },
    { key: 'location', label: 'Location' },
    { key: 'economic_observability', label: 'Economic Observability' },
    { key: 'cross_chain_observability', label: 'Cross-Chain Observability' },
    { key: 'fraud_prevention', label: 'Fraud Prevention' },
  ];

  return (
    <dl style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: '4px 12px', marginTop: 4 }}>
      {purposes.map(({ key, label }) => (
        <React.Fragment key={String(key)}>
          <div>{label}</div>
          <div style={{ color: consent[key] ? '#8f8' : '#f88' }}>
            {String(consent[key])}
          </div>
        </React.Fragment>
      ))}
      <div>updatedAt</div>
      <div>{consent.updatedAt ?? '—'}</div>
      <div>policyVersion</div>
      <div>{consent.policyVersion ?? '—'}</div>
    </dl>
  );
}

export function DebugPanel({ state }: DebugPanelProps): ReactElement {
  const realConsent = state.realConsentState;
  const sdkInstance = getSDKInstance();

  return (
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
        <div>initialized</div>
        <div>{String(state.initialized)}</div>
        <div>version</div>
        <div>{state.version}</div>
        <div>sdkVersion</div>
        <div>{state.sdkVersion}</div>
        <div>tenantId</div>
        <div>{state.tenantId ?? '—'}</div>
        <div>workspaceId</div>
        <div>{state.workspaceId ?? '—'}</div>
        <div>platformId</div>
        <div>{state.platformId ?? '—'}</div>
        <div>sessionId</div>
        <div>{state.sessionId ?? '—'}</div>
        <div>anonymousId</div>
        <div>{state.anonymousId ?? '—'}</div>
        <div>knownUserId</div>
        <div>{state.knownUserId ?? '—'}</div>
        <div>consentState (summary)</div>
        <div>{state.consentState}</div>
        <div>queueSize (local count)</div>
        <div>{state.queueSize}</div>
        <div>lastDeliveryStatus</div>
        <div>{state.lastDeliveryStatus}</div>
        <div>lastApiResponse</div>
        <div>{state.lastApiResponse ?? '—'}</div>
        <div>lastError</div>
        <div>{state.lastError ?? '—'}</div>
        <div>lastEventId</div>
        <div>{state.lastEventId ?? '—'}</div>
      </dl>

      {realConsent && (
        <div style={{ marginTop: 16, padding: 12, background: '#1a1a1a', borderRadius: 4, border: '1px solid #333' }}>
          <h3 style={{ margin: '0 0 8px 0', fontSize: 14, color: '#aaa' }}>Real Consent State (from @aether/web SDK)</h3>
          <ConsentGrid consent={realConsent} />
        </div>
      )}

      {sdkInstance && (
        <div style={{ marginTop: 12, padding: 8, background: '#1a1a1a', borderRadius: 4, border: '1px solid #333', fontSize: 11, color: '#888' }}>
          SDK instance: {String(sdkInstance !== null)}<br />
          Methods available: init, track, observe, pageView, conversion, flush, reset, destroy, consent, wallet, commerce, agent, x402
        </div>
      )}
    </section>
  );
}
