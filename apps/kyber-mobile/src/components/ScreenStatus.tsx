/**
 * Shared screen-state components (M4a): loading / error / empty placeholders plus
 * severity→color helpers for the Kyber operator screens. Theme-driven via
 * `@aether/mobile-ui`.
 */
import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { Button, theme } from '@aether/mobile-ui';

import type { AgentAlertSeverity, KyberSeverity } from '../kyberOps';

export function LoadingState(): React.JSX.Element {
  return (
    <View style={styles.center}>
      <ActivityIndicator color={theme.colors.accent} />
      <Text style={styles.muted}>Loading…</Text>
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }): React.JSX.Element {
  return (
    <View style={styles.center}>
      <Text style={styles.errorTitle}>Couldn’t load this screen</Text>
      <Text style={styles.muted}>{message}</Text>
      <Button label="Retry" onPress={onRetry} variant="secondary" style={styles.retry} />
    </View>
  );
}

export function EmptyState({ message }: { message: string }): React.JSX.Element {
  return (
    <View style={styles.center}>
      <Text style={styles.muted}>{message}</Text>
    </View>
  );
}

/** Theme color for a Kyber severity (exceptions / incidents). */
export function kyberSeverityColor(severity: KyberSeverity | string): string {
  switch (severity) {
    case 'critical':
      return theme.colors.danger;
    case 'high':
      return theme.colors.warning;
    case 'medium':
      return theme.colors.accent;
    case 'low':
    case 'info':
      return theme.colors.muted;
    default:
      return theme.colors.muted;
  }
}

/** Theme color for an ops-alert severity (P0–P4). */
export function agentAlertColor(severity: AgentAlertSeverity | string): string {
  switch (severity) {
    case 'P0':
    case 'P1':
      return theme.colors.danger;
    case 'P2':
      return theme.colors.warning;
    case 'P3':
      return theme.colors.accent;
    case 'P4':
      return theme.colors.muted;
    default:
      return theme.colors.muted;
  }
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: theme.spacing.sm,
    padding: theme.spacing.xl,
  },
  muted: { color: theme.colors.muted, fontSize: theme.type.body.fontSize, textAlign: 'center' },
  errorTitle: { color: theme.colors.danger, fontSize: theme.type.title.fontSize, fontWeight: '600' },
  retry: { marginTop: theme.spacing.md, minWidth: 120 },
});
