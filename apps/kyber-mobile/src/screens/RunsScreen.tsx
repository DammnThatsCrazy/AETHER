/**
 * Runs — durable worker runs + stuck-run recovery list (M4a).
 *
 * Consumes GET /v1/agent/runs and GET /v1/agent/runs/stuck via the typed client.
 * Shows recent runs (controller / status / attempt / objective / created / error)
 * and the stuck-run recovery list. Read-only — no replay / cancel actions (M5/M6).
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { kyberOps, type AgentRun } from '../kyberOps';
import { useOpsFetch, type OpsFetchStatus } from '../useOpsFetch';
import { EmptyState, ErrorState, LoadingState } from '../components/ScreenStatus';

function runStatusColor(status: string): string {
  switch (status) {
    case 'completed':
      return theme.colors.success;
    case 'queued':
    case 'running':
    case 'retry':
      return theme.colors.warning;
    case 'failed':
    case 'dispatch_failed':
      return theme.colors.danger;
    case 'stale':
      return theme.colors.muted;
    default:
      return theme.colors.muted;
  }
}

function RunRow({ run }: { run: AgentRun }): React.JSX.Element {
  return (
    <Card style={styles.row}>
      <View style={styles.rowText}>
        <View style={styles.chipRow}>
          <Text style={[styles.chip, { color: runStatusColor(run.status), borderColor: runStatusColor(run.status) }]}>
            {run.status}
          </Text>
          <Text style={styles.chip}>{run.controller}</Text>
          {run.queue ? <Text style={styles.chip}>queue {run.queue}</Text> : null}
        </View>
        <Text style={styles.rowTitle}>{run.run_id}</Text>
        <Text style={styles.rowMeta}>
          objective {run.objective_id} · attempt {run.attempt}
        </Text>
        <Text style={styles.rowMeta}>created {run.created_at} · updated {run.updated_at}</Text>
        {run.error ? <Text style={styles.errorText}>{run.error}</Text> : null}
      </View>
    </Card>
  );
}

function RunsContent({
  runs,
  stuck,
}: {
  runs: AgentRun[];
  stuck: AgentRun[];
}): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.sectionLabel}>
        Stuck runs · {stuck.length} need recovery
      </Text>
      {stuck.length === 0 ? (
        <EmptyState message="No stuck runs." />
      ) : (
        stuck.map((run) => <RunRow key={run.run_id} run={run} />)
      )}

      <Text style={[styles.sectionLabel, styles.listLabel]}>
        Recent runs · {runs.length}
      </Text>
      {runs.length === 0 ? (
        <EmptyState message="No runs recorded." />
      ) : (
        runs.map((run) => <RunRow key={run.run_id} run={run} />)
      )}
    </ScrollView>
  );
}

export default function RunsScreen(): React.JSX.Element {
  const runs = useOpsFetch(() => kyberOps.getRuns());
  const stuck = useOpsFetch(() => kyberOps.getStuckRuns());

  const status: OpsFetchStatus =
    runs.status === 'loading' || stuck.status === 'loading'
      ? 'loading'
      : runs.status === 'error' || stuck.status === 'error'
        ? 'error'
        : 'fresh';

  const firstError = runs.error ?? stuck.error;

  const retry = (): void => {
    runs.refresh();
    stuck.refresh();
  };

  return (
    <Screen title="Runs" subtitle="Worker run queue">
      {status === 'loading' && (runs.data === null || stuck.data === null) ? (
        <LoadingState />
      ) : status === 'error' && (runs.data === null || stuck.data === null) ? (
        <ErrorState message={firstError?.message ?? 'Unknown error'} onRetry={retry} />
      ) : runs.data !== null && stuck.data !== null ? (
        <RunsContent runs={runs.data.runs} stuck={stuck.data.runs} />
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
    borderColor: theme.colors.border,
    fontSize: theme.type.caption.fontSize,
    color: theme.colors.muted,
    fontWeight: '600',
  },
  rowTitle: { color: theme.colors.text, fontSize: theme.type.body.fontSize, fontWeight: '600' },
  rowMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  errorText: { color: theme.colors.danger, fontSize: theme.type.caption.fontSize },
});
