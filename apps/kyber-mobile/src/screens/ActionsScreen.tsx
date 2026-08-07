/**
 * Actions — the tier 0-3 governed-action availability digest (M6b).
 *
 * Consumes `client.getActions()` (GET /v1/kyber/mobile/actions) via the typed
 * SDK. The digest is READ-ONLY: it reports what a governed action exists for,
 * which capability it needs, and whether a step-up grant is fresh — it never
 * dispatches anything. Tapping a high-impact item with `requires_step_up` runs
 * the device-bound step-up flow (`attestation.elevate`, challenge → sign →
 * verify) and then refreshes the digest. Tapping any other item opens a
 * read-only detail sheet: this app never dispatches or mutates, and there is
 * no offline mutation.
 */
import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { Button, Card, theme } from '@aether/mobile-ui';
import type { MobileActionItem, MobileActionsDigest } from '@aether/mobile-core';

import { client } from '../client';
import { Screen } from '../navigator';
import { useOpsFetch } from '../useOpsFetch';
import { EmptyState, ErrorState, kyberSeverityColor, LoadingState } from '../components/ScreenStatus';
import { ACTION_TIERS, actionClassLabel, humanizeSnake, toneToColor } from '../actionVocabulary';
import { elevate, type StepUpState } from '../attestation';

function StepUpBanner({
  stepUp,
  stepUpRequired,
}: {
  stepUp: StepUpState;
  stepUpRequired: boolean;
}): React.JSX.Element {
  const tone = stepUpRequired ? 'warning' : 'success';
  return (
    <View style={[styles.stepUpBanner, { borderColor: toneToColor(tone) }]}>
      <Text style={[styles.stepUpBannerTitle, { color: toneToColor(tone) }]}>
        {stepUpRequired ? 'Step-up required' : 'Step-up fresh'}
      </Text>
      <Text style={styles.muted}>
        {stepUpRequired
          ? 'High-impact actions need a fresh device-bound step-up grant before they can be taken.'
          : stepUp.expires_at
            ? `A live step-up grant covers this session until ${stepUp.expires_at}.`
            : 'A live step-up grant covers this session.'}
      </Text>
    </View>
  );
}

function ActionRow({
  item,
  elevating,
  onPress,
}: {
  item: MobileActionItem;
  elevating: boolean;
  onPress: () => void;
}): React.JSX.Element {
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={elevating}
      accessibilityRole="button"
      accessibilityLabel={`${item.title} — ${item.kind}`}
      accessibilityHint={
        item.requires_step_up
          ? 'Step up to unlock this governed action'
          : 'Show read-only action details'
      }
    >
      <Card style={styles.row}>
        <View style={styles.chipRow}>
          <Text style={[styles.chip, item.kind === 'command' ? styles.commandChip : styles.exceptionChip]}>
            {item.kind}
          </Text>
          <Text style={[styles.chip, { color: kyberSeverityColor(item.severity), borderColor: kyberSeverityColor(item.severity) }]}>
            {item.severity}
          </Text>
          <Text style={styles.chip}>{item.status}</Text>
          {item.requires_step_up ? <Text style={[styles.chip, styles.stepUpChip]}>step-up required</Text> : null}
        </View>
        <Text style={styles.rowTitle}>{item.title}</Text>
        <View style={styles.chipRow}>
          <Text style={styles.chip}>action {actionClassLabel(item.action_class)}</Text>
          <Text style={styles.chip}>→ {humanizeSnake(item.available_action)}</Text>
          <Text style={styles.chip}>{item.capability_id}</Text>
        </View>
        <Text style={styles.rowMeta}>
          score {item.priority_score.toFixed(3)} · {item.signal_count} signal{item.signal_count === 1 ? '' : 's'} · last seen {item.last_seen_at ?? '—'}
          {elevating ? ' · elevating…' : ''}
        </Text>
        {item.requires_step_up ? (
          <Text style={styles.stepUpHint}>
            Tap to step up and unlock this governed action on the command plane.
          </Text>
        ) : (
          <Text style={styles.rowMeta}>Read-only here — tap for details.</Text>
        )}
      </Card>
    </TouchableOpacity>
  );
}

