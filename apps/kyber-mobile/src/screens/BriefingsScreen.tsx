/**
 * Briefings — the durable operator briefing feed (M4a).
 *
 * Consumes GET /v1/agent/briefings via the typed client. Each briefing is shown
 * as its operator-facing summary plus redacted section digest (attention items,
 * kill-switch posture, pending-review count) and timestamps. Read-only.
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { kyberOps, type AgentBriefing } from '../kyberOps';
import { useOpsFetch } from '../useOpsFetch';
import { EmptyState, ErrorState, LoadingState } from '../components/ScreenStatus';

function BriefingRow({ briefing }: { briefing: AgentBriefing }): React.JSX.Element {
  const attention = briefing.sections.attention ?? [];
  return (
    <Card style={styles.row}>
      <View style={styles.rowText}>
        <View style={styles.chipRow}>
          <Text style={styles.chip}>{briefing.type}</Text>
        </View>
        <Text style={styles.rowTitle}>{briefing.summary}</Text>
        <Text style={styles.rowMeta}>
          {attention.length} attention item{attention.length === 1 ? '' : 's'} · created{' '}
          {briefing.created_at}
        </Text>
        {briefing.sections.kill_switch.enabled ? (
          <Text style={styles.killSwitch}>Kill switch engaged.</Text>
        ) : null}
        {briefing.sections.review.pending_batches > 0 ? (
          <Text style={styles.rowMeta}>
            {briefing.sections.review.pending_batches} review batch
            {briefing.sections.review.pending_batches === 1 ? '' : 'es'} awaiting approval
          </Text>
        ) : null}
      </View>
    </Card>
  );
}

function BriefingsContent({ data }: { data: { briefings: AgentBriefing[]; total: number } }): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.sectionLabel}>
        Briefings · {data.total} on record
      </Text>
      {data.briefings.length === 0 ? (
        <EmptyState message="No briefings yet." />
      ) : (
        data.briefings.map((briefing) => <BriefingRow key={briefing.briefing_id} briefing={briefing} />)
      )}
    </ScrollView>
  );
}

export default function BriefingsScreen(): React.JSX.Element {
  const { data, status, error, refresh } = useOpsFetch(() => kyberOps.getBriefings());

  return (
    <Screen title="Briefings" subtitle="Operator briefs">
      {status === 'loading' && data === null ? (
        <LoadingState />
      ) : status === 'error' && data === null ? (
        <ErrorState message={error?.message ?? 'Unknown error'} onRetry={refresh} />
      ) : data !== null ? (
        <BriefingsContent data={data} />
      ) : (
        <EmptyState message="Nothing to show yet." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  sectionLabel: { color: theme.colors.muted, fontSize: theme.type.label.fontSize },
  row: { gap: theme.spacing.sm },
  rowText: { flex: 1, gap: theme.spacing.xs },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.xs },
  chip: {
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 2,
    borderRadius: theme.radii.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.accent,
    color: theme.colors.accentHover,
    fontSize: theme.type.caption.fontSize,
    fontWeight: '600',
  },
  rowTitle: { color: theme.colors.text, fontSize: theme.type.body.fontSize, fontWeight: '600' },
  rowMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  killSwitch: { color: theme.colors.danger, fontSize: theme.type.caption.fontSize, fontWeight: '600' },
});
