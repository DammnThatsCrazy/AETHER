/**
 * Receipts — durable command-receipt visibility (M6b).
 *
 * Consumes `client.getCommandReceipts({ status: 'open', limit: 100 })` and
 * `client.getCommandReceipt(commandId)` (the desktop command plane's durable
 * receipts) via the typed SDK. Every row opens a read-only detail view showing
 * command_type / status / requested_by / action_class / capability / reason /
 * blast-radius summary / approvals / execution and — critically — the
 * verification block. When `verification` is `null` the detail renders
 * "Not verified" prominently: that is the honest answer and is never omitted.
 *
 * READ-ONLY by construction — dispatch and verify happen on the desktop command
 * plane; nothing here names or runs an arbitrary action.
 */
import type { CommandReceiptList } from '@aether/mobile-core';
import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { Card, theme } from '@aether/mobile-ui';

import { client } from '../client';
import { Screen } from '../navigator';
import { useOpsFetch } from '../useOpsFetch';
import { EmptyState, ErrorState, LoadingState } from '../components/ScreenStatus';
import {
  actionClassLabel,
  commandStatusLabel,
  commandStatusTone,
  humanizeSnake,
  toneToColor,
  verificationOutcomeTone,
} from '../actionVocabulary';
import {
  blastRadiusSummary,
  executionOutcomeText,
  mapReceiptDetailToView,
  receiptVerificationText,
  type CommandReceiptDetailView,
  type CommandReceiptListRow,
} from '../commandReceipts';

/** The SDK list shape is the app's list shape (no adapter needed). */
const fetchReceiptsList = (): Promise<CommandReceiptList> =>
  client.getCommandReceipts({ status: 'open', limit: 100 });

/** The SDK detail is nested (`{ command, spec, ... }`); adapt to the flat view. */
const fetchReceiptDetail = (commandId: string): Promise<CommandReceiptDetailView> =>
  client.getCommandReceipt(commandId).then(mapReceiptDetailToView);

function ReceiptRow({
  receipt,
  onPress,
}: {
  receipt: CommandReceiptListRow;
  onPress: () => void;
}): React.JSX.Element {
  const color = toneToColor(commandStatusTone(receipt.status));
  return (
    <TouchableOpacity
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`Receipt ${receipt.command_type}`}
      accessibilityHint="Open the command receipt detail"
    >
      <Card style={styles.row}>
        <View style={styles.chipRow}>
          <Text style={[styles.chip, { color, borderColor: color }]}>{commandStatusLabel(receipt.status)}</Text>
          <Text style={styles.chip}>action {actionClassLabel(receipt.action_class)}</Text>
        </View>
        <Text style={styles.rowTitle}>{receipt.command_type}</Text>
        <Text style={styles.rowMeta}>
          requested by {receipt.requested_by} · created {receipt.created_at}
        </Text>
        <Text style={styles.rowMeta}>updated {receipt.updated_at}</Text>
      </Card>
    </TouchableOpacity>
  );
}

function ReceiptsContent({
  list,
  onOpen,
}: {
  list: CommandReceiptList;
  onOpen: (commandId: string) => void;
}): React.JSX.Element {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.sectionLabel}>
        Open receipts · {list.count} command{list.count === 1 ? '' : 's'} · filter {list.status_filter}
      </Text>
      {list.commands.length === 0 ? (
        <EmptyState message="No open command receipts right now." />
      ) : (
        list.commands.map((receipt) => (
          <ReceiptRow key={receipt.command_id} receipt={receipt} onPress={() => onOpen(receipt.command_id)} />
        ))
      )}
      <Text style={styles.readOnlyNote}>
        Read-only visibility into the desktop command plane — nothing here dispatches or mutates.
      </Text>
    </ScrollView>
  );
}

/** One human-readable approval line from a `CommandRequest.approvals` row. */
function approvalText(approval: Record<string, unknown>): string {
  const parts: string[] = [];
  if (typeof approval['approver_id'] === 'string') parts.push(String(approval['approver_id']));
  if (typeof approval['approved_at'] === 'string') parts.push(String(approval['approved_at']));
  if (Array.isArray(approval['role_template_ids'])) {
    const count = (approval['role_template_ids'] as unknown[]).length;
    parts.push(`${count} template${count === 1 ? '' : 's'}`);
  }
  return parts.length > 0 ? parts.join(' · ') : 'approval recorded';
}

