/**
 * Risk 360 — Kyber operator risk-assessment workbench.
 *
 * Read-only projection surface over the flag-gated `/v1/risk360` plane
 * (AETHER_RISK360_ENABLED, default OFF). The operator picks a subject
 * (entity | relationship | cluster | population) and the page renders the
 * projection's sections (summary/state/evidence/findings/health) with honest
 * state badges, plus any claims and dependency state. A plane that is not
 * enabled / not registered / kind unserved renders a graceful empty state —
 * never an error crash.
 */

import { useState } from 'react';
import { EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import {
  RISK360_SUBJECT_KINDS,
  useRisk360Health,
  useRisk360Sections,
  type Risk360SubjectKind,
} from '@kyber/features/risk360';
import {
  ProjectionPlaneHealth,
  ProjectionResultView,
  ProjectionSubjectPicker,
} from '@kyber/features/projection-plane';

export function Risk360Page() {
  const [kind, setKind] = useState<Risk360SubjectKind>('entity');
  const [subjectId, setSubjectId] = useState('');
  const [target, setTarget] = useState<{ kind: Risk360SubjectKind; id: string } | null>(null);

  const activeKind = target?.kind ?? '';
  const activeId = target?.id ?? '';
  const projection = useRisk360Sections(activeKind, activeId);
  const health = useRisk360Health();

  function runProjection() {
    if (!subjectId.trim()) return;
    setTarget({ kind, id: subjectId.trim() });
  }

  function clearProjection() {
    setTarget(null);
    setSubjectId('');
  }

  return (
    <PageWrapper
      title="Risk 360"
      subtitle="Subject risk-assessment workbench — read-only projection over canonical risk truth"
      actions={
        <ProjectionPlaneHealth
          name="Risk 360"
          health={health.data}
          isLoading={health.isLoading}
        />
      }
    >
      <ProjectionSubjectPicker
        planeName="Risk 360"
        kinds={RISK360_SUBJECT_KINDS}
        kind={kind}
        onKindChange={k => setKind(k as Risk360SubjectKind)}
        subjectId={subjectId}
        onSubjectIdChange={setSubjectId}
        onRun={runProjection}
        onClear={clearProjection}
      />

      {health.error && (
        <p className="text-xs text-text-muted">Risk 360 plane probe failed: {health.error}</p>
      )}

      {!target ? (
        <EmptyState
          title="Pick a subject"
          description="Choose a subject kind and id to run the Risk 360 projection over that subject."
        />
      ) : projection.isLoading ? (
        <LoadingState lines={6} />
      ) : projection.error ? (
        <ErrorState title="Risk 360 projection failed" message={projection.error} />
      ) : projection.result === null ? (
        <EmptyState
          title="Risk 360 plane not enabled / no projection"
          description="Risk 360 could not be served for this subject. The plane may not be enabled on this backend (AETHER_RISK360_ENABLED), its provider may not be registered, or the subject kind may not be served."
        />
      ) : (
        <ProjectionResultView result={projection.result} />
      )}
    </PageWrapper>
  );
}
