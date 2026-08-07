/**
 * Copilot — read-only briefing / exploration (M3b).
 *
 * Consumes GET /v1/mobile/briefing via the typed projection client and renders the
 * headline + briefing sections. No message-sending UI yet: this milestone is
 * read-only, so the surface is honest about that. If the projection endpoint is
 * absent (backend landing in parallel), the offline-first hook falls back to the
 * last cached briefing and labels it `offline` / `stale`; with no cache it shows
 * an error + retry. A noesis conversation transport will replace this fallback
 * when one ships.
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { projections, type BriefingProjection } from '../projections';
import { useProjection } from '../useProjection';
import { EmptyState, ErrorState, LoadingState, StatusBadge } from '../components/ScreenStatus';

function BriefingContent({ data }: { data: BriefingProjection }): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Card style={styles.headlineCard}>
        <Text style={styles.headline}>{data.headline}</Text>
        <Text style={styles.meta}>
          Briefing · generated {data.generated_at} · read-only
        </Text>
      </Card>

      {data.sections.map((section) => (
        <Card key={section.heading} style={styles.sectionCard}>
          <Text style={styles.sectionHeading}>{section.heading}</Text>
          <Text style={styles.sectionSummary}>{section.summary}</Text>
          <Text style={styles.meta}>
            {section.source}
            {section.updated_at ? ` · updated ${section.updated_at}` : ''}
          </Text>
        </Card>
      ))}

      <Text style={styles.readOnlyNote}>
        This build is read-only — assistant messaging arrives in a later milestone.
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