/** One human-readable line from a verification `checks` row. */
function verificationCheckText(check: unknown): string {
  if (check === null || typeof check !== 'object') return String(check);
  const record = check as Record<string, unknown>;
  const parts: string[] = [];
  if (typeof record['check'] === 'string') parts.push(String(record['check']));
  if (typeof record['outcome'] === 'string') parts.push(String(record['outcome']));
  if (typeof record['detail'] === 'string') parts.push(String(record['detail']));
  return parts.length > 0 ? parts.join(' — ') : 'check recorded';
}

/**
 * The verification block. `verification: null` renders "Not verified"
 * prominently — the honest answer, never omitted. A present block renders its
 * outcome, per-check rows, and any named failure.
 */
function VerificationBlock({ detail }: { detail: CommandReceiptDetailView }): React.JSX.Element {
  if (detail.verification === null) {
    return (
      <Card style={styles.unverifiedCard}>
        <Text style={styles.unverifiedTitle}>Not verified</Text>
        <Text style={styles.muted}>{receiptVerificationText(detail)}</Text>
      </Card>
    );
  }
  const outcome =
    typeof detail.verification['outcome'] === 'string'
      ? String(detail.verification['outcome'])
      : 'unknown';
  const failure =
    typeof detail.verification['failure_reason'] === 'string'
      ? String(detail.verification['failure_reason'])
      : null;
  const checks = detail.verification['checks'];
  const color = toneToColor(verificationOutcomeTone(outcome));
  return (
    <Card style={styles.row}>
      <Text style={styles.cardTitle}>Verification</Text>
      <View style={styles.chipRow}>
        <Text style={[styles.chip, { color, borderColor: color }]}>{humanizeSnake(outcome)}</Text>
        <Text
          style={[
            styles.chip,
            {
              color: detail.verified ? theme.colors.success : theme.colors.warning,
              borderColor: detail.verified ? theme.colors.success : theme.colors.warning,
            },
          ]}
        >
          {detail.verified ? 'verified' : 'unverified'}
        </Text>
      </View>
      {Array.isArray(checks) && checks.length > 0 ? (
        checks.map((check, index) => (
          <Text key={index} style={styles.rowMeta}>
            • {verificationCheckText(check)}
          </Text>
        ))
      ) : (
        <Text style={styles.muted}>No check rows reported.</Text>
      )}
      {failure ? <Text style={styles.dangerText}>{failure}</Text> : null}
      {typeof detail.verification['mirror_digest_before'] === 'string' ? (
        <Text style={styles.muted}>
          mirror digest before: {String(detail.verification['mirror_digest_before'])}
        </Text>
      ) : null}
    </Card>
  );
}

