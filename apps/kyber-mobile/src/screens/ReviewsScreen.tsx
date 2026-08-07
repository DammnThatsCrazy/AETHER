/**
 * Reviews — the staged-mutation review queue (M4a).
 *
 * Consumes GET /v1/agent/review-batches via the typed client. Lists review
 * batches with their status, objective id, mutation count and review outcome
 * fields. Read-only — no approve / reject / quarantine / reconcile actions
 * (M5/M6).
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { kyberOps, type AgentReviewBatch } from '../kyberOps';
import { useOpsFetch } from '../useOpsFetch';
import { EmptyState, ErrorState, LoadingState } from '../components/ScreenStatus';

function statusColor(status: string): string {
  switch (status) {
    case 'pending':
      return theme.colors.warning;
    case 'approved':
    case 'committed':
      return theme.colors.success;
    case 'rejected':
    case 'quarantined':
    case 'rolled_back':
      return theme.colors.danger;
    default:
      return theme.colors.muted;
  }
}

function ReviewRow({ batch }: { batch: AgentReviewBatch }): React.JSX.Element {
  return (
    <Card style={styles.row}>
      <View style={styles.rowText}>
        <View style={styles.chipRow}>
          <Text style={[styles.chip, { color: statusColor(batch.status), borderColor: statusColor(batch.status) }]}>
            {batch.status}
          </Text>
        </View>
        <Text style={styles.rowTitle}>{batch.batch_id}</Text>
        <Text style={styles.rowMeta}>
          objective {batch.objective_id} · {batch.mutation_ids.length} mutation
          {batch.mutation_ids.length === 1 ? '' : 's'}
        </Text>
        <Text style={styles.rowMeta}>created {batch.created_at}</Text>
        {batch.reviewed_by ? (
          <Text style={styles.rowMeta}>reviewed by {batch.reviewed_by}</Text>
        ) : null}
      </View>
    </Card>
  );
}

function ReviewsContent({ data }: { data: { batches: AgentReviewBatch[]; total: number } }): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.sectionLabel}>
        Review queue · {data.total} batch{data.total === 1 ? '' : 'es'}
      </Text>
      {data.batches.length === 0 ? (
        <EmptyState message="No review batches right now." />
      ) : (
        data.batches.map((batch) => <ReviewRow key={batch.batch_id} batch={batch} />)
      )}
    </ScrollView>
  );
}

export default function ReviewsScreen(): React.JSX.Element {
  const { data, status, error, refresh } = useOpsFetch(() => kyberOps.getReviewBatches());

  return (
    <Screen title="Reviews" subtitle="Staged-mutation review">
      {status === 'loading' && data === null ? (
        <LoadingState />
      ) : status === 'error' && data === null ? (
        <ErrorState message={error?.message ?? 'Unknown error'} onRetry={refresh} />
      ) : data !== null ? (
        <ReviewsContent data={data} />
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
    fontSize: theme.type.caption.fontSize,
    fontWeight: '600',
  },
  rowTitle: { color: theme.colors.text, fontSize: theme.type.body.fontSize, fontWeight: '600' },
  rowMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
});
