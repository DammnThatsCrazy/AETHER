/**
 * Explore — saved-views browsing (M3b).
 *
 * Consumes the `/v1/mobile/briefing` exploration projection via the typed client
 * and renders its saved views. Shares the `briefing` cache key with Copilot, so
 * both tabs read the same projection without a second network round-trip. Read-only.
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { projections, type BriefingProjection, type SavedView } from '../projections';
import { useProjection } from '../useProjection';
import { EmptyState, ErrorState, LoadingState, StatusBadge } from '../components/ScreenStatus';

function SavedViewRow({ view }: { view: SavedView }): React.JSX.Element {
  return (
    <Card style={styles.row}>
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{view.title}</Text>
        <Text style={styles.rowMeta}>
          {view.kind}
          {typeof view.item_count === 'number' ? ` · ${view.item_count} items` : ''}
          {view.updated_at ? ` · updated ${view.updated_at}` : ''}
        </Text>
      </View>
    </Card>
  );
}

function ExploreContent({ data }: { data: BriefingProjection }): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.sectionLabel}>Saved views</Text>
      {data.saved_views.length === 0 ? (
        <EmptyState message="No saved views yet. Saved views will appear here." />
      ) : (
        data.saved_views.map((view) => <SavedViewRow key={view.view_id} view={view} />)
      )}
    </ScrollView>
  );
}

export default function ExploreScreen(): React.JSX.Element {
  const { data, status, error, refresh } = useProjection('briefing', () => projections.getBriefing());

  return (
    <Screen title="Explore" subtitle="Saved views" accessory={<StatusBadge status={status} />}>
      {status === 'loading' && data === null ? (
        <LoadingState />
      ) : status === 'error' && data === null ? (
        <ErrorState message={error?.message ?? 'Unknown error'} onRetry={refresh} />
      ) : data !== null ? (
        <ExploreContent data={data} />
      ) : (
        <EmptyState message="Nothing to explore right now." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  sectionLabel: { color: theme.colors.muted, fontSize: theme.type.label.fontSize },
  row: { flexDirection: 'row', alignItems: 'center', gap: theme.spacing.md },
  rowText: { flex: 1 },
  rowTitle: { color: theme.colors.text, fontSize: theme.type.body.fontSize },
  rowMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize, marginTop: 2 },
});
