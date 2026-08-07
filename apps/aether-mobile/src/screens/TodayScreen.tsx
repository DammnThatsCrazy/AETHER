/**
 * Today — the digest surface (M3b).
 *
 * Consumes GET /v1/mobile/today via the typed projection client, showing
 * severity-banded alert counts plus redacted notification titles. Read-only: it
 * only ever renders the projection's redacted `title` fields — never raw bodies.
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { alertBands, bandForSeverity, projections, type TodayProjection } from '../projections';
import { useProjection } from '../useProjection';
import { bandColor, EmptyState, ErrorState, LoadingState, StatusBadge } from '../components/ScreenStatus';

const BAND_LABELS: Record<(typeof alertBands)[number], string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  info: 'Info',
};

function TodayContent({ data }: { data: TodayProjection }): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Card style={styles.card}>
        <Text style={styles.cardTitle}>Alerts</Text>
        <View style={styles.bandRow}>
          {alertBands.map((band) => (
            <View key={band} style={styles.band}>
              <Text style={[styles.bandCount, { color: bandColor(band) }]}>{data.alert_counts[band] ?? 0}</Text>
              <Text style={styles.bandLabel}>{BAND_LABELS[band]}</Text>
            </View>
          ))}
        </View>
      </Card>

      <Text style={styles.sectionLabel}>Notifications</Text>
      {data.notifications.length === 0 ? (
        <EmptyState message="No notifications right now." />
      ) : (
        data.notifications.map((notification) => (
          <Card key={notification.notification_id} style={styles.notifCard}>
            <View style={[styles.dot, { backgroundColor: bandColor(bandForSeverity(notification.severity)) }]} />
            <View style={styles.notifText}>
              <Text style={styles.notifTitle}>{notification.title}</Text>
              <Text style={styles.notifMeta}>{notification.detected_at}</Text>
            </View>
          </Card>
        ))
      )}
    </ScrollView>
  );
}

export default function TodayScreen(): React.JSX.Element {
  const { data, status, error, refresh } = useProjection('today', () => projections.getToday());

  return (
    <Screen title="Today" subtitle="Your day at a glance" accessory={<StatusBadge status={status} />}>
      {status === 'loading' && data === null ? (
        <LoadingState />
      ) : status === 'error' && data === null ? (
        <ErrorState message={error?.message ?? 'Unknown error'} onRetry={refresh} />
      ) : data !== null ? (
        <TodayContent data={data} />
      ) : (
        <EmptyState message="Nothing to show yet." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  card: { marginBottom: theme.spacing.sm },
  cardTitle: { color: theme.colors.text, fontSize: theme.type.subtitle.fontSize, fontWeight: '600' },
  bandRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: theme.spacing.md,
  },
  band: { alignItems: 'center', gap: theme.spacing.xs },
  bandCount: { fontSize: 26, fontWeight: '700' },
  bandLabel: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  sectionLabel: { color: theme.colors.muted, fontSize: theme.type.label.fontSize, marginTop: theme.spacing.sm },
  notifCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.md,
    paddingVertical: theme.spacing.md,
  },
  dot: { width: 10, height: 10, borderRadius: theme.radii.pill },
  notifText: { flex: 1 },
  notifTitle: { color: theme.colors.text, fontSize: theme.type.body.fontSize },
  notifMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize, marginTop: 2 },
});
