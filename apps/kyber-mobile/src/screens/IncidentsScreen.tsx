/**
 * Incidents — open incidents + resume cards (M4a).
 *
 * Consumes GET /v1/kyber/ops/incidents and GET /v1/kyber/ops/incidents/resume-cards
 * via the typed client. Shows incidents (severity / status / priority / signal
 * count / next action) plus the deterministic resume cards a returning operator
 * needs to pick work back up. Read-only — no update / resolve actions (M5/M6).
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { kyberOps, type KyberIncident, type KyberResumeCard } from '../kyberOps';
import { useOpsFetch, type OpsFetchStatus } from '../useOpsFetch';
import { EmptyState, ErrorState, kyberSeverityColor, LoadingState } from '../components/ScreenStatus';

function IncidentRow({ incident }: { incident: KyberIncident }): React.JSX.Element {
  return (
    <Card style={styles.row}>
      <View style={[styles.dot, { backgroundColor: kyberSeverityColor(incident.severity) }]} />
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{incident.title}</Text>
        <View style={styles.chipRow}>
          <Text style={[styles.chip, styles.statusChip]}>{incident.status}</Text>
          <Text style={styles.chip}>{incident.severity}</Text>
        </View>
        <Text style={styles.rowMeta}>
          {incident.signal_count} signal{incident.signal_count === 1 ? '' : 's'} · score{' '}
          {incident.priority_score.toFixed(3)} · {incident.affected_services.length} service
          {incident.affected_services.length === 1 ? '' : 's'}
        </Text>
        {incident.next_action ? <Text style={styles.nextAction}>Next: {incident.next_action}</Text> : null}
        <Text style={styles.rowMeta}>opened {incident.opened_at} · updated {incident.updated_at}</Text>
      </View>
    </Card>
  );
}

function ResumeCardRow({ card }: { card: KyberResumeCard }): React.JSX.Element {
  return (
    <Card style={styles.row}>
      <View style={[styles.dot, { backgroundColor: kyberSeverityColor(card.severity) }]} />
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{card.title}</Text>
        <View style={styles.chipRow}>
          <Text style={[styles.chip, styles.statusChip]}>{card.status}</Text>
          <Text style={styles.chip}>{card.severity}</Text>
        </View>
        {card.last_action ? <Text style={styles.rowMeta}>Last: {card.last_action}</Text> : null}
        {card.next_action ? <Text style={styles.nextAction}>Next: {card.next_action}</Text> : null}
        {card.blocked_by ? <Text style={styles.blocked}>Blocked by: {card.blocked_by}</Text> : null}
        {card.pending_verification.length > 0 ? (
          <Text style={styles.rowMeta}>
            {card.pending_verification.length} pending verification
            {card.pending_verification.length === 1 ? '' : 's'}
          </Text>
        ) : null}
      </View>
    </Card>
  );
}

function IncidentsContent({
  incidents,
  cards,
}: {
  incidents: KyberIncident[];
  cards: KyberResumeCard[];
}): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.sectionLabel}>
        Open incidents · {incidents.length}
      </Text>
      {incidents.length === 0 ? (
        <EmptyState message="No open incidents right now." />
      ) : (
        incidents.map((incident) => <IncidentRow key={incident.incident_id} incident={incident} />)
      )}

      <Text style={[styles.sectionLabel, styles.resumeLabel]}>Resume cards</Text>
      {cards.length === 0 ? (
        <EmptyState message="Nothing to resume." />
      ) : (
        cards.map((card) => <ResumeCardRow key={card.incident_id} card={card} />)
      )}
    </ScrollView>
  );
}

export default function IncidentsScreen(): React.JSX.Element {
  const incidents = useOpsFetch(() => kyberOps.getIncidents());
  const cards = useOpsFetch(() => kyberOps.getResumeCards());

  const status: OpsFetchStatus =
    incidents.status === 'loading' || cards.status === 'loading'
      ? 'loading'
      : incidents.status === 'error' || cards.status === 'error'
        ? 'error'
        : 'fresh';

  const firstError = incidents.error ?? cards.error;

  const retry = (): void => {
    incidents.refresh();
    cards.refresh();
  };

  return (
    <Screen title="Incidents" subtitle="Correlated failures">
      {status === 'loading' && (incidents.data === null || cards.data === null) ? (
        <LoadingState />
      ) : status === 'error' && (incidents.data === null || cards.data === null) ? (
        <ErrorState message={firstError?.message ?? 'Unknown error'} onRetry={retry} />
      ) : incidents.data !== null && cards.data !== null ? (
        <IncidentsContent incidents={incidents.data.incidents} cards={cards.data.cards} />
      ) : (
        <EmptyState message="Nothing to show yet." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  sectionLabel: { color: theme.colors.muted, fontSize: theme.type.label.fontSize },
  resumeLabel: { marginTop: theme.spacing.lg },
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
  statusChip: { borderColor: theme.colors.warning, color: theme.colors.warning },
  rowMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  nextAction: { color: theme.colors.text, fontSize: theme.type.caption.fontSize },
  blocked: { color: theme.colors.danger, fontSize: theme.type.caption.fontSize },
});
