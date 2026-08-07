/**
 * Account — profile summary, app version, and distribution profile (M3b).
 *
 * Combines GET /v1/mobile/config (version + distribution profile) with
 * GET /v1/mobile/profile (profile summary) via the typed projection client. Both
 * routes are scoped: `config` is keyed by the device installation id and `profile`
 * by the principal user id, each discovered read-only from the device's own
 * installation record. Read-only — no profile editing, no sign-out mutation. When
 * the device has no registered installation yet, the account surfaces degrade to
 * the empty state rather than fabricating an identity.
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { projections, type MobileConfigWire, type ProfileProjection } from '../projections';
import { useProjection, type ProjectionStatus } from '../useProjection';
import { currentInstallationId, currentPrincipalId } from '../continuations';
import { ContinueOnDesktopPanel } from '../components/ContinueOnDesktopPanel';
import { EmptyState, ErrorState, LoadingState, StatusBadge } from '../components/ScreenStatus';

/** Profile-360 counts the Account surface shows — a bounded presentation subset. */
const PROFILE_COUNT_KEYS = ['agents', 'wallets', 'active_delegations_received', 'journey_chains'] as const;

function fieldRow(label: string, value: string | number | null | undefined): React.JSX.Element | null {
  if (value === null || value === undefined || value === '') return null;
  return (
    <View style={styles.fieldRow}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <Text style={styles.fieldValue}>{String(value)}</Text>
    </View>
  );
}

function AccountContent({
  profile,
  config,
}: {
  profile: ProfileProjection;
  config: MobileConfigWire;
}): React.JSX.Element {
  const counts = profile.counts ?? {};
  const behavior = profile.behavior;
  const financials = profile.financials;

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Card style={styles.card}>
        <Text style={styles.cardTitle}>Profile</Text>
        {fieldRow('Name', profile.entity?.display_label)}
        {fieldRow('Type', profile.entity?.type)}
        {fieldRow('Entity', profile.entity_id)}
        {fieldRow('Risk score', behavior?.risk_score)}
        {fieldRow(
          'Anomaly flags',
          behavior?.anomaly_flags && behavior.anomaly_flags.length > 0
            ? behavior.anomaly_flags.length
            : null,
        )}
        {fieldRow('Financial rollup', financials?.rollup_status)}
        {PROFILE_COUNT_KEYS.map((key) => {
          const value = counts[key];
          if (typeof value !== 'number') return null;
          return fieldRow(key.replace(/_/g, ' '), value);
        })}
      </Card>

      <Card style={styles.card}>
        <Text style={styles.cardTitle}>App</Text>
        {fieldRow('Version', config.latest_version)}
        {fieldRow('Minimum version', config.min_version)}
        {fieldRow('Distribution profile', config.distribution_profile)}
        {fieldRow('Environment', config.environment)}
        {config.upgrade_policy !== 'none' ? (
          <Text style={styles.upgradeNote}>Update {config.upgrade_policy === 'required' ? 'required' : 'suggested'}.</Text>
        ) : null}
      </Card>

      <ContinueOnDesktopPanel />

      <Text style={styles.readOnlyNote}>Read-only in this build — account actions arrive in a later milestone.</Text>
    </ScrollView>
  );
}

export default function AccountScreen(): React.JSX.Element {
  const configProj = useProjection<MobileConfigWire | null>('config', async () => {
    const installationId = await currentInstallationId();
    if (!installationId) return null;
    return projections.getConfig(installationId);
  });
  const profileProj = useProjection<ProfileProjection | null>('profile', async () => {
    const principalId = await currentPrincipalId();
    if (!principalId) return null;
    return projections.getProfile(principalId);
  });

  const status: ProjectionStatus =
    configProj.status === 'loading' || profileProj.status === 'loading'
      ? 'loading'
      : configProj.status === 'error' || profileProj.status === 'error'
        ? 'error'
        : configProj.status === profileProj.status
          ? configProj.status
          : 'offline';

  const cfg = configProj.data;
  const profile = profileProj.data;
  const firstError = configProj.error ?? profileProj.error;

  const retry = (): void => {
    configProj.refresh();
    profileProj.refresh();
  };

  return (
    <Screen title="Account" subtitle="Profile and app" accessory={<StatusBadge status={status} />}>
      {status === 'loading' && (cfg === null || profile === null) ? (
        <LoadingState />
      ) : status === 'error' && (cfg === null || profile === null) ? (
        <ErrorState message={firstError?.message ?? 'Unknown error'} onRetry={retry} />
      ) : cfg !== null && profile !== null ? (
        <AccountContent profile={profile} config={cfg} />
      ) : (
        <EmptyState message="Account details aren’t available right now." />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  card: { gap: theme.spacing.sm },
  cardTitle: { color: theme.colors.text, fontSize: theme.type.subtitle.fontSize, fontWeight: '600' },
  fieldRow: { flexDirection: 'row', justifyContent: 'space-between', gap: theme.spacing.md },
  fieldLabel: { color: theme.colors.muted, fontSize: theme.type.body.fontSize, textTransform: 'capitalize' },
  fieldValue: { color: theme.colors.text, fontSize: theme.type.body.fontSize },
  upgradeNote: { color: theme.colors.warning, fontSize: theme.type.caption.fontSize, marginTop: theme.spacing.xs },
  readOnlyNote: {
    color: theme.colors.muted,
    fontSize: theme.type.caption.fontSize,
    textAlign: 'center',
    marginTop: theme.spacing.lg,
  },
});
