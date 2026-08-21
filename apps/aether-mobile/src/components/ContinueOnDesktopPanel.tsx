/**
 * Continue on desktop — cross-device continuation surface (M5d).
 *
 * Shows recent continuations authored on desktop (SDK `recentContinuations()`, the
 * tenant `/v1/continuations/recent` feed) with a read-only "Resume" action that
 * re-fetches the continuation and resolves it to a deep link back into the desktop
 * app, displaying the destination. Read-only except the resolve.
 *
 * 404-safe: when the continuation plane is flag-gated off the backend returns 404,
 * `recentContinuations()` rejects, no data exists and this panel renders nothing —
 * no dead surface and no further requests.
 */
import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Card, theme } from '@aether/mobile-ui';
import type { ContinuationContext } from '@aether/mobile-core';

import { client } from '../client';
import { resumeContinuation, type ContinueOnDesktopResult } from '../continuations';
import { useProjection } from '../useProjection';

function ContinuationRow({
  continuation,
  busy,
  result,
  onResume,
}: {
  continuation: ContinuationContext;
  busy: boolean;
  result: ContinueOnDesktopResult | null;
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
          accessibilityHint="Open this continuation and resolve its deep link"
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

export function ContinueOnDesktopPanel(): React.JSX.Element | null {
  // 404-safe: any error (including the flag-gated plane's 404) leaves data null and
  // the panel renders nothing.
  const { data } = useProjection('continuations-recent', () => client.recentContinuations());
  const [resumeFor, setResumeFor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ContinueOnDesktopResult | null>(null);

  if (data === null) return null;

  function runResume(continuationId: string): void {
    setResumeFor(continuationId);
    setResult(null);
    setBusy(true);
    void resumeContinuation(continuationId)
      .then(res => setResult(res))
      .catch(() => setResult(null))
      .finally(() => setBusy(false));
  }

  if (data.length === 0) {
    return (
      <Card style={styles.card}>
        <Text style={styles.cardTitle}>Continue on desktop</Text>
        <Text style={styles.muted}>No desktop work to resume right now.</Text>
      </Card>
    );
  }

  return (
    <Card style={styles.card}>
      <Text style={styles.cardTitle}>Continue on desktop</Text>
      <Text style={styles.muted}>
        Work you started on desktop. Resume opens it back in the desktop app.
      </Text>
      {data.map(continuation => (
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
