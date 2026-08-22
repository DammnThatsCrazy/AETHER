/**
 * Exceptions — the operator queue (M4a).
 *
 * Consumes GET /v1/kyber/ops/exceptions via the typed client. Shows the
 * prioritised exception queue, redacted: severity / bucket / status / title /
 * signal count / priority score / last-seen timestamp and the number of affected
 * services. Read-only — no acknowledge / resolve / suppress actions (M5/M6).
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { kyberOps, type KyberException, type KyberExceptionQueue } from '../kyberOps';
import { useOpsFetch } from '../useOpsFetch';
import { EmptyState, ErrorState, kyberSeverityColor, LoadingState } from '../components/ScreenStatus';

function ExceptionRow({ item }: { item: KyberException }): React.JSX.Element {
  return (
    <Card style={styles.row}>
      <View style={[styles.dot, { backgroundColor: kyberSeverityColor(item.severity) }]} />
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{item.title}</Text>
        <View style={styles.chipRow}>
          <Text style={[styles.chip, styles.severityChip]}>{item.severity}</Text>
          <Text style={[styles.chip, styles.bucketChip]}>{item.bucket}</Text>
          <Text style={[styles.chip, styles.statusChip]}>{item.status}</Text>
        </View>
        <Text style={styles.rowMeta}>
          {item.signal_count} signal{item.signal_count === 1 ? '' : 's'} · score{' '}
          {item.priority_score.toFixed(3)} · {item.affected_services.length} service
          {item.affected_services.length === 1 ? '' : 's'} · last seen {item.last_seen_at}
        </Text>
      </View>
    </Card>
  );
}

function ExceptionsContent({ queue }: { queue: KyberExceptionQueue }): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.sectionLabel}>
        Queue · {queue.total} open exception{queue.total === 1 ? '' : 's'} · {queue.generated_at}
      </Text>
      {queue.items.length === 0 ? (
        <EmptyState message="No open exceptions right now." />
      ) : (
        queue.items.map((item) => <ExceptionRow key={item.exception_id} item={item} />)
      )}
    </ScrollView>
  );
}

export default function ExceptionsScreen(): React.JSX.Element {
  const { data, status, error, refresh } = useOpsFetch(() => kyberOps.getExceptions());

  return (
    <Screen title="Exceptions" subtitle="Operator queue">
      {status === 'loading' && data === null ? (
        <LoadingState />
      ) : status === 'error' && data === null ? (
        <ErrorState message={error?.message ?? 'Unknown error'} onRetry={refresh} />
      ) : data !== null ? (
        <ExceptionsContent queue={data} />
      ) : (
        <EmptyState message="Nothing to show yet." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  sectionLabel: { color: theme.colors.muted, fontSize: theme.type.label.fontSize },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: theme.spacing.md },
  dot: { width: 10, height: 10, borderRadius: theme.radii.pill, marginTop: 5 },
  rowText: { flex: 1, gap: theme.spacing.xs },
  rowTitle: { color: theme.colors.text, fontSize: theme.type.body.fontSize, fontWeight: '600' },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.xs },
  chip: {
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 2,
    borderRadius: theme.radii.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.border,
    fontSize: theme.type.caption.fontSize,
    color: theme.colors.muted,
  },
  severityChip: { borderColor: theme.colors.warning, color: theme.colors.warning },
  bucketChip: { borderColor: theme.colors.accent, color: theme.colors.accentHover },
  statusChip: { borderColor: theme.colors.border, color: theme.colors.muted },
  rowMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
});
