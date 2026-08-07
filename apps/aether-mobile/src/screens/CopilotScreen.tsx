/**
 * Copilot — read-only briefing / exploration (M3b).
 *
 * Consumes GET /v1/mobile/briefing via the typed projection client and renders the
 * recent Noesis conversations with an honest source status
 * (`missing` / `empty` / `available` — an outage never presents as "no
 * conversations"). No message-sending UI yet: this milestone is read-only, so the
 * surface is honest about that. If the projection endpoint is absent, the
 * offline-first hook falls back to the last cached briefing and labels it
 * `offline` / `stale`; with no cache it shows an error + retry.
 */
import React from 'react';
import { ScrollView, StyleSheet, Text } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { projections, type BriefingProjection } from '../projections';
import { useProjection } from '../useProjection';
import { EmptyState, ErrorState, LoadingState, StatusBadge } from '../components/ScreenStatus';

function BriefingContent({ data }: { data: BriefingProjection }): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Card style={styles.headlineCard}>
        <Text style={styles.headline}>Recent conversations</Text>
        <Text style={styles.meta}>
          Noesis source: {data.conversations_source_status} · read-only
        </Text>
      </Card>

      {data.conversations.length === 0 ? (
        <EmptyState message="No conversations yet." />
      ) : (
        data.conversations.map((conversation) => (
          <Card
            key={conversation.conversation_id ?? conversation.last_message ?? conversation.last_intent ?? ''}
            style={styles.sectionCard}
          >
            <Text style={styles.sectionHeading}>{conversation.last_intent ?? 'Conversation'}</Text>
            <Text style={styles.sectionSummary}>{conversation.last_message ?? ''}</Text>
            <Text style={styles.meta}>{conversation.last_ts ? `Updated ${conversation.last_ts}` : ''}</Text>
          </Card>
        ))
      )}

      <Text style={styles.readOnlyNote}>
        {data.saved_views.length} saved {data.saved_views.length === 1 ? 'view' : 'views'} · This build is read-only —
        assistant messaging arrives in a later milestone.
      </Text>
    </ScrollView>
  );
}

export default function CopilotScreen(): React.JSX.Element {
  const { data, status, error, refresh } = useProjection('briefing', () => projections.getBriefing());

  return (
    <Screen title="Copilot" subtitle="Read-only briefing" accessory={<StatusBadge status={status} />}>
      {status === 'loading' && data === null ? (
        <LoadingState />
      ) : status === 'error' && data === null ? (
        <ErrorState message={error?.message ?? 'Unknown error'} onRetry={refresh} />
      ) : data !== null ? (
        <BriefingContent data={data} />
      ) : (
        <EmptyState message="No briefing available right now." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  headlineCard: { marginBottom: theme.spacing.xs },
  headline: { color: theme.colors.text, fontSize: theme.type.title.fontSize, fontWeight: '700' },
  meta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize, marginTop: theme.spacing.sm },
  sectionCard: { gap: theme.spacing.xs },
  sectionHeading: { color: theme.colors.text, fontSize: theme.type.subtitle.fontSize, fontWeight: '600' },
  sectionSummary: { color: theme.colors.text, fontSize: theme.type.body.fontSize },
  readOnlyNote: {
    color: theme.colors.muted,
    fontSize: theme.type.caption.fontSize,
    textAlign: 'center',
    marginTop: theme.spacing.lg,
  },
});
