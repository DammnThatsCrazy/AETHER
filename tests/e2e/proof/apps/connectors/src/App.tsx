// @aether/proof-connectors — main application
// FPS-061–FPS-063: connector proof UI with 11 real controls

import { useState, useCallback, useEffect } from 'react';
import type { ConnectorState } from './types';
import * as panel from './connector-panel';
import * as sdk from './sdk';

// ---------------------------------------------------------------------------
// Status badge colours
// ---------------------------------------------------------------------------

function statusColor(status: string): string {
  switch (status) {
    case 'connected':
    case 'backfilling':
    case 'syncing':
    case 'completed':
    case 'valid':
      return '#22c55e';
    case 'connecting':
    case 'running':
    case 'refreshing':
      return '#eab308';
    case 'error':
    case 'failed':
    case 'expired':
    case 'invalid':
      return '#ef4444';
    case 'disconnected':
    case 'idle':
    case 'missing':
    case 'replaying':
    default:
      return '#6b7280';
  }
}

function statusBadge(status: string): React.ReactNode {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        color: '#fff',
        background: statusColor(status),
        textTransform: 'capitalize',
        letterSpacing: '0.02em',
      }}
    >
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Modal: raw / normalized payload viewer
// ---------------------------------------------------------------------------

function PayloadModal({
  title,
  payload,
  onClose,
}: {
  title: string;
  payload: unknown;
  onClose: () => void;
}): React.ReactNode {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#1a1a2e',
          border: '1px solid #334',
          borderRadius: 12,
          padding: 24,
          maxWidth: 700,
          maxHeight: '80vh',
          overflow: 'auto',
          boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, color: '#e2e8f0', fontSize: 16 }}>{title}</h3>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: '1px solid #445',
              color: '#aaa',
              borderRadius: 6,
              padding: '4px 12px',
              cursor: 'pointer',
              fontSize: 13,
            }}
          >
            Close
          </button>
        </div>
        <pre
          style={{
            background: '#0f0f1a',
            color: '#a5f3fc',
            padding: 16,
            borderRadius: 8,
            fontSize: 13,
            overflow: 'auto',
            maxHeight: 400,
            fontFamily: 'Menlo, monospace',
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          {JSON.stringify(payload, null, 2) as string}
        </pre>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal: graph writes viewer
// ---------------------------------------------------------------------------

function GraphWritesModal({
  graphWrites,
  onClose,
}: {
  graphWrites: unknown;
  onClose: () => void;
}): React.ReactNode {
  const data = graphWrites as { nodes?: unknown[]; edges?: unknown[] };
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#1a1a2e',
          border: '1px solid #334',
          borderRadius: 12,
          padding: 24,
          maxWidth: 700,
          maxHeight: '80vh',
          overflow: 'auto',
          boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, color: '#e2e8f0', fontSize: 16 }}>Graph Writes Preview</h3>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: '1px solid #445',
              color: '#aaa',
              borderRadius: 6,
              padding: '4px 12px',
              cursor: 'pointer',
              fontSize: 13,
            }}
          >
            Close
          </button>
        </div>
        <div style={{ display: 'grid', gap: 16 }}>
          <div>
            <h4 style={{ color: '#94a3b8', fontSize: 13, margin: '0 0 8px 0' }}>Nodes ({data.nodes?.length ?? 0})</h4>
            <pre
              style={{
                background: '#0f0f1a',
                color: '#a5f3fc',
                padding: 16,
                borderRadius: 8,
                fontSize: 13,
                overflow: 'auto',
                maxHeight: 200,
                fontFamily: 'Menlo, monospace',
                lineHeight: 1.5,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {JSON.stringify(data.nodes ?? [], null, 2) as string}
            </pre>
          </div>
          <div>
            <h4 style={{ color: '#94a3b8', fontSize: 13, margin: '0 0 8px 0' }}>Edges ({data.edges?.length ?? 0})</h4>
            <pre
              style={{
                background: '#0f0f1a',
                color: '#a5f3fc',
                padding: 16,
                borderRadius: 8,
                fontSize: 13,
                overflow: 'auto',
                maxHeight: 200,
                fontFamily: 'Menlo, monospace',
                lineHeight: 1.5,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {JSON.stringify(data.edges ?? [], null, 2) as string}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Provider selector dropdown
// ---------------------------------------------------------------------------

const PROVIDERS = [
  { value: 'stripe', label: 'Stripe (test mode)', hint: 'sk_test_ required' },
  { value: 'shopify', label: 'Shopify (dev store)', hint: 'shop + token required' },
  { value: 'email', label: 'Email (fixture)', hint: 'no live provider' },
];

function ProviderSelector({
  open,
  onSelect,
  onClose,
}: {
  open: boolean;
  onSelect: (provider: 'stripe' | 'shopify' | 'email') => void;
  onClose: () => void;
}): React.ReactNode {
  if (!open) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 90,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#1a1a2e',
          border: '1px solid #334',
          borderRadius: 12,
          padding: 24,
          minWidth: 320,
          boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 16px 0', color: '#e2e8f0', fontSize: 16 }}>Select Provider</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {PROVIDERS.map((p) => (
            <button
              key={p.value}
              onClick={() => {
                onSelect(p.value as 'stripe' | 'shopify' | 'email');
                onClose();
              }}
              style={{
                background: '#252540',
                border: '1px solid #334',
                borderRadius: 8,
                padding: '12px 16px',
                color: '#e2e8f0',
                textAlign: 'left',
                cursor: 'pointer',
                fontSize: 14,
              }}
            >
              <div style={{ fontWeight: 500 }}>{p.label}</div>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{p.hint}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Action result toast
// ---------------------------------------------------------------------------

function ActionResult({ result, onDismiss }: { result: ConnectorState['lastActionResult']; onDismiss: () => void }) {
  if (!result) return null;
  const ok = (result as { success?: boolean }).success !== false;
  return (
    <div
      style={{
        position: 'fixed',
        bottom: 24,
        right: 24,
        background: ok ? '#14532d' : '#7f1d1d',
        color: '#fff',
        padding: '12px 20px',
        borderRadius: 10,
        fontSize: 13,
        boxShadow: '0 8px 30px rgba(0,0,0,0.4)',
        maxWidth: 360,
        zIndex: 200,
        border: ok ? '1px solid #22c55e' : '1px solid #ef4444',
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4 }}>
        {ok ? '✓ Action succeeded' : '✗ Action failed'}
      </div>
      <div style={{ color: '#ccc' }}>{(result as { message?: string }).message}</div>
      <button
        onClick={onDismiss}
        style={{
          background: 'transparent',
          border: 'none',
          color: '#888',
          cursor: 'pointer',
          fontSize: 12,
          marginTop: 6,
          float: 'right',
        }}
      >
        dismiss
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------

export function App(): React.ReactNode {
  const [state, setState] = useState<ConnectorState>(panel.getState());
  const [dismissResult, setDismissResult] = useState(false);

  // Sync local state with the panel's mutable state, and initialize the
  // @aether/web SDK on mount so connector actions emit canonical events.
  useEffect(() => {
    const unsub = panel.subscribe(() => {
      setState(panel.getState());
    });
    sdk.initSDK().then(() => {
      setState((prev) => ({ ...prev, sdkInitialized: true, sdkVersion: sdk.getSDKVersion() }));
    }).catch(() => {
      // SDK init failure is non-fatal — the app still works for local simulation
      setState((prev) => ({ ...prev, sdkInitialized: false }));
    });
    return unsub;
  }, []);

  const handleConnect = useCallback(
    async (provider: 'stripe' | 'shopify' | 'email') => {
      await panel.connectProvider(provider);
    },
    []
  );

  const handleDisconnect = useCallback(() => {
    panel.disconnectProvider();
  }, []);

  const handleReconnect = useCallback(() => {
    panel.reconnectProvider();
  }, []);

  const handleBackfill = useCallback(() => {
    panel.startBackfill();
  }, []);

  const handleIncrementalSync = useCallback(() => {
    panel.triggerIncrementalSync();
  }, []);

  const handleWebhookReplay = useCallback(() => {
    panel.replayWebhook();
  }, []);

  const handleTokenExpiration = useCallback(() => {
    panel.simulateTokenExpiration();
  }, []);

  const handleProviderError = useCallback(() => {
    panel.simulateProviderError();
  }, []);

  const handleViewRaw = useCallback(() => {
    panel.viewRawPayload();
  }, []);

  const handleViewNormalized = useCallback(() => {
    panel.viewNormalizedPayload();
  }, []);

  const handleViewGraph = useCallback(() => {
    panel.viewGraphWrites();
  }, []);

  const handleCloseModal = useCallback(
    (modal: 'raw' | 'normalized' | 'graph') => {
      panel.closeModal(modal);
      setDismissResult(true);
    },
    []
  );

  const handleDismissResult = useCallback(() => {
    setDismissResult(true);
  }, []);

  const s = state;

  return (
    <div
      style={{
        maxWidth: 900,
        margin: '0 auto',
        padding: '24px 16px',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        backgroundColor: '#0a0a0f',
        minHeight: '100vh',
        color: '#e2e8f0',
      }}
    >
      {/* Header */}
      <header style={{ marginBottom: 32, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: '#f1f5f9' }}>
            Aether — Proof Connectors
          </h1>
          <p style={{ margin: '4px 0 0 0', fontSize: 13, color: '#64748b' }}>
            FPS-061 · FPS-062 · FPS-063 — connector lifecycle validation
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 12, color: '#64748b' }}>API:</span>
          <code style={{ fontSize: 11, background: '#1e1e2e', padding: '2px 6px', borderRadius: 4, color: '#94a3b8' }}>
            {s.provider ?? 'not connected'}
          </code>
        </div>
      </header>

      {/* Provider selector */}
      <ProviderSelector
        open={s.providerSelectorOpen}
        onSelect={handleConnect}
        onClose={() => panel.closeProviderSelector()}
      />

      {/* Action buttons grid */}
      <section style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 13, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 12px 0' }}>
          Connector Controls
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
          {/* Connect Provider */}
          <button
            onClick={() => panel.openProviderSelector()}
            disabled={s.status === 'connecting' || s.status === 'backfilling' || s.status === 'syncing'}
            style={{
              background: s.status === 'disconnected' ? '#1e3a5f' : '#1a3a2a',
              border: '1px solid #2a4a6a',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: s.status === 'disconnected' ? 'pointer' : 'not-allowed',
              opacity: s.status === 'disconnected' ? 1 : 0.5,
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>🔌 Connect Provider</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              {s.provider ? `Currently: ${s.provider}` : 'Select a provider to connect'}
            </div>
          </button>

          {/* Disconnect Provider */}
          <button
            onClick={handleDisconnect}
            disabled={s.status === 'disconnected'}
            style={{
              background: s.status === 'connected' || s.status === 'syncing' || s.status === 'backfilling' ? '#3a1a1a' : '#1a1a2e',
              border: '1px solid #4a2a2a',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: s.status === 'disconnected' ? 'not-allowed' : 'pointer',
              opacity: s.status === 'disconnected' ? 0.4 : 1,
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>⛓️ Disconnect Provider</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              Disconnect the current provider
            </div>
          </button>

          {/* Reconnect Provider */}
          <button
            onClick={handleReconnect}
            disabled={!s.provider || s.status === 'disconnected'}
            style={{
              background: s.provider ? '#1a2a3a' : '#1a1a2e',
              border: '1px solid #2a3a4a',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: s.provider ? 'pointer' : 'not-allowed',
              opacity: s.provider ? 1 : 0.4,
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>🔄 Reconnect Provider</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              Reconnect the current provider
            </div>
          </button>

          {/* Start Backfill */}
          <button
            onClick={handleBackfill}
            disabled={!s.provider || s.status === 'disconnected' || s.backfillStatus === 'running'}
            style={{
              background: s.provider && s.backfillStatus !== 'running' ? '#1a2a1a' : '#1a1a2e',
              border: '1px solid #2a4a2a',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: s.provider && s.backfillStatus !== 'running' ? 'pointer' : 'not-allowed',
              opacity: s.provider && s.backfillStatus !== 'running' ? 1 : 0.4,
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>📥 Start Backfill</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              {s.backfillStatus === 'running' ? 'Backfill in progress...' : s.backfillStatus === 'completed' ? 'Last backfill completed' : 'Read fixtures & POST to ingestion API'}
            </div>
          </button>

          {/* Trigger Incremental Sync */}
          <button
            onClick={handleIncrementalSync}
            disabled={!s.provider || s.status === 'disconnected'}
            style={{
              background: s.provider ? '#2a1a2a' : '#1a1a2e',
              border: '1px solid #4a2a4a',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: s.provider ? 'pointer' : 'not-allowed',
              opacity: s.provider ? 1 : 0.4,
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>⚡ Trigger Incremental Sync</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              Send an incremental update batch
            </div>
          </button>

          {/* Replay Webhook */}
          <button
            onClick={handleWebhookReplay}
            disabled={!s.provider || s.status === 'disconnected'}
            style={{
              background: s.provider ? '#2a2a1a' : '#1a1a2e',
              border: '1px solid #4a4a2a',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: s.provider ? 'pointer' : 'not-allowed',
              opacity: s.provider ? 1 : 0.4,
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>🔁 Replay Webhook</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              Replay a webhook payload from fixtures
            </div>
          </button>

          {/* Simulate Token Expiration */}
          <button
            onClick={handleTokenExpiration}
            disabled={s.status === 'disconnected'}
            style={{
              background: '#3a2a0a',
              border: '1px solid #5a4a1a',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: 'pointer',
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>⚠️ Simulate Token Expiration</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              Show token expired state
            </div>
          </button>

          {/* Simulate Provider Error */}
          <button
            onClick={handleProviderError}
            disabled={s.status === 'disconnected'}
            style={{
              background: '#3a1a1a',
              border: '1px solid #5a2a2a',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: 'pointer',
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>🚨 Simulate Provider Error</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              Show error state
            </div>
          </button>

          {/* View Raw Payload */}
          <button
            onClick={handleViewRaw}
            disabled={!s.provider}
            style={{
              background: s.provider ? '#1a1a2e' : '#111118',
              border: '1px solid #333',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: s.provider ? 'pointer' : 'not-allowed',
              opacity: s.provider ? 1 : 0.4,
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>📄 View Raw Payload</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              Show the raw fixture payload
            </div>
          </button>

          {/* View Normalized Payload */}
          <button
            onClick={handleViewNormalized}
            disabled={!s.provider}
            style={{
              background: s.provider ? '#1a1a2e' : '#111118',
              border: '1px solid #333',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: s.provider ? 'pointer' : 'not-allowed',
              opacity: s.provider ? 1 : 0.4,
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>📊 View Normalized Payload</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              Show the normalized output
            </div>
          </button>

          {/* View Graph Writes */}
          <button
            onClick={handleViewGraph}
            disabled={!s.provider}
            style={{
              background: s.provider ? '#1a2a2a' : '#111118',
              border: '1px solid #2a3a3a',
              color: '#e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              cursor: s.provider ? 'pointer' : 'not-allowed',
              opacity: s.provider ? 1 : 0.4,
              textAlign: 'left',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            <div style={{ fontWeight: 600 }}>🕸️ View Graph Writes</div>
            <div style={{ fontSize: 11, color: '#8899aa', marginTop: 2 }}>
              Show graph nodes/edges that would be written
            </div>
          </button>
        </div>
      </section>

      {/* Connector state panel */}
      <section
        style={{
          border: '1px solid #2a2a3a',
          borderRadius: 12,
          padding: 20,
          backgroundColor: '#111118',
          boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
        }}
      >
        <h2 style={{ fontSize: 13, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 16px 0' }}>
          Connector State
        </h2>

        {/* Status bar */}
        <div
          style={{
            display: 'flex',
            gap: 12,
            alignItems: 'center',
            marginBottom: 16,
            paddingBottom: 16,
            borderBottom: '1px solid #2a2a3a',
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>Status:</span>
            {statusBadge(s.status)}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>Provider:</span>
            <span style={{ fontSize: 13, fontWeight: 500, color: '#e2e8f0' }}>
              {s.provider ?? '—'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>Credential:</span>
            {statusBadge(s.credentialStatus)}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>Token:</span>
            {statusBadge(s.tokenRefreshStatus)}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>Backfill:</span>
            {statusBadge(s.backfillStatus)}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>Sync:</span>
            {statusBadge(s.incrementalSyncStatus)}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>Webhook:</span>
            {statusBadge(s.webhookStatus)}
          </div>
          {s.sync.lastSyncAt && (
            <div style={{ fontSize: 11, color: '#64748b' }}>
              Last sync: {new Date(s.sync.lastSyncAt).toLocaleTimeString()}
            </div>
          )}
        </div>

        {/* Sync metrics grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
            gap: 12,
            marginBottom: 16,
          }}
        >
          <Metric label="Records Received" value={s.sync.recordsReceived} color="#60a5fa" />
          <Metric label="Records Accepted" value={s.sync.recordsAccepted} color="#22c55e" />
          <Metric label="Records Rejected" value={s.sync.recordsRejected} color="#ef4444" />
          <Metric label="Records Normalized" value={s.sync.recordsNormalized} color="#a78bfa" />
          <Metric label="Records Written" value={s.sync.recordsWritten} color="#f59e0b" />
        </div>

        {/* Error / degraded info */}
        {(s.sync.lastError || s.sync.degradedReason) && (
          <div
            style={{
              background: '#1f1f2e',
              border: '1px solid #3a2a2a',
              borderRadius: 8,
              padding: '12px 16px',
              marginBottom: 12,
              fontSize: 13,
              color: '#fca5a5',
            }}
          >
            {s.sync.lastError && (
              <>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Last Error</div>
                <div>{s.sync.lastError}</div>
              </>
            )}
            {s.sync.degradedReason && (
              <>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Degraded Reason</div>
                <div>{s.sync.degradedReason}</div>
              </>
            )}
          </div>
        )}

        {/* Last action result */}
        {s.lastAction && s.lastActionResult && (
          <div
            style={{
              background: '#1a1a2e',
              border: '1px solid #333',
              borderRadius: 8,
              padding: '12px 16px',
              fontSize: 13,
            }}
          >
            <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', marginBottom: 4 }}>
              Last Action: {s.lastAction}
            </div>
            <pre
              style={{
                background: 'transparent',
                color: '#a5f3fc',
                fontSize: 12,
                fontFamily: 'Menlo, monospace',
                margin: 0,
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {JSON.stringify(s.lastActionResult, null, 2) as string}
            </pre>
          </div>
        )}

        {/* Raw payload modal */}
        {s.showRawPayload && s.rawPayload !== null && (
          <PayloadModal
            title="Raw Payload"
            payload={s.rawPayload}
            onClose={() => handleCloseModal('raw')}
          />
        )}

        {/* Normalized payload modal */}
        {s.showNormalizedPayload && s.normalizedPayload !== null && (
          <PayloadModal
            title="Normalized Payload"
            payload={s.normalizedPayload}
            onClose={() => handleCloseModal('normalized')}
          />
        )}

        {/* Graph writes modal */}
        {s.showGraphWrites && s.graphWrites !== null && (
          <GraphWritesModal
            graphWrites={s.graphWrites}
            onClose={() => handleCloseModal('graph')}
          />
        )}

        {/* Action result toast */}
        {!dismissResult && s.lastActionResult && (
          <ActionResult result={s.lastActionResult} onDismiss={handleDismissResult} />
        )}
      </section>

      {/* Footer note */}
      <footer style={{ marginTop: 32, textAlign: 'center', fontSize: 12, color: '#444' }}>
        Aether Proof Spine · Connector validation UI · {new Date().toISOString().slice(0, 10)}
      </footer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Metric tile
// ---------------------------------------------------------------------------

function Metric({ label, value, color }: { label: string; value: number; color: string }): React.ReactNode {
  return (
    <div
      style={{
        background: '#1a1a2e',
        borderRadius: 8,
        padding: '12px',
        border: '1px solid #2a2a3a',
      }}
    >
      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.03em' }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 24,
          fontWeight: 700,
          color,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value.toLocaleString()}
      </div>
    </div>
  );
}
