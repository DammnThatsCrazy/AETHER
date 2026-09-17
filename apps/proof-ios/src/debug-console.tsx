// =============================================================================
// Aether SDK Proof Harness — Debug Console (apps/proof-ios)
// Real-time view of SDK state + event log. Updates as events are sent.
// =============================================================================

import React, { useState, useEffect } from 'react';
import { View, Text, ScrollView, StyleSheet } from 'react-native';
import { getState, getEventLog, getLastEventPayload } from './sdk';
import type { SDKState } from './types';

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16, backgroundColor: '#0a0a0a' },
  header: { fontSize: 24, fontWeight: 'bold', marginBottom: 4, color: '#fff' },
  subheader: { fontSize: 14, color: '#888', marginBottom: 16 },
  section: {
    backgroundColor: '#111',
    borderColor: '#333',
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    marginBottom: 16,
  },
  sectionTitle: { color: '#93c5fd', fontSize: 14, fontWeight: '600', marginBottom: 8 },
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
  gridItem: { width: '50%' },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3 },
  label: { color: '#aaa', fontSize: 13 },
  value: { color: '#fff', fontFamily: 'monospace', fontSize: 13 },
  empty: { color: '#555', fontStyle: 'italic', fontSize: 13 },
  logItem: {
    borderBottomColor: '#222',
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingVertical: 6,
    flexDirection: 'row',
    alignItems: 'center',
  },
  logTimestamp: { color: '#666', fontSize: 11, width: 90, fontFamily: 'monospace' },
  logType: { color: '#93c5fd', flex: 1, fontSize: 13 },
  logStatusDelivered: { color: '#4ade80', fontSize: 11, fontFamily: 'monospace', width: 80, textAlign: 'right' },
  logStatusFailed: { color: '#f87171', fontSize: 11, fontFamily: 'monospace', width: 80, textAlign: 'right' },
  logStatusPending: { color: '#fbbf24', fontSize: 11, fontFamily: 'monospace', width: 80, textAlign: 'right' },
  logStatusIdle: { color: '#888', fontSize: 11, fontFamily: 'monospace', width: 80, textAlign: 'right' },
  payloadSection: { marginTop: 4 },
  payloadLabel: { color: '#93c5fd', fontSize: 14, fontWeight: '600', marginBottom: 4 },
  payloadText: { color: '#ccc', fontFamily: 'monospace', fontSize: 11, lineHeight: 16 },
});

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DebugConsole(): React.ReactElement {
  const [state, setState] = useState<SDKState | null>(null);
  const [eventLog, setEventLog] = useState<ReturnType<typeof getEventLog>>([]);
  const [lastPayload, setLastPayload] = useState<string>('');

  useEffect(() => {
    // Poll SDK state + event log every 500ms so the console updates as events
    // are sent from other screens.
    const interval = setInterval(() => {
      setState(getState());
      setEventLog(getEventLog());
      const payload = getLastEventPayload();
      setLastPayload(
        payload
          ? JSON.stringify(payload, null, 2)
          : '',
      );
    }, 500);
    return () => clearInterval(interval);
  }, []);

  if (!state) {
    return (
      <View style={styles.container}>
        <Text style={styles.header}>Debug Console</Text>
        <Text style={styles.subheader}>Loading SDK state…</Text>
      </View>
    );
  }

  const statusClass = (s: SDKState['lastDeliveryStatus']) => {
    if (s === 'delivered') return styles.logStatusDelivered;
    if (s === 'failed') return styles.logStatusFailed;
    if (s === 'pending') return styles.logStatusPending;
    return styles.logStatusIdle;
  };

  return (
    <ScrollView style={styles.container}>
      <Text style={styles.header}>Debug Console</Text>
      <Text style={styles.subheader}>
        SDK state + event log (auto-refreshes every 500ms)
      </Text>

      {/* ── SDK State ──────────────────────────────────────────────────── */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>SDK State</Text>
        <View style={styles.grid}>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>initialized</Text>
              <Text style={[styles.value, state.initialized ? { color: '#4ade80' } : { color: '#f87171' }]}>
                {String(state.initialized)}
              </Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>sdkVersion</Text>
              <Text style={styles.value}>{state.version}</Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>tenantId</Text>
              <Text style={styles.value}>{state.tenantId ?? '—'}</Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>workspaceId</Text>
              <Text style={styles.value}>{state.workspaceId ?? '—'}</Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>platformId</Text>
              <Text style={styles.value}>{state.platformId ?? '—'}</Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>sessionId</Text>
              <Text style={styles.value}>{state.sessionId ?? '—'}</Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>anonymousId</Text>
              <Text style={styles.value}>{state.anonymousId ?? '—'}</Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>knownUserId</Text>
              <Text style={styles.value}>{state.knownUserId ?? '—'}</Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>consentState</Text>
              <Text style={styles.value}>{state.consentState}</Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>queueSize</Text>
              <Text style={styles.value}>{String(state.queueSize)}</Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>lastDeliveryStatus</Text>
              <Text style={[styles.value, state.lastDeliveryStatus === 'delivered' ? { color: '#4ade80' } : state.lastDeliveryStatus === 'failed' ? { color: '#f87171' } : undefined]}>
                {state.lastDeliveryStatus}
              </Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>lastApiResponse</Text>
              <Text style={styles.value}>{state.lastApiResponse ?? '—'}</Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>lastError</Text>
              <Text style={[styles.value, state.lastError ? { color: '#f87171' } : undefined]}>
                {state.lastError ?? '—'}
              </Text>
            </View>
          </View>
          <View style={styles.gridItem}>
            <View style={styles.row}>
              <Text style={styles.label}>lastEventId</Text>
              <Text style={styles.value}>—</Text>
            </View>
          </View>
        </View>
      </View>

      {/* ── Last event payload ──────────────────────────────────────────── */}
      {lastPayload ? (
        <View style={[styles.section, styles.payloadSection]}>
          <Text style={styles.payloadLabel}>Last event payload</Text>
          <Text style={styles.payloadText}>{lastPayload.slice(0, 1500)}</Text>
          {lastPayload.length > 1500 && (
            <Text style={{ color: '#666', fontSize: 11 }}>… (truncated)</Text>
          )}
        </View>
      ) : null}

      {/* ── Event log ───────────────────────────────────────────────────── */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Event Log</Text>
        {eventLog.length === 0 ? (
          <Text style={styles.empty}>No events sent yet.</Text>
        ) : (
          [...eventLog].reverse().map((entry, idx) => (
            <View key={idx} style={styles.logItem}>
              <Text style={styles.logTimestamp}>{entry.timestamp.slice(11, 23)}</Text>
              <Text style={styles.logType}>{entry.type}</Text>
              <Text style={statusClass(entry.status)}>{entry.status}</Text>
            </View>
          ))
        )}
      </View>

      {/* Bottom padding for safe area */}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}