function ActionsContent({
  digest,
  elevatingId,
  result,
  onElevate,
  onInspect,
}: {
  digest: MobileActionsDigest;
  elevatingId: string | null;
  result: { itemId: string; ok: boolean; text: string } | null;
  onElevate: (item: MobileActionItem) => void;
  onInspect: (item: MobileActionItem) => void;
}): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <StepUpBanner stepUp={digest.step_up} stepUpRequired={digest.step_up_required} />
      {result !== null ? (
        <View style={result.ok ? styles.resultOk : styles.resultError}>
          <Text style={styles.resultText}>{result.text}</Text>
        </View>
      ) : null}

      {ACTION_TIERS.map((tier) => {
        const items = digest.tiers[tier.key];
        const count = digest.counts[tier.key];
        return (
          <View key={tier.key} style={styles.tier}>
            <Text style={styles.tierHeading}>
              {tier.heading} · {count}
            </Text>
            <Text style={styles.tierHint}>{tier.hint}</Text>
            {items.length === 0 ? (
              <EmptyState message={`Nothing in ${tier.heading.toLowerCase()}.`} />
            ) : (
              items.map((item) => (
                <ActionRow
                  key={`${item.kind}:${item.id}`}
                  item={item}
                  elevating={elevatingId === item.id}
                  onPress={() => (item.requires_step_up ? onElevate(item) : onInspect(item))}
                />
              ))
            )}
          </View>
        );
      })}

      <Text style={styles.readOnlyNote}>
        Read-only in this build — governed actions are dispatched on the desktop
        command plane, never from this app.
      </Text>
    </ScrollView>
  );
}

/** Read-only detail sheet for a non-step-up item. */
function DetailSheet({ item, onClose }: { item: MobileActionItem; onClose: () => void }): React.JSX.Element {
  return (
    <View style={styles.overlay}>
      <TouchableOpacity style={styles.backdrop} onPress={onClose} accessibilityLabel="Close action details" />
      <View style={styles.sheet}>
        <View style={styles.chipRow}>
          <Text style={[styles.chip, item.kind === 'command' ? styles.commandChip : styles.exceptionChip]}>
            {item.kind}
          </Text>
          <Text style={styles.chip}>{item.status}</Text>
          {item.requires_step_up ? <Text style={[styles.chip, styles.stepUpChip]}>step-up required</Text> : null}
        </View>
        <Text style={styles.sheetTitle}>{item.title}</Text>
        <Text style={styles.rowMeta}>
          action {actionClassLabel(item.action_class)} · → {humanizeSnake(item.available_action)}
        </Text>
        <Text style={styles.rowMeta}>capability {item.capability_id}</Text>
        <Text style={styles.rowMeta}>
          severity {item.severity} · score {item.priority_score.toFixed(3)} · {item.signal_count} signal{item.signal_count === 1 ? '' : 's'} · last seen {item.last_seen_at ?? '—'}
        </Text>
        <View style={styles.governedNote}>
          <Text style={styles.governedNoteTitle}>Governed on the desktop command plane</Text>
          <Text style={styles.muted}>
            This app is read-only: it never dispatches or mutates, and there is no offline mutation.
            Approve / execute / acknowledge / resolve happen in the desktop Kyber operator app.
          </Text>
        </View>
        <Button label="Close" onPress={onClose} variant="secondary" />
      </View>
    </View>
  );
}

