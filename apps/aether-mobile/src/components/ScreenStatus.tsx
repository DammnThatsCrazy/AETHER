/**
 * Shared screen-state components (M3b): loading / error / empty placeholders plus
 * the `fresh` / `offline` / `stale` header badge. Theme-driven via `@aether/mobile-ui`.
 */
import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { Button, theme } from '@aether/mobile-ui';

import type { AlertBand, AlertSeverity } from '../projections';
import { bandForSeverity } from '../projections';
import type { ProjectionStatus } from '../useProjection';

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

/**
 * Header accessory that names the projection's data source. Shows nothing for
 * `fresh` / `loading`; an amber chip for `stale` / `offline` reads.
 */
export function StatusBadge({ status }: { status: ProjectionStatus }): React.JSX.Element | null {
  if (status !== 'offline' && status !== 'stale') return null;
  return (
    <View style={styles.badge}>
      <Text style={styles.badgeText}>{status}</Text>
    </View>
  );
}

/** Theme color for a severity band (Today counts + notification dots). */
export function bandColor(band: AlertBand): string {
  switch (band) {
    case 'critical':
      return theme.colors.danger;
    case 'high':
      return theme.colors.warning;
    case 'medium':
      return theme.colors.accent;
    case 'info':
      return theme.colors.muted;
  }
}

/** Theme color for a raw alert severity (via banding). */
export function severityColor(severity: AlertSeverity): string {
  return bandColor(bandForSeverity(severity));
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
  badge: {
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: theme.spacing.xs,
    borderRadius: theme.radii.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.warning,
  },
  badgeText: {
    color: theme.colors.warning,
    fontSize: theme.type.caption.fontSize,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
});
