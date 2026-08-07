/**
 * Alerts — the read-only inbox (M3b).
 *
 * Consumes GET /v1/mobile/alerts via the typed projection client. Lists redacted
 * notification titles only (never raw bodies/PII) with a per-item severity dot.
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { bandForSeverity, projections, type AlertsProjection } from '../projections';
import { useProjection } from '../useProjection';
import { EmptyState, ErrorState, LoadingState, severityColor, StatusBadge } from '../components/ScreenStatus';

function AlertsContent({ data }: { data: AlertsProjection }): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.sectionLabel}>
        Inbox · {data.unread_count} unread
      </Text>
      {data.items.length === 0 ? (
        <EmptyState message="You’re all caught up." />
      ) : (
        data.items.map((item) => (
          <Card key={item.notification_id} style={styles.row}>
            <View style={[styles.dot, { backgroundColor: severityColor(item.severity) }]} />
            <View style={styles.rowText}>
              <Text style={styles.rowTitle}>{item.title}</Text>
              <Text style={styles.rowMeta}>
                {item.severity} · {item.detected_at}
              </Text>
            </View>
          </Card>
        ))
      )}
    </ScrollView>
  );
}

export default function AlertsScreen(): React.JSX.Element {
  const { data, status, error, refresh } = useProjection('alerts', () => projections.getAlerts());

  return (
    <Screen title="Alerts" subtitle="Inbox" accessory={<StatusBadge status={status} />}>
      {status === 'loading' && data === null ? (
        <LoadingState />
      ) : status === 'error' && data === null ? (
        <ErrorState message={error?.message ?? 'Unknown error'} onRetry={refresh} />
      ) : data !== null ? (
        <AlertsContent data={data} />
      ) : (
        <EmptyState message="No alerts right now." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  sectionLabel: { color: theme.colors.muted, fontSize: theme.type.label.fontSize },
  row: { flexDirection: 'row', alignItems: 'center', gap: theme.spacing.md },
  dot: { width: 10, height: 10, borderRadius: theme.radii.pill },
  rowText: { flex: 1 },
  rowTitle: { color: theme.colors.text, fontSize: theme.type.body.fontSize },
  rowMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize, marginTop: 2 },
});
