/**
 * Account — profile summary, app version, and distribution profile (M3b).
 *
 * Combines GET /v1/mobile/config (version + distribution profile) with
 * GET /v1/mobile/profile (profile summary) via the typed projection client.
 * Read-only — no profile editing, no sign-out mutation.
 */
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { Screen } from '../navigator';
import { projections, type MobileConfigWire, type ProfileProjection } from '../projections';
import { useProjection, type ProjectionStatus } from '../useProjection';
import { ContinueOnDesktopPanel } from '../components/ContinueOnDesktopPanel';
import { EmptyState, ErrorState, LoadingState, StatusBadge } from '../components/ScreenStatus';

function fieldRow(label: string, value: string): React.JSX.Element {
  return (
    <View style={styles.fieldRow}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <Text style={styles.fieldValue}>{value}</Text>
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
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Card style={styles.card}>
        <Text style={styles.cardTitle}>Profile</Text>
        {fieldRow('Name', profile.display_name)}
        {profile.masked_identifier ? fieldRow('Identifier', profile.masked_identifier) : null}
        {fieldRow('Plan', profile.plan)}
        {profile.tier ? fieldRow('Tier', profile.tier) : null}
        {profile.member_since ? fieldRow('Member since', profile.member_since) : null}
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
  const configProj = useProjection('config', () => projections.getConfig());
  const profileProj = useProjection('profile', () => projections.getProfile());

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
  fieldLabel: { color: theme.colors.muted, fontSize: theme.type.body.fontSize },
  fieldValue: { color: theme.colors.text, fontSize: theme.type.body.fontSize },
  upgradeNote: { color: theme.colors.warning, fontSize: theme.type.caption.fontSize, marginTop: theme.spacing.xs },
  readOnlyNote: {
    color: theme.colors.muted,
    fontSize: theme.type.caption.fontSize,
    textAlign: 'center',
    marginTop: theme.spacing.lg,
  },
});
