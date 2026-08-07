/**
 * Operator "Continue on desktop / Resume" feed (M5d).
 *
 * Shows recent operator continuations authored on desktop
 * (`operatorRecentContinuations()`, the flag-gated `/v1/kyber/continuations/recent`
 * feed) with a read-only "Resume" action that re-fetches the continuation
 * (`operatorGetContinuation`) and resolves it to a deep link back into the desktop
 * app, displaying the destination. Read-only except the resolve.
 *
 * 404-safe: when the operator continuation plane is flag-gated off the backend
 * returns 404, the fetcher reports `available: false` and this panel renders a
 * muted "unavailable" note — no dead surface and no crash. While loading (or on a
 * genuine non-404 error) the panel renders nothing.
 */
import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Card, theme } from '@aether/mobile-ui';
import type { ContinuationContext } from '@aether/mobile-core';

import {
  fetchOperatorContinuations,
  resumeOperatorContinuation,
  type OperatorResumeResult,
} from '../operatorContinuations';
import { useOpsFetch } from '../useOpsFetch';

function ContinuationRow({
  continuation,
  busy,
  result,
  onResume,
}: {
  continuation: ContinuationContext;
  busy: boolean;
  result: OperatorResumeResult | null;
  onResume: () => void;
}): React.JSX.Element {
  return (
    <Card style={styles.row}>
      <Text style={styles.rowTitle}>{continuation.summary?.title ?? continuation.id}</Text>
      <Text style={styles.rowMeta}>
        {continuation.surface}
        {continuation.source_client ? ` · ${continuation.source_client}` : ''}
      </Text>
      <Text style={styles.rowMeta}>{continuation.updated_at}</Text>
      <View style={styles.resumeRow}>
        <Button
          label={busy ? 'Opening…' : 'Resume on desktop'}
          onPress={onResume}
          variant="secondary"
          disabled={busy}
          accessibilityHint="Open this operator continuation and resolve its deep link"
          style={styles.resumeButton}
        />
      </View>
      {result !== null && (
        <View style={styles.resultBox}>
          <Text style={styles.resultText}>
            {result.unavailableReason !== null
              ? result.unavailableReason
              : result.resolution !== null && result.resolution.continuation
                ? `Resumes into ${result.resolution.continuation.surface}`
                : result.resolution !== null && result.resolution.requires_step_up
                  ? 'Resume requires a step-up grant.'
                  : result.resolution !== null
                    ? 'Resolved — open the continuation on desktop.'
                    : 'Resume is unavailable right now.'}
          </Text>
        </View>
      )}
    </Card>
  );
}

export function OperatorContinuationsPanel(): React.JSX.Element | null {
  const feed = useOpsFetch(() => fetchOperatorContinuations());
  const [resumeFor, setResumeFor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<OperatorResumeResult | null>(null);

  // Nothing on screen yet (first load) or a genuine non-404 failure — render nothing.
  if (feed.data === null) return null;

  function runResume(continuationId: string): void {
    setResumeFor(continuationId);
    setResult(null);
    setBusy(true);
    void resumeOperatorContinuation(continuationId)
      .then(res => setResult(res))
      .catch(() => setResult(null))
      .finally(() => setBusy(false));
  }

  if (!feed.data.available) {
    return (
      <Card style={styles.card}>
        <Text style={styles.cardTitle}>Continue on desktop</Text>
        <Text style={styles.muted}>
          Operator continuations are unavailable in this build (feature flag off).
        </Text>
      </Card>
    );
  }

  if (feed.data.continuations.length === 0) {
    return (
      <Card style={styles.card}>
        <Text style={styles.cardTitle}>Continue on desktop</Text>
        <Text style={styles.muted}>No desktop operator work to resume right now.</Text>
      </Card>
    );
  }

  return (
    <Card style={styles.card}>
      <Text style={styles.cardTitle}>Continue on desktop</Text>
      <Text style={styles.muted}>
        Operator work you started on desktop. Resume opens it back in the desktop app.
      </Text>
      {feed.data.continuations.map(continuation => (
        <ContinuationRow
          key={continuation.id}
          continuation={continuation}
          busy={busy && resumeFor === continuation.id}
          result={resumeFor === continuation.id ? result : null}
          onResume={() => runResume(continuation.id)}
        />
      ))}
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { gap: theme.spacing.sm },
  cardTitle: { color: theme.colors.text, fontSize: theme.type.subtitle.fontSize, fontWeight: '600' },
  muted: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  row: { gap: theme.spacing.xs },
  rowTitle: { color: theme.colors.text, fontSize: theme.type.body.fontSize, fontWeight: '600' },
  rowMeta: { color: theme.colors.muted, fontSize: theme.type.caption.fontSize },
  resumeRow: { marginTop: theme.spacing.xs },
  resumeButton: { alignSelf: 'flex-start', minWidth: 160 },
  resultBox: {
    marginTop: theme.spacing.xs,
    padding: theme.spacing.sm,
    borderRadius: theme.radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.surface,
  },
  resultText: { color: theme.colors.accentHover, fontSize: theme.type.caption.fontSize },
});