export default function ActionsScreen(): React.JSX.Element {
  const actions = useOpsFetch(() => client.getActions());
  const [selected, setSelected] = useState<MobileActionItem | null>(null);
  const [elevatingId, setElevatingId] = useState<string | null>(null);
  const [result, setResult] = useState<{ itemId: string; ok: boolean; text: string } | null>(null);

  const runElevate = async (item: MobileActionItem): Promise<void> => {
    if (elevatingId !== null) return; // one elevation at a time
    setElevatingId(item.id);
    setResult(null);
    const elevation = await elevate(item.capability_id);
    setElevatingId(null);
    setResult({
      itemId: item.id,
      ok: elevation.ok,
      text: elevation.ok
        ? elevation.expires_at
          ? `Step-up granted — fresh until ${elevation.expires_at}.`
          : 'Step-up granted.'
        : elevation.error ?? 'Step-up failed — try again.',
    });
    actions.refresh();
  };

  return (
    <Screen title="Actions" subtitle="Governed action availability">
      <View style={styles.wrap}>
        {actions.status === 'loading' && actions.data === null ? (
          <LoadingState />
        ) : actions.status === 'error' && actions.data === null ? (
          <ErrorState message={actions.error?.message ?? 'Unknown error'} onRetry={actions.refresh} />
        ) : actions.data !== null ? (
          <ActionsContent
            digest={actions.data}
            elevatingId={elevatingId}
            result={result}
            onElevate={(item) => void runElevate(item)}
            onInspect={(item) => setSelected(item)}
          />
        ) : (
          <EmptyState message="Nothing to show yet." />
        )}
        {selected !== null ? <DetailSheet item={selected} onClose={() => setSelected(null)} /> : null}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1 },
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  stepUpBanner: {
    padding: theme.spacing.md,
    borderRadius: theme.radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    gap: theme.spacing.xs,
    backgroundColor: theme.colors.surface,
  },
  stepUpBannerTitle: { fontSize: theme.type.label.fontSize, fontWeight: '700' },
  tier: { gap: theme.spacing.sm },
  tierHeading: { color: theme.colors.text, fontSize: theme.type.subtitle.fontSize, fontWeight: '600' },
  tierHint: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  row: { gap: theme.spacing.xs },
  rowTitle: { color: theme.colors.text, fontSize: theme.type.body.fontSize, fontWeight: '600' },
  rowMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
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
  commandChip: { borderColor: theme.colors.accent, color: theme.colors.accentHover },
  exceptionChip: { borderColor: theme.colors.success, color: theme.colors.success },
  stepUpChip: { borderColor: theme.colors.warning, color: theme.colors.warning },
  stepUpHint: { color: theme.colors.warning, fontSize: theme.type.caption.fontSize, fontWeight: '600' },
  resultOk: {
    padding: theme.spacing.sm,
    borderRadius: theme.radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.success,
    backgroundColor: theme.colors.surface,
  },
  resultError: {
    padding: theme.spacing.sm,
    borderRadius: theme.radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.danger,
    backgroundColor: theme.colors.surface,
  },
  resultText: { color: theme.colors.text, fontSize: theme.type.caption.fontSize },
  readOnlyNote: {
    color: theme.colors.muted,
    fontSize: theme.type.caption.fontSize,
    textAlign: 'center',
    marginTop: theme.spacing.lg,
  },
  muted: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  overlay: { ...StyleSheet.absoluteFillObject, justifyContent: 'flex-end' },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0, 0, 0, 0.55)' },
  sheet: {
    backgroundColor: theme.colors.surface,
    borderTopLeftRadius: theme.radii.lg,
    borderTopRightRadius: theme.radii.lg,
    padding: theme.spacing.lg,
    gap: theme.spacing.md,
    maxHeight: '85%',
  },
  sheetTitle: { color: theme.colors.text, fontSize: theme.type.title.fontSize, fontWeight: '600' },
  governedNote: {
    padding: theme.spacing.sm,
    borderRadius: theme.radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.background,
    gap: theme.spacing.xs,
  },
  governedNoteTitle: { color: theme.colors.text, fontSize: theme.type.label.fontSize, fontWeight: '600' },
});
