/**
 * Account — read-only trusted devices + workforce sessions (M4a).
 *
 * Consumes GET /v1/kyber/devices and GET /v1/kyber/auth/sessions via the typed
 * client. Devices render their approval / risk state as chips; sessions render
 * their status and authentication strength. Read-only — no approve / suspend /
 * revoke / rename device and no session-revoke actions (governed actions are
 * M5/M6, out of scope).
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { kyberOps, type KyberDevice, type KyberSession } from '../kyberOps';
import { useOpsFetch, type OpsFetchStatus } from '../useOpsFetch';
import { OperatorContinuationsPanel } from '../components/OperatorContinuationsPanel';
import { EmptyState, ErrorState, LoadingState } from '../components/ScreenStatus';

function approvalColor(state: string): string {
  switch (state) {
    case 'approved':
      return theme.colors.success;
    case 'pending':
      return theme.colors.warning;
    case 'suspended':
    case 'revoked':
    case 'expired':
      return theme.colors.danger;
    default:
      return theme.colors.muted;
  }
}

function riskColor(state: string): string {
  switch (state) {
    case 'ok':
      return theme.colors.success;
    case 'suspect':
      return theme.colors.warning;
    case 'blocked':
      return theme.colors.danger;
    default:
      return theme.colors.muted;
  }
}

function sessionColor(status: string): string {
  switch (status) {
    case 'active':
      return theme.colors.success;
    case 'restricted':
    case 'risk_limited':
      return theme.colors.warning;
    case 'revoked':
    case 'expired':
    case 'locked':
      return theme.colors.danger;
    default:
      return theme.colors.muted;
  }
}

function chip(label: string, color: string): React.JSX.Element {
  return <Text style={[styles.chip, { color, borderColor: color }]}>{label}</Text>;
}

function DeviceRow({ device }: { device: KyberDevice }): React.JSX.Element {
  return (
    <Card style={styles.row}>
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{device.display_name}</Text>
        <View style={styles.chipRow}>
          {chip(device.approval_state, approvalColor(device.approval_state))}
          {chip(`risk ${device.risk_state}`, riskColor(device.risk_state))}
        </View>
        <Text style={styles.rowMeta}>
          {device.device_id}
          {device.platform_family ? ` · ${device.platform_family}` : ''}
          {device.browser_family ? ` · ${device.browser_family}` : ''}
        </Text>
        <Text style={styles.rowMeta}>
          requested {device.requested_at ?? '—'}
          {device.last_used_at ? ` · last used ${device.last_used_at}` : ''}
        </Text>
      </View>
    </Card>
  );
}

function SessionRow({ session }: { session: KyberSession }): React.JSX.Element {
  return (
    <Card style={styles.row}>
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{session.session_id}</Text>
        <View style={styles.chipRow}>
          {chip(session.status, sessionColor(session.status))}
          {chip(session.authentication_strength, theme.colors.accentHover)}
          {chip(session.environment, theme.colors.muted)}
        </View>
        <Text style={styles.rowMeta}>
          {session.authentication_methods.join(', ') || 'no methods recorded'}
        </Text>
        <Text style={styles.rowMeta}>
          created {session.created_at}
          {session.last_seen_at ? ` · last seen ${session.last_seen_at}` : ''}
        </Text>
      </View>
    </Card>
  );
}

function AccountContent({
  devices,
  sessions,
}: {
  devices: KyberDevice[];
  sessions: KyberSession[];
}): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.sectionLabel}>
        Trusted devices · {devices.length}
      </Text>
      {devices.length === 0 ? (
        <EmptyState message="No trusted devices." />
      ) : (
        devices.map((device) => <DeviceRow key={device.device_id} device={device} />)
      )}

      <Text style={[styles.sectionLabel, styles.listLabel]}>
        Sessions · {sessions.length}
      </Text>
      {sessions.length === 0 ? (
        <EmptyState message="No active sessions." />
      ) : (
        sessions.map((session) => <SessionRow key={session.session_id} session={session} />)
      )}

      <OperatorContinuationsPanel />

      <Text style={styles.readOnlyNote}>
        Read-only in this build — device and session actions arrive in a later milestone.
      </Text>
    </ScrollView>
  );
}

export default function AccountScreen(): React.JSX.Element {
  const devices = useOpsFetch(() => kyberOps.getDevices());
  const sessions = useOpsFetch(() => kyberOps.getSessions());

  const status: OpsFetchStatus =
    devices.status === 'loading' || sessions.status === 'loading'
      ? 'loading'
      : devices.status === 'error' || sessions.status === 'error'
        ? 'error'
        : 'fresh';

  const firstError = devices.error ?? sessions.error;

  const retry = (): void => {
    devices.refresh();
    sessions.refresh();
  };

  return (
    <Screen title="Account" subtitle="Devices and sessions">
      {status === 'loading' && (devices.data === null || sessions.data === null) ? (
        <LoadingState />
      ) : status === 'error' && (devices.data === null || sessions.data === null) ? (
        <ErrorState message={firstError?.message ?? 'Unknown error'} onRetry={retry} />
      ) : devices.data !== null && sessions.data !== null ? (
        <AccountContent devices={devices.data.devices} sessions={sessions.data} />
      ) : (
        <EmptyState message="Nothing to show yet." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  sectionLabel: { color: theme.colors.muted, fontSize: theme.type.label.fontSize },
  listLabel: { marginTop: theme.spacing.lg },
  row: { gap: theme.spacing.sm },
  rowText: { flex: 1, gap: theme.spacing.xs },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.xs },
  chip: {
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 2,
    borderRadius: theme.radii.pill,
    borderWidth: StyleSheet.hairlineWidth,
    fontSize: theme.type.caption.fontSize,
    fontWeight: '600',
  },
  rowTitle: { color: theme.colors.text, fontSize: theme.type.body.fontSize, fontWeight: '600' },
  rowMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  readOnlyNote: {
    color: theme.colors.muted,
    fontSize: theme.type.caption.fontSize,
    textAlign: 'center',
    marginTop: theme.spacing.lg,
  },
});