function ReceiptDetailView({
  receipt,
  onBack,
}: {
  receipt: CommandReceiptDetailView;
  onBack: () => void;
}): React.JSX.Element {
  const color = toneToColor(commandStatusTone(receipt.status));
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <TouchableOpacity
        onPress={onBack}
        accessibilityRole="button"
        accessibilityLabel="Back to receipts"
        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        style={styles.backButton}
      >
        <Text style={styles.backLabel}>‹ Back</Text>
      </TouchableOpacity>

      <Card style={styles.row}>
        <View style={styles.chipRow}>
          <Text style={[styles.chip, { color, borderColor: color }]}>{commandStatusLabel(receipt.status)}</Text>
          <Text
            style={[
              styles.chip,
              {
                color: receipt.verified ? theme.colors.success : theme.colors.warning,
                borderColor: receipt.verified ? theme.colors.success : theme.colors.warning,
              },
            ]}
          >
            {receipt.verified ? 'verified' : 'not verified'}
          </Text>
          <Text style={styles.chip}>action {actionClassLabel(receipt.action_class)}</Text>
        </View>
        <Text style={styles.rowTitle}>{receipt.command_type}</Text>
        <Text style={styles.rowMeta}>command {receipt.command_id}</Text>
        <Text style={styles.rowMeta}>requested by {receipt.requested_by}</Text>
        {receipt.capability ? <Text style={styles.rowMeta}>capability {receipt.capability}</Text> : null}
        <Text style={styles.rowMeta}>created {receipt.created_at} · updated {receipt.updated_at}</Text>
      </Card>

      <Card style={styles.row}>
        <Text style={styles.cardTitle}>Reason</Text>
        <Text style={styles.rowMeta}>{receipt.reason || '—'}</Text>
      </Card>

      <Card style={styles.row}>
        <Text style={styles.cardTitle}>Blast radius</Text>
        <Text style={styles.rowMeta}>{blastRadiusSummary(receipt.blast_radius)}</Text>
      </Card>

      <Card style={styles.row}>
        <Text style={styles.cardTitle}>Approvals</Text>
        <Text style={styles.rowMeta}>
          required {receipt.required_approvals ?? 0} · mode {receipt.approval_mode ?? 'unknown'} · recorded {receipt.approvals?.length ?? 0}
        </Text>
        {(receipt.approvals ?? []).map((approval, index) => (
          <Text key={index} style={styles.rowMeta}>
            • {approvalText(approval)}
          </Text>
        ))}
      </Card>

      <Card style={styles.row}>
        <Text style={styles.cardTitle}>Execution</Text>
        <Text style={styles.rowMeta}>{executionOutcomeText(receipt.execution)}</Text>
        {receipt.execution?.error ? <Text style={styles.dangerText}>{String(receipt.execution.error)}</Text> : null}
      </Card>

      <VerificationBlock detail={receipt} />

      <Text style={styles.readOnlyNote}>
        Read-only receipt — dispatch and verify happen on the desktop command plane.
      </Text>
    </ScrollView>
  );
}

export default function ReceiptsScreen(): React.JSX.Element {
  const list = useOpsFetch(fetchReceiptsList);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CommandReceiptDetailView | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const openDetail = (commandId: string): void => {
    setPendingId(commandId);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    fetchReceiptDetail(commandId)
      .then((receipt) => {
        setDetailLoading(false);
        setDetail(receipt);
      })
      .catch((err) => {
        setDetailLoading(false);
        setDetailError(err instanceof Error ? err.message : String(err));
      });
  };

  const retryDetail = (): void => {
    if (pendingId !== null) openDetail(pendingId);
  };

  const closeDetail = (): void => {
    setDetail(null);
    setDetailError(null);
    setDetailLoading(false);
    setPendingId(null);
  };

  return (
    <Screen title="Receipts" subtitle="Durable command receipts">
      {detail !== null ? (
        <ReceiptDetailView receipt={detail} onBack={closeDetail} />
      ) : detailLoading ? (
        <LoadingState />
      ) : detailError !== null ? (
        <ErrorState message={detailError} onRetry={retryDetail} />
      ) : (
        <View style={styles.wrap}>
          {list.status === 'loading' && list.data === null ? (
            <LoadingState />
          ) : list.status === 'error' && list.data === null ? (
            <ErrorState message={list.error?.message ?? 'Unknown error'} onRetry={list.refresh} />
          ) : list.data !== null ? (
            <ReceiptsContent list={list.data} onOpen={openDetail} />
          ) : (
            <EmptyState message="Nothing to show yet." />
          )}
        </View>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1 },
  content: { padding: theme.spacing.lg, gap: theme.spacing.md },
  sectionLabel: { color: theme.colors.muted, fontSize: theme.type.label.fontSize },
  row: { gap: theme.spacing.sm },
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
  cardTitle: { color: theme.colors.text, fontSize: theme.type.subtitle.fontSize, fontWeight: '600' },
  dangerText: { color: theme.colors.danger, fontSize: theme.type.caption.fontSize },
  muted: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  unverifiedCard: {
    gap: theme.spacing.sm,
    borderColor: theme.colors.warning,
    backgroundColor: theme.colors.background,
  },
  unverifiedTitle: {
    color: theme.colors.warning,
    fontSize: theme.type.label.fontSize,
    fontWeight: '700',
  },
  backButton: { alignSelf: 'flex-start', paddingRight: theme.spacing.sm },
  backLabel: {
    color: theme.colors.accentHover,
    fontSize: theme.type.label.fontSize,
    fontWeight: '600',
  },
  readOnlyNote: {
    color: theme.colors.muted,
    fontSize: theme.type.caption.fontSize,
    textAlign: 'center',
    marginTop: theme.spacing.lg,
  },
});
