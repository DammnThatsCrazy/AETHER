// =============================================================================
// Aether SDK Proof Harness — app shell (apps/proof-android)
// 8 tabbed screens wired to real SDK functions. SDK key from
// PROOF_ANDROID_SDK_KEY env or a default staging key.
// =============================================================================

import React, { useState, useCallback, useRef } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  ScrollView,
  StyleSheet,
  ActivityIndicator,
  TextStyle,
} from 'react-native';
import {
  initSDK,
  emitHeartbeat,
  trackScreen,
  trackEvent,
  identifyUser,
  trackConversion,
  setConsent,
  flushQueue,
  simulateOffline,
  getState,
  getDebugStateRaw,
  getLastEventPayload,
  getEventLog,
} from './sdk';
import type { SDKState } from './types';

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16, backgroundColor: '#0a0a0a' },
  header: { fontSize: 24, fontWeight: 'bold', marginBottom: 16, color: '#fff' },
  subheader: { fontSize: 14, color: '#888', marginBottom: 12 },
  button: {
    backgroundColor: '#2563eb',
    padding: 12,
    borderRadius: 8,
    marginBottom: 8,
    alignItems: 'center',
  },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  buttonDanger: { backgroundColor: '#dc2626' },
  buttonSuccess: { backgroundColor: '#16a34a' },
  buttonWarning: { backgroundColor: '#d97706' },
  panel: {
    backgroundColor: '#111',
    borderColor: '#333',
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    marginTop: 16,
  },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 },
  label: { color: '#aaa' },
  value: { color: '#fff', fontFamily: 'monospace' },
  statusOk: { color: '#4ade80' },
  statusFail: { color: '#f87171' },
  statusIdle: { color: '#888' },
  logItem: {
    borderBottomColor: '#222',
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingVertical: 6,
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  logType: { color: '#93c5fd', flex: 1 },
  logTs: { color: '#666', fontSize: 11, marginRight: 8 },
  logStatus: { color: '#4ade80', fontSize: 11, fontFamily: 'monospace' },
  spinner: { marginVertical: 8 },
  tab: {
    padding: 12,
    marginRight: 8,
    borderRadius: 8,
    backgroundColor: '#1f1f1f',
  },
  tabActive: { backgroundColor: '#2563eb' },
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusColor(status: SDKState['lastDeliveryStatus']): TextStyle {
  if (status === 'delivered') return { color: '#4ade80' as const };
  if (status === 'failed') return { color: '#f87171' as const };
  if (status === 'pending') return { color: '#fbbf24' as const };
  return { color: '#888' as const };
}

function statusText(status: SDKState['lastDeliveryStatus']): string {
  if (status === 'delivered') return 'DELIVERED';
  if (status === 'failed') return 'FAILED';
  if (status === 'pending') return 'PENDING';
  return 'IDLE';
}

/** Resolve the SDK key: PROOF_ANDROID_SDK_KEY env, else a default staging key. */
function resolveSdkKey(): string {
  if (typeof process !== 'undefined' && process.env?.PROOF_ANDROID_SDK_KEY) {
    return process.env.PROOF_ANDROID_SDK_KEY;
  }
  return 'staging-key-placeholder';
}

// ---------------------------------------------------------------------------
// Screen components
// ---------------------------------------------------------------------------

function DebugConsoleScreen(): React.ReactElement {
  const [, setTick] = useState(0);
  const tick = useRef(0);

  React.useEffect(() => {
    const id = setInterval(() => {
      tick.current += 1;
      setTick(tick.current);
    }, 500);
    return () => clearInterval(id);
  }, []);

  const raw = getDebugStateRaw();
  const log = getEventLog();
  const lastPayload = getLastEventPayload();

  return (
    <ScrollView style={styles.container}>
      <Text style={styles.header}>Debug Console</Text>
      <Text style={styles.subheader}>
        SDK state snapshot + event log (auto-refresh)
      </Text>

      <View style={styles.panel}>
        <View style={styles.row}>
          <Text style={styles.label}>initialized</Text>
          <Text style={[styles.value, raw.initialized ? styles.statusOk : styles.statusFail]}>
            {String(raw.initialized)}
          </Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>sdkVersion</Text>
          <Text style={styles.value}>{raw.version}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>tenantId</Text>
          <Text style={styles.value}>{raw.tenantId ?? '—'}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>workspaceId</Text>
          <Text style={styles.value}>{raw.workspaceId ?? '—'}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>platformId</Text>
          <Text style={styles.value}>{raw.platformId ?? '—'}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>sessionId</Text>
          <Text style={styles.value}>{raw.sessionId ?? '—'}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>anonymousId</Text>
          <Text style={styles.value}>{raw.anonymousId ?? '—'}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>knownUserId</Text>
          <Text style={styles.value}>{raw.knownUserId ?? '—'}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>consentState</Text>
          <Text style={styles.value}>{raw.consentState}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>queueSize</Text>
          <Text style={styles.value}>{String(raw.queueSize)}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>lastDeliveryStatus</Text>
          <Text style={[styles.value, statusColor(raw.lastDeliveryStatus)]}>
            {statusText(raw.lastDeliveryStatus)}
          </Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>lastApiResponse</Text>
          <Text style={styles.value}>{raw.lastApiResponse ?? '—'}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>lastError</Text>
          <Text style={[styles.value, raw.lastError ? styles.statusFail : styles.statusIdle]}>
            {raw.lastError ?? '—'}
          </Text>
        </View>
      </View>

      {lastPayload && (
        <View style={styles.panel}>
          <Text style={[styles.label, { marginBottom: 6, color: '#93c5fd' }]}>
            Last event payload (pretty)
          </Text>
          <Text style={styles.value}>
            {JSON.stringify(lastPayload, null, 2).slice(0, 800)}
            {JSON.stringify(lastPayload, null, 2).length > 800 ? '…' : ''}
          </Text>
        </View>
      )}

      <View style={styles.panel}>
        <Text style={[styles.label, { marginBottom: 6, color: '#93c5fd' }]}>
          Event log ({log.length} entries — newest at top)
        </Text>
        {log.length === 0 ? (
          <Text style={{ color: '#555', fontFamily: 'monospace' }}>
            No events sent yet.
          </Text>
        ) : (
          [...log].reverse().map((entry, idx) => (
            <View key={idx} style={styles.logItem}>
              <Text style={styles.logTs}>{entry.timestamp.slice(11, 23)}</Text>
              <Text style={styles.logType}>{entry.type}</Text>
              <Text style={[styles.logStatus, entry.status === 'failed' ? styles.statusFail : undefined]}>
                {entry.status}
              </Text>
            </View>
          ))
        )}
      </View>

      <View style={{ padding: 12, marginTop: 8 }}>
        <TouchableOpacity
          style={[styles.button, { backgroundColor: '#475569' }]}
          onPress={() => {
            getState();
            tick.current += 1;
            setTick(tick.current);
          }}
        >
          <Text style={styles.buttonText}>Refresh State</Text>
        </TouchableOpacity>
      </View>
    </ScrollView>
  );
}

function InitializationScreen(): React.ReactElement {
  const [result, setResult] = useState<SDKState | null>(null);
  const [loading, setLoading] = useState(false);

  const handleInit = useCallback(async () => {
    setLoading(true);
    setResult(null);
    const s = initSDK({
      tenantId: 'demo-tenant',
      workspaceId: 'demo-workspace',
      apiKey: resolveSdkKey(),
    });
    setResult(s);
    setLoading(false);
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.header}>Initialization</Text>
      <Text style={styles.subheader}>
        Calls Aether.init() from @aether/react-native with the canonical RN
        config, plus SDK-local session / anonymous id setup.
      </Text>
      <TouchableOpacity
        style={[styles.button, loading && { backgroundColor: '#64748b' }]}
        onPress={handleInit}
        disabled={loading}
      >
        {loading && <ActivityIndicator color="#fff" />}
        <Text style={styles.buttonText}>Initialize SDK</Text>
      </TouchableOpacity>

      {result && (
        <View style={styles.panel}>
          <View style={styles.row}>
            <Text style={styles.label}>initialized</Text>
            <Text style={[styles.value, result.initialized ? styles.statusOk : styles.statusFail]}>
              {String(result.initialized)}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>sessionId</Text>
            <Text style={styles.value}>{result.sessionId ?? '—'}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>anonymousId</Text>
            <Text style={styles.value}>{result.anonymousId ?? '—'}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>lastError</Text>
            <Text style={[styles.value, result.lastError ? styles.statusFail : styles.statusIdle]}>
              {result.lastError ?? '—'}
            </Text>
          </View>
        </View>
      )}
    </View>
  );
}

function HeartbeatScreen(): React.ReactElement {
  const [last, setLast] = useState<SDKState | null>(null);
  const [loading, setLoading] = useState(false);

  const handleEmit = useCallback(async () => {
    setLoading(true);
    const s = await emitHeartbeat();
    setLast(s);
    setLoading(false);
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.header}>Heartbeat</Text>
      <Text style={styles.subheader}>
        Sends a canonical heartbeat event to POST /v1/batch (plus observe() side
        channel through the native SDK when linked).
      </Text>
      <TouchableOpacity
        style={[styles.button, loading && { backgroundColor: '#64748b' }]}
        onPress={handleEmit}
        disabled={loading}
      >
        {loading && <ActivityIndicator color="#fff" />}
        <Text style={styles.buttonText}>Emit Heartbeat</Text>
      </TouchableOpacity>

      {last && (
        <View style={styles.panel}>
          <View style={styles.row}>
            <Text style={styles.label}>status</Text>
            <Text style={statusColor(last.lastDeliveryStatus)}>
              {statusText(last.lastDeliveryStatus)}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>lastError</Text>
            <Text style={[styles.value, last.lastError ? styles.statusFail : styles.statusIdle]}>
              {last.lastError ?? '—'}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>lastApiResponse</Text>
            <Text style={styles.value}>{last.lastApiResponse ?? '—'}</Text>
          </View>
        </View>
      )}
    </View>
  );
}

function ScreenTrackingScreen(): React.ReactElement {
  const [last, setLast] = useState<SDKState | null>(null);
  const [loading, setLoading] = useState(false);

  const handleTrack = useCallback(async () => {
    setLoading(true);
    const s = await trackScreen('HeartbeatScreen', { source: 'proof-android' });
    setLast(s);
    setLoading(false);
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.header}>Screen Tracking</Text>
      <Text style={styles.subheader}>
        Calls Aether.screenView() (native) and sends a screen.view envelope to
        POST /v1/batch.
      </Text>
      <TouchableOpacity
        style={[styles.button, loading && { backgroundColor: '#64748b' }]}
        onPress={handleTrack}
        disabled={loading}
      >
        {loading && <ActivityIndicator color="#fff" />}
        <Text style={styles.buttonText}>Track Screen</Text>
      </TouchableOpacity>

      {last && (
        <View style={styles.panel}>
          <View style={styles.row}>
            <Text style={styles.label}>status</Text>
            <Text style={statusColor(last.lastDeliveryStatus)}>
              {statusText(last.lastDeliveryStatus)}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>lastError</Text>
            <Text style={[styles.value, last.lastError ? styles.statusFail : styles.statusIdle]}>
              {last.lastError ?? '—'}
            </Text>
          </View>
        </View>
      )}
    </View>
  );
}

function IdentifyUserScreen(): React.ReactElement {
  const [last, setLast] = useState<SDKState | null>(null);
  const [loading, setLoading] = useState(false);

  const handleIdentify = useCallback(async () => {
    setLoading(true);
    const s = await identifyUser('user-123', { email: 'demo@example.com' });
    setLast(s);
    setLoading(false);
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.header}>Identify User</Text>
      <Text style={styles.subheader}>
        Sends an identity.identify envelope to POST /v1/batch and updates the
        local known user id. (The native SDK owns identity via getIdentity(); JS
        has no direct setter — we send the canonical event instead.)
      </Text>
      <TouchableOpacity
        style={[styles.button, loading && { backgroundColor: '#64748b' }]}
        onPress={handleIdentify}
        disabled={loading}
      >
        {loading && <ActivityIndicator color="#fff" />}
        <Text style={styles.buttonText}>Identify User</Text>
      </TouchableOpacity>

      {last && (
        <View style={styles.panel}>
          <View style={styles.row}>
            <Text style={styles.label}>status</Text>
            <Text style={statusColor(last.lastDeliveryStatus)}>
              {statusText(last.lastDeliveryStatus)}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>knownUserId</Text>
            <Text style={styles.value}>{last.knownUserId ?? '—'}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>lastError</Text>
            <Text style={[styles.value, last.lastError ? styles.statusFail : styles.statusIdle]}>
              {last.lastError ?? '—'}
            </Text>
          </View>
        </View>
      )}
    </View>
  );
}

function ConversionScreen(): React.ReactElement {
  const [last, setLast] = useState<SDKState | null>(null);
  const [loading, setLoading] = useState(false);

  const handleConversion = useCallback(async () => {
    setLoading(true);
    const s = await trackConversion('purchase_completed', 29.99, 'USD');
    setLast(s);
    setLoading(false);
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.header}>Conversion</Text>
      <Text style={styles.subheader}>
        Calls Aether.conversion() (native) and sends a conversion.completed
        envelope to POST /v1/batch.
      </Text>
      <TouchableOpacity
        style={[styles.button, loading && { backgroundColor: '#64748b' }]}
        onPress={handleConversion}
        disabled={loading}
      >
        {loading && <ActivityIndicator color="#fff" />}
        <Text style={styles.buttonText}>Simulate Conversion</Text>
      </TouchableOpacity>

      {last && (
        <View style={styles.panel}>
          <View style={styles.row}>
            <Text style={styles.label}>status</Text>
            <Text style={statusColor(last.lastDeliveryStatus)}>
              {statusText(last.lastDeliveryStatus)}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>lastError</Text>
            <Text style={[styles.value, last.lastError ? styles.statusFail : styles.statusIdle]}>
              {last.lastError ?? '—'}
            </Text>
          </View>
        </View>
      )}
    </View>
  );
}

function OfflineRetryScreen(): React.ReactElement {
  const [lastFlush, setLastFlush] = useState<SDKState | null>(null);
  const [lastOffline, setLastOffline] = useState<SDKState | null>(null);
  const [loading, setLoading] = useState(false);

  const handleFlush = useCallback(() => {
    setLoading(true);
    const s = flushQueue();
    setLastFlush(s);
    setLastOffline(null);
    setLoading(false);
  }, []);

  const handleOffline = useCallback(() => {
    const s = simulateOffline();
    setLastOffline(s);
    setLastFlush(null);
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.header}>Offline / Retry</Text>
      <Text style={styles.subheader}>
        Calls Aether.flush() (native) and clears the harness queue tracking.
        Simulate offline to queue events for retry.
      </Text>

      <TouchableOpacity
        style={[styles.button, styles.buttonSuccess, loading && { backgroundColor: '#64748b' }]}
        onPress={handleFlush}
        disabled={loading}
      >
        {loading && <ActivityIndicator color="#fff" />}
        <Text style={styles.buttonText}>Flush Queue</Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={[styles.button, styles.buttonWarning]}
        onPress={handleOffline}
        disabled={loading}
      >
        <Text style={styles.buttonText}>Simulate Offline</Text>
      </TouchableOpacity>

      {lastFlush && (
        <View style={styles.panel}>
          <View style={styles.row}>
            <Text style={styles.label}>status</Text>
            <Text style={statusColor(lastFlush.lastDeliveryStatus)}>
              {statusText(lastFlush.lastDeliveryStatus)}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>lastApiResponse</Text>
            <Text style={styles.value}>{lastFlush.lastApiResponse ?? '—'}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>queueSize</Text>
            <Text style={styles.value}>{String(lastFlush.queueSize)}</Text>
          </View>
        </View>
      )}

      {lastOffline && (
        <View style={styles.panel}>
          <View style={styles.row}>
            <Text style={styles.label}>status</Text>
            <Text style={statusColor(lastOffline.lastDeliveryStatus)}>
              {statusText(lastOffline.lastDeliveryStatus)}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>queueSize</Text>
            <Text style={styles.value}>{String(lastOffline.queueSize)}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>lastError</Text>
            <Text style={[styles.value, styles.statusFail]}>
              {lastOffline.lastError ?? '—'}
            </Text>
          </View>
        </View>
      )}
    </View>
  );
}

function ConsentStateScreen(): React.ReactElement {
  const [last, setLast] = useState<SDKState | null>(null);

  const handleGrant = useCallback(() => {
    const s = setConsent('analytics', true);
    setLast(s);
  }, []);

  const handleDeny = useCallback(() => {
    const s = setConsent('analytics', false);
    setLast(s);
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.header}>Consent State</Text>
      <Text style={styles.subheader}>
        Maps to Aether.consent.grant() / revoke() in the native SDK for the
        'analytics' purpose.
      </Text>
      <TouchableOpacity style={[styles.button, styles.buttonSuccess]} onPress={handleGrant}>
        <Text style={styles.buttonText}>Grant Consent</Text>
      </TouchableOpacity>
      <TouchableOpacity style={[styles.button, styles.buttonDanger]} onPress={handleDeny}>
        <Text style={styles.buttonText}>Deny Consent</Text>
      </TouchableOpacity>

      {last && (
        <View style={styles.panel}>
          <View style={styles.row}>
            <Text style={styles.label}>consentState</Text>
            <Text style={styles.value}>{last.consentState}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.label}>lastError</Text>
            <Text style={[styles.value, last.lastError ? styles.statusFail : styles.statusIdle]}>
              {last.lastError ?? '—'}
            </Text>
          </View>
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------

const TABBED_SCREENS: Record<string, React.ElementType> = {
  Initialization: InitializationScreen,
  Heartbeat: HeartbeatScreen,
  'Screen Tracking': ScreenTrackingScreen,
  'Identify User': IdentifyUserScreen,
  Conversion: ConversionScreen,
  'Offline/Retry': OfflineRetryScreen,
  'Consent State': ConsentStateScreen,
  'Debug Console': DebugConsoleScreen,
};

// ---------------------------------------------------------------------------
// App root
// ---------------------------------------------------------------------------

export function App(): React.ReactElement {
  const [activeScreen, setActiveScreen] = useState<string>('Initialization');

  const ActiveComponent = TABBED_SCREENS[activeScreen] ?? View;

  return (
    <View style={styles.container}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={{ marginBottom: 16 }}
      >
        {Object.keys(TABBED_SCREENS).map((name) => (
          <TouchableOpacity
            key={name}
            onPress={() => {
              setActiveScreen(name);
              trackScreen(name, { source: 'tab-bar' }).catch(() => {});
            }}
            style={[
              styles.tab,
              activeScreen === name ? styles.tabActive : undefined,
            ]}
          >
            <Text
              style={{
                color: activeScreen === name ? '#fff' : '#aaa',
                fontSize: 14,
              }}
            >
              {name}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>
      <ActiveComponent />
    </View>
  );
}
