/**
 * Fraud 360 — Kyber operator fraud-synthesis consolidation page.
 *
 * Read-only projection surface over the flag-gated `/v1/fraud360` plane
 * (AETHER_FRAUD360_ENABLED, default OFF). The operator picks a subject
 * (entity | relationship | agent) and the page renders the projection's
 * sections (summary/state/evidence/findings/health) with honest state badges;
 * material hypotheses surface as candidate cards. A plane that is not enabled /
 * not registered / kind unserved renders a graceful empty state — never an
 * error crash. Fraud is presented as a hypothesis, never stronger than the
 * states the backend reports.
 */

import { useState } from 'react';
import { EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import {
  FRAUD360_SUBJECT_KINDS,
  useFraud360Health,
  useFraud360Sections,
  type Fraud360SubjectKind,
} from '@kyber/features/fraud360';
import {
  ProjectionPlaneHealth,
  ProjectionResultView,
  ProjectionSubjectPicker,
} from '@kyber/features/projection-plane';

export function Fraud360Page() {
  const [kind, setKind] = useState<Fraud360SubjectKind>('entity');
  const [subjectId, setSubjectId] = useState('');
  const [target, setTarget] = useState<{ kind: Fraud360SubjectKind; id: string } | null>(null);

  const activeKind = target?.kind ?? '';
  const activeId = target?.id ?? '';
  const projection = useFraud360Sections(activeKind, activeId);
  const health = useFraud360Health();

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
      title="Fraud 360"
      subtitle="Fraud-synthesis consolidation — evidence-grounded fraud hypotheses over canonical truth"
      actions={
        <ProjectionPlaneHealth
          name="Fraud 360"
          health={health.data}
          isLoading={health.isLoading}
        />
      }
    >
      <ProjectionSubjectPicker
        planeName="Fraud 360"
        kinds={FRAUD360_SUBJECT_KINDS}
        kind={kind}
        onKindChange={k => setKind(k as Fraud360SubjectKind)}
        subjectId={subjectId}
        onSubjectIdChange={setSubjectId}
        onRun={runProjection}
        onClear={clearProjection}
      />

      {health.error && (
        <p className="text-xs text-text-muted">Fraud 360 plane probe failed: {health.error}</p>
      )}

      {!target ? (
        <EmptyState
          title="Pick a subject"
          description="Choose a subject kind and id to run the Fraud 360 projection over that subject."
        />
      ) : projection.isLoading ? (
        <LoadingState lines={6} />
      ) : projection.error ? (
        <ErrorState title="Fraud 360 projection failed" message={projection.error} />
      ) : projection.result === null ? (
        <EmptyState
          title="Fraud 360 plane not enabled / no projection"
          description="Fraud 360 could not be served for this subject. The plane may not be enabled on this backend (AETHER_FRAUD360_ENABLED), its provider may not be registered, or the subject kind may not be served."
        />
      ) : (
        <ProjectionResultView result={projection.result} />
      )}
    </PageWrapper>
  );
}
