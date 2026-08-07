/**
 * Pulse — the operator health dashboard (M4a).
 *
 * Consumes GET /v1/agent/health, GET /v1/agent/ops/alerts and
 * GET /v1/agent/controllers/status via the typed client. Shows kill-switch
 * posture, objective/run/review counts, queue depths, per-controller health and
 * the redacted compressed-alert stream. Read-only.
 *
 * The ops-alerts endpoint can be individually disabled (one-person-ops flag), so
 * alerts render as a best-effort section rather than gating the whole screen.
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import {
  kyberOps,
  type AgentControllerStatus,
  type AgentHealth,
  type AgentOpsAlert,
  type AgentOpsAlerts,
  type AgentControllersStatus,
} from '../kyberOps';
import { useOpsFetch } from '../useOpsFetch';
import {
  agentAlertColor,
  EmptyState,
  ErrorState,
  LoadingState,
} from '../components/ScreenStatus';

function controllerColor(status: string): string {
  switch (status) {
    case 'healthy':
      return theme.colors.success;
    case 'degraded':
      return theme.colors.warning;
    case 'stale':
    case 'unknown':
      return theme.colors.muted;
    default:
      return theme.colors.muted;
  }
}

function Stat({ label, value }: { label: string; value: number }): React.JSX.Element {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function ControllersBlock({ controllers }: { controllers: AgentControllerStatus[] }): React.JSX.Element {
  return (
    <Card style={styles.card}>
      <Text style={styles.cardTitle}>Controllers</Text>
      <View style={styles.controllerRows}>
        {controllers.length === 0 ? (
          <Text style={styles.mutedText}>No controllers reporting.</Text>
        ) : (
          controllers.map((controller) => (
            <View key={controller.controller} style={styles.controllerRow}>
              <View style={[styles.dot, { backgroundColor: controllerColor(controller.status) }]} />
              <Text style={styles.controllerName}>{controller.controller}</Text>
              <Text style={[styles.controllerStatus, { color: controllerColor(controller.status) }]}>
                {controller.status}
              </Text>
              <Text style={styles.mutedText}>
                {controller.queue_depth} queued · {controller.worker_count} worker
                {controller.worker_count === 1 ? '' : 's'}
              </Text>
            </View>
          ))
        )}
      </View>
    </Card>
  );
}

function AlertsBlock({ alerts }: { alerts: AgentOpsAlert[] }): React.JSX.Element {
  return (
    <Card style={styles.card}>
      <Text style={styles.cardTitle}>Alerts</Text>
      {alerts.length === 0 ? (
        <Text style={styles.mutedText}>No open alerts right now.</Text>
      ) : (
        alerts.map((alert) => (
          <View key={alert.alert_id} style={styles.alertRow}>
            <View style={[styles.dot, { backgroundColor: agentAlertColor(alert.severity) }]} />
            <View style={styles.alertText}>
              <Text style={styles.alertKind}>
                [{alert.severity}] {alert.kind}
              </Text>
              <Text style={styles.alertMessage}>{alert.message}</Text>
              <Text style={styles.mutedText}>
                {alert.count} occurrence{alert.count === 1 ? '' : 's'} · last seen{' '}
                {alert.last_seen_at}
              </Text>
            </View>
          </View>
        ))
      )}
    </Card>
  );
}

function PulseContent({
  health,
  alerts,
  controllers,
}: {
  health: AgentHealth;
  alerts: AgentOpsAlerts | null;
  controllers: AgentControllersStatus | null;
}): React.JSX.Element {
  const controllerRows = controllers !== null ? controllers.controllers : health.controllers;
  const alertsRows = alerts !== null ? alerts.alerts : [];

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Card style={styles.card}>
        <Text style={styles.cardTitle}>Kill switch</Text>
        <Text style={health.kill_switch.enabled ? styles.killSwitchEngaged : styles.killSwitchReleased}>
          {health.kill_switch.enabled ? 'ENGAGED — dispatch blocked' : 'Released'}
        </Text>
        {health.kill_switch.reason ? (
          <Text style={styles.mutedText}>Reason: {health.kill_switch.reason}</Text>
        ) : null}
      </Card>

      <Card style={styles.card}>
        <Text style={styles.cardTitle}>Objectives</Text>
        <View style={styles.statRow}>
          <Stat label="Active" value={health.objectives.active} />
          <Stat label="Blocked" value={health.objectives.blocked} />
          <Stat label="Failed" value={health.objectives.failed} />
          <Stat label="Total" value={health.objectives.total} />
        </View>
      </Card>

      <Card style={styles.card}>
        <Text style={styles.cardTitle}>Runs</Text>
        <View style={styles.statRow}>
          <Stat label="Queued" value={health.runs.queued} />
          <Stat label="Running" value={health.runs.running} />
          <Stat label="Completed" value={health.runs.completed} />
          <Stat label="Failed" value={health.runs.failed} />
          <Stat label="Stuck" value={health.runs.stuck} />
        </View>
        <Text style={styles.mutedText}>
          Review queue: {health.review.awaiting_review} awaiting approval
        </Text>
      </Card>

      <ControllersBlock controllers={controllerRows} />
      <AlertsBlock alerts={alertsRows} />
    </ScrollView>
  );
}

export default function PulseScreen(): React.JSX.Element {
  const health = useOpsFetch(() => kyberOps.getHealth());
  const alerts = useOpsFetch(() => kyberOps.getOpsAlerts());
  const controllers = useOpsFetch(() => kyberOps.getControllersStatus());

  const retry = (): void => {
    health.refresh();
    alerts.refresh();
    controllers.refresh();
  };

  return (
    <Screen title="Pulse" subtitle="Agent health">
      {health.status === 'loading' && health.data === null ? (
        <LoadingState />
      ) : health.status === 'error' && health.data === null ? (
        <ErrorState message={health.error?.message ?? 'Unknown error'} onRetry={retry} />
      ) : health.data !== null ? (
        <PulseContent health={health.data} alerts={alerts.data} controllers={controllers.data} />
      ) : (
        <EmptyState message="Nothing to show yet." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  card: { gap: theme.spacing.sm },
  cardTitle: { color: theme.colors.text, fontSize: theme.type.subtitle.fontSize, fontWeight: '600' },
  mutedText: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  killSwitchEngaged: { color: theme.colors.danger, fontSize: theme.type.body.fontSize, fontWeight: '700' },
  killSwitchReleased: { color: theme.colors.success, fontSize: theme.type.body.fontSize, fontWeight: '700' },
  statRow: { flexDirection: 'row', justifyContent: 'space-between', flexWrap: 'wrap', gap: theme.spacing.md },
  stat: { alignItems: 'center', gap: theme.spacing.xs },
  statValue: { fontSize: 22, fontWeight: '700', color: theme.colors.text },
  statLabel: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  controllerRows: { gap: theme.spacing.sm },
  controllerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.sm,
  },
  controllerName: { flex: 1, color: theme.colors.text, fontSize: theme.type.body.fontSize },
  controllerStatus: { fontSize: theme.type.caption.fontSize, fontWeight: '600', textTransform: 'uppercase' },
  dot: { width: 10, height: 10, borderRadius: theme.radii.pill },
  alertRow: { flexDirection: 'row', alignItems: 'flex-start', gap: theme.spacing.md },
  alertText: { flex: 1, gap: 2 },
  alertKind: { color: theme.colors.text, fontSize: theme.type.body.fontSize, fontWeight: '600' },
  alertMessage: { color: theme.colors.text, fontSize: theme.type.caption.fontSize },
});
