/**
 * KYBER — Exceptions & incidents (operator).
 *
 * The prioritised queue a single operator reads instead of watching dashboards, the
 * incidents those exceptions roll up into, and the resume cards that let a half-finished
 * investigation be picked back up.
 *
 * Three rules run through everything below, and each exists because of a specific way
 * an operator gets misled:
 *
 *  1. **A ranking must be interrogable.** `priority_inputs` is stored beside
 *     `priority_score` precisely so the arithmetic can be replayed after the fact. A
 *     ranking nobody can question is a ranking they stop trusting — so every row can
 *     show its terms, their weights and their contributions, and an exception whose
 *     inputs the backend did not record says so rather than implying the order is
 *     self-evident.
 *
 *  2. **A suppression must announce itself.** Suppression is the one transition that
 *     removes something from view without fixing it. A silently suppressed exception is
 *     indistinguishable from one that never fired, so a suppressed row renders its
 *     reason, and a suppression with no recorded reason is flagged rather than hidden.
 *
 *  3. **A guess must look like a guess.** `correlation_basis` records why a signal was
 *     attached to an incident. Attributing it on time proximity or a similar error
 *     string is inference; attributing it on the same release is evidence. They render
 *     differently, because an operator who treats the first as the second chases the
 *     wrong root cause.
 *
 * Counts the backend could not compute arrive as `null` and render as "Unknown" with
 * whatever reason travelled with them. There is no `?? 0` in this file, and — the part
 * that is easy to miss — nothing standing in for one: no `?? []` whose length is then
 * counted or announced, no invented literal filling in for a field the backend did not
 * send, and no `null` sorted as if it were zero. A `?? []` survives here only where the
 * empty case renders no claim at all (an optional line that is simply not drawn), never
 * where it would become a number, a count in a heading, or a statement that there is
 * nothing there. An absent list is "we could not read it"; an empty list is "we read it
 * and it was empty"; and only the second one may be shown as none.
 */

import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Select,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useMutation,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { PermissionGate } from '@kyber/features/permissions';
import { cn } from '@kyber/lib/utils';
import {
  BASIS_LABELS,
  BUCKET_LABELS,
  BUCKET_ORDER,
  acknowledgeException,
  basisKind,
  resolveException,
  suppressException,
  useExceptionQueue,
  useIncident,
  useIncidents,
  useResumeCards,
} from '@kyber/features/kyber-ops';
import type {
  BasisKind,
  ExceptionQueue,
  Incident,
  IncidentDetail,
  IncidentSignal,
  OperationalException,
  PriorityInputs,
  ResumeCard,
} from '@kyber/features/kyber-ops';

const PAGE_SUBTITLE =
  'One prioritised queue instead of many dashboards. Every rank can be interrogated, every suppression states its reason, and a correlation made on inference is labelled as inference.';

/** Capabilities the ops router enforces. Hiding a control it would refuse is the point. */
const INCIDENT_MANAGE = 'kyber.incident.manage';
const INCIDENT_CLOSE = 'kyber.incident.close';

export const UNKNOWN_LABEL = 'Unknown';

// ── Small honest primitives ──────────────────────────────────────────────────

/** A count the backend may not have computed. `null` is Unknown, never zero. */
function CountText({ value }: { readonly value: number | null | undefined }) {
  if (value === null || value === undefined) {
    return <span className="text-warning font-mono">{UNKNOWN_LABEL}</span>;
  }
  return <span className="font-mono text-text-primary">{value}</span>;
}

function ScoreText({ value }: { readonly value: number | null | undefined }) {
  if (value === null || value === undefined) {
    return <span className="text-warning font-mono">{UNKNOWN_LABEL}</span>;
  }
  return <span className="font-mono text-text-primary">{value.toFixed(2)}</span>;
}

function severityVariant(severity: string): 'danger' | 'warning' | 'info' | 'default' {
  const normalized = severity.toLowerCase();
  if (normalized === 'critical') return 'danger';
  if (normalized === 'high') return 'danger';
  if (normalized === 'medium') return 'warning';
  if (normalized === 'low') return 'info';
  return 'default';
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, ' ');
}

function readString(record: Record<string, unknown> | null | undefined, key: string): string | null {
  if (!record) return null;
  const value = record[key];
  return typeof value === 'string' && value !== '' ? value : null;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (Array.isArray(value)) return value.length === 0 ? '—' : value.join(', ');
  return String(value);
}

// ── Why this ranks where it does ─────────────────────────────────────────────

/**
 * The bucket floors in `severity.bucket_for` can raise an exception above the bucket
 * its score alone would put it in. Saying so is part of explaining the rank: without
 * it, a low-scoring row sitting in `critical_now` looks like a bug.
 */
function bucketFloorReasons(exception: OperationalException): readonly string[] {
  const reasons: string[] = [];
  if (exception.security_exposure === true && exception.data_integrity_exposure === true) {
    reasons.push(
      'Floor: security exposure together with data-integrity exposure is the cross-tenant leak signature, which is always Critical now.',
    );
  }
  if (exception.severity.toLowerCase() === 'critical') {
    reasons.push('Floor: a critical severity is always Critical now.');
  }
  if (exception.security_exposure === true) {
    reasons.push('Floor: a security exposure is at least Needs action.');
  }
  if (exception.data_integrity_exposure === true) {
    reasons.push('Floor: a data-integrity exposure is at least Needs action.');
  }
  if (exception.reversible === false) {
    reasons.push('Floor: an irreversible exception is at least Needs action.');
  }
  const breach = exception.time_to_breach_seconds;
  if (breach !== null && breach !== undefined && breach <= 3600) {
    reasons.push('Floor: a deadline inside an hour is at least Needs action.');
  }
  return reasons;
}

/**
 * Order the terms by contribution, descending.
 *
 * A term whose contribution the backend did not record is not a term that contributed
 * zero. Sorting it as `?? 0` buries it at the bottom of the table beside the terms that
 * genuinely contributed nothing, which is an unrecorded value being ranked as a measured
 * one. Unrecorded terms are kept as their own trailing group — still visible, still
 * rendered as Unknown in the contribution column — and ordered by name so the table is
 * stable rather than arbitrary.
 */
function compareByContribution(
  a: { readonly name: string; readonly contribution: number | null | undefined },
  b: { readonly name: string; readonly contribution: number | null | undefined },
): number {
  const aKnown = a.contribution !== null && a.contribution !== undefined;
  const bKnown = b.contribution !== null && b.contribution !== undefined;
  if (aKnown && bKnown) return (b.contribution as number) - (a.contribution as number);
  if (aKnown) return -1;
  if (bKnown) return 1;
  return a.name.localeCompare(b.name);
}

function PriorityExplanation({
  exception,
}: {
  readonly exception: OperationalException;
}) {
  const inputs: PriorityInputs | null | undefined = exception.priority_inputs;
  const terms = inputs?.terms ?? null;
  const termNames = terms === null ? [] : Object.keys(terms);
  const floors = bucketFloorReasons(exception);
  const unrecordedContributions = termNames.filter(name => {
    const contribution = terms?.[name]?.contribution;
    return contribution === null || contribution === undefined;
  });

  const ordered = termNames
    .map(name => ({ name, term: terms?.[name], contribution: terms?.[name]?.contribution }))
    .sort(compareByContribution);

  return (
    <div className="mt-2 rounded border border-border-default bg-surface-raised p-3 space-y-2">
      <div className="text-[11px] font-mono text-text-secondary">
        Why this ranks here
      </div>

      {termNames.length === 0 ? (
        <div role="status" className="text-xs text-warning">
          No priority inputs were recorded for this exception, so this rank cannot be
          explained. Treat the ordering as unexplained, not as agreed.
        </div>
      ) : (
        <>
          {/* The scale is printed only when the backend recorded one. `?? '0-100'`
              invented a bound no field supports, which turns an unlabelled number into
              a percentage in the reader's head. */}
          <div className="text-[11px] text-text-muted font-mono">
            Score <ScoreText value={inputs?.score ?? exception.priority_score} />{' '}
            {inputs?.scale
              ? `on the ${inputs.scale} scale`
              : `on a scale the backend did not record — ${UNKNOWN_LABEL}, so this number has no bound to read it against`}
            . Raw subtotal <CountText value={inputs?.raw_subtotal ?? null} /> of{' '}
            <CountText value={inputs?.max_raw_score ?? null} />, scaled by a confidence
            factor of <CountText value={inputs?.confidence_factor ?? null} />.
          </div>

          {(inputs?.dominant_terms ?? []).length > 0 && (
            <div className="text-[11px] text-text-secondary font-mono">
              Dominant terms:{' '}
              {(inputs?.dominant_terms ?? []).map(term => titleCase(term)).join(', ')}
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-[11px] font-mono border-collapse">
              <thead>
                <tr className="border-b border-border-default text-text-muted">
                  <th className="py-1 px-2 text-left">Term</th>
                  <th className="py-1 px-2 text-left">Observed</th>
                  <th className="py-1 px-2 text-right">Normalised</th>
                  <th className="py-1 px-2 text-right">Weight</th>
                  <th className="py-1 px-2 text-right">Contribution</th>
                </tr>
              </thead>
              <tbody>
                {ordered.map(({ name, term }) => (
                  <tr key={name} className="border-b border-border-subtle">
                    <td className="py-1 px-2 text-text-primary">{titleCase(name)}</td>
                    <td className="py-1 px-2 text-text-secondary">
                      {renderValue(term?.value)}
                    </td>
                    <td className="py-1 px-2 text-right">
                      <CountText value={term?.normalized ?? null} />
                    </td>
                    <td className="py-1 px-2 text-right">
                      <CountText value={term?.weight ?? null} />
                    </td>
                    <td className="py-1 px-2 text-right">
                      <CountText value={term?.contribution ?? null} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {unrecordedContributions.length > 0 && (
            <div role="status" className="text-[11px] text-warning">
              The backend recorded no contribution for{' '}
              {unrecordedContributions.map(name => titleCase(name)).join(', ')}. Those
              terms are listed last because their contribution is Unknown, not because it
              was measured as nothing — their place in this ordering is unknown too.
            </div>
          )}
        </>
      )}

      {floors.length > 0 && (
        <ul className="text-[11px] text-text-secondary space-y-0.5">
          {floors.map(reason => (
            <li key={reason}>· {reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Suppression ──────────────────────────────────────────────────────────────

/**
 * A suppressed exception is not a resolved one. It says so, and it carries the reason
 * that was recorded when it was silenced.
 */
function SuppressionNotice({ exception }: { readonly exception: OperationalException }) {
  const reason = readString(exception.metadata, 'suppression_reason');
  const by = readString(exception.metadata, 'suppressed_by');
  const at = readString(exception.metadata, 'suppressed_at');

  return (
    <div
      role="status"
      className="mt-2 rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
    >
      <div className="font-semibold font-mono">
        Suppressed — silenced, not fixed
      </div>
      {reason === null ? (
        <div className="mt-1 text-text-secondary">
          No suppression reason was recorded. A suppression without a reason is
          indistinguishable from an exception that never fired.
        </div>
      ) : (
        <div className="mt-1 text-text-secondary">
          Suppression reason: {reason}
        </div>
      )}
      <div className="mt-1 text-[10px] text-text-muted font-mono">
        by {by ?? UNKNOWN_LABEL} · {at ?? UNKNOWN_LABEL}
      </div>
    </div>
  );
}

// ── One exception row ────────────────────────────────────────────────────────

interface ExceptionRowProps {
  readonly exception: OperationalException;
  readonly onChanged: () => void;
}

function ExceptionRow({ exception, onChanged }: ExceptionRowProps) {
  const [showRank, setShowRank] = useState(false);
  const [suppressOpen, setSuppressOpen] = useState(false);
  const [suppressReason, setSuppressReason] = useState('');

  const acknowledge = useMutation<string, OperationalException>({
    mutationFn: acknowledgeException,
    onSuccess: onChanged,
  });
  const resolve = useMutation<string, OperationalException>({
    mutationFn: id => resolveException(id),
    onSuccess: onChanged,
  });
  const suppress = useMutation<{ id: string; reason: string }, OperationalException>({
    mutationFn: input => suppressException(input.id, input.reason),
    onSuccess: () => {
      setSuppressOpen(false);
      setSuppressReason('');
      onChanged();
    },
  });

  const actionError = acknowledge.error ?? resolve.error ?? suppress.error;
  const suppressed = exception.status === 'suppressed';

  return (
    <div
      role="group"
      aria-label={`Exception ${exception.exception_id}`}
      className="border border-border-default rounded p-3 space-y-2"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm text-text-primary">{exception.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Badge variant={severityVariant(exception.severity)}>{exception.severity}</Badge>
            <Badge variant={suppressed ? 'warning' : 'default'}>
              {titleCase(exception.status)}
            </Badge>
            <span className="text-[11px] text-text-muted font-mono">
              priority <ScoreText value={exception.priority_score} /> · signals{' '}
              <CountText value={exception.signal_count} />
            </span>
          </div>
          {exception.probable_cause && (
            <div className="mt-1 text-[11px] text-text-secondary">
              Probable cause: {exception.probable_cause}
            </div>
          )}
          {exception.recommended_action && (
            <div className="text-[11px] text-text-secondary">
              Recommended: {exception.recommended_action}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setShowRank(current => !current)}
          >
            {showRank ? 'Hide rank inputs' : 'Why this rank'}
          </Button>
          <PermissionGate capability={INCIDENT_MANAGE}>
            <Button
              size="sm"
              variant="secondary"
              disabled={acknowledge.isLoading}
              onClick={() => void acknowledge.mutate(exception.exception_id)}
            >
              Acknowledge
            </Button>
          </PermissionGate>
          <PermissionGate capability={INCIDENT_CLOSE}>
            <Button
              size="sm"
              variant="secondary"
              disabled={resolve.isLoading}
              onClick={() => void resolve.mutate(exception.exception_id)}
            >
              Resolve
            </Button>
          </PermissionGate>
          <PermissionGate capability={INCIDENT_CLOSE}>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setSuppressOpen(current => !current)}
            >
              Suppress
            </Button>
          </PermissionGate>
        </div>
      </div>

      {suppressed && <SuppressionNotice exception={exception} />}
      {showRank && <PriorityExplanation exception={exception} />}

      {suppressOpen && (
        <div className="rounded border border-warning/40 bg-warning/10 p-3 space-y-2">
          <div className="text-xs text-warning font-semibold font-mono">
            Suppressing hides this exception without fixing it
          </div>
          <div className="text-[11px] text-text-secondary">
            The reason is recorded on the exception and shown wherever it appears. The
            condition recurring after suppression opens a fresh exception rather than
            reviving this one.
          </div>
          <label className="block text-[11px] text-text-muted font-mono">
            Suppression reason (required)
            <Input
              value={suppressReason}
              onChange={event => setSuppressReason(event.target.value)}
              placeholder="why this is safe to silence"
            />
          </label>
          <Button
            size="sm"
            disabled={suppressReason.trim() === '' || suppress.isLoading}
            onClick={() =>
              void suppress.mutate({
                id: exception.exception_id,
                reason: suppressReason.trim(),
              })
            }
          >
            Confirm suppression
          </Button>
        </div>
      )}

      {actionError !== null && (
        <div role="alert" className="text-[11px] text-danger font-mono">
          {actionError}
        </div>
      )}
    </div>
  );
}

// ── Exception queue ──────────────────────────────────────────────────────────

const STATUS_OPTIONS = [
  { value: 'open', label: 'Live (open, acknowledged, in progress)' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'suppressed', label: 'Suppressed' },
];

function ExceptionQueueCard() {
  const [status, setStatus] = useState('open');
  const { data, loading, error, refresh } = useExceptionQueue({ status });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Prioritised exception queue</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <Select
            label="Status"
            options={STATUS_OPTIONS}
            value={status}
            onChange={setStatus}
          />
          <Button size="sm" variant="secondary" onClick={refresh}>
            Refresh
          </Button>
        </div>

        {loading && data === null ? (
          <LoadingState lines={4} />
        ) : error !== null ? (
          <ErrorState title="Unable to load the exception queue" message={error} onRetry={refresh} />
        ) : data === null ? (
          <EmptyState title="No exception queue returned" />
        ) : (
          <QueueBody queue={data} onChanged={refresh} />
        )}
      </CardContent>
    </Card>
  );
}

function QueueBody({
  queue,
  onChanged,
}: {
  readonly queue: ExceptionQueue;
  readonly onChanged: () => void;
}) {
  const order = queue.order.length > 0 ? queue.order : [...BUCKET_ORDER];

  // `items` is required by the schema, so there is no absent case to paper over here.
  if (queue.items.length === 0) {
    return (
      <EmptyState
        title="Nothing in this queue"
        description="No exception matches the selected status. That is an answer about this filter, not about the platform."
      />
    );
  }

  return (
    <div className="space-y-4">
      {order.map(bucket => {
        // A bucket the response never carried is not an empty bucket. `?? []` would
        // print "Nothing in this bucket." over a bucket nobody sent.
        const rows = queue.buckets[bucket];
        return (
          <section key={bucket} className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 className="text-xs font-mono text-text-primary">
                {BUCKET_LABELS[bucket] ?? titleCase(bucket)}
              </h2>
              <span className="text-[11px] text-text-muted font-mono">
                <CountText value={queue.counts[bucket] ?? null} /> in bucket
              </span>
            </div>
            {rows === undefined ? (
              <div role="status" className="text-[11px] text-warning font-mono">
                This bucket was not returned in the response, so what is in it is{' '}
                {UNKNOWN_LABEL} — not empty.
              </div>
            ) : rows.length === 0 ? (
              <div className="text-[11px] text-text-muted font-mono">
                Nothing in this bucket.
              </div>
            ) : (
              rows.map(exception => (
                <ExceptionRow
                  key={exception.exception_id}
                  exception={exception}
                  onChanged={onChanged}
                />
              ))
            )}
          </section>
        );
      })}
    </div>
  );
}

// ── Incidents ────────────────────────────────────────────────────────────────

const BASIS_KIND_COPY: Record<BasisKind, { readonly label: string; readonly note: string }> = {
  deterministic: {
    label: 'Deterministic',
    note: 'Attached on evidence the two observations share, not on inference.',
  },
  heuristic: {
    label: 'Heuristic',
    note: 'Inferred. This attribution is a guess and may be wrong.',
  },
  founding: {
    label: 'Opened this incident',
    note: 'Not a correlation — this signal is why the incident exists.',
  },
  none: {
    label: 'No correlation recorded',
    note: 'This signal opened its own incident; nothing was correlated.',
  },
};

/**
 * Deterministic and heuristic bases must not look alike. Attributing a signal on time
 * proximity is a guess, and a guess drawn like evidence sends an operator after the
 * wrong root cause.
 */
function CorrelationBasisBadge({ basis }: { readonly basis: string | null | undefined }) {
  const kind = basisKind(basis);
  const copy = BASIS_KIND_COPY[kind];
  const variant =
    kind === 'deterministic' ? 'success' : kind === 'founding' ? 'default' : 'warning';
  const label = basis ? (BASIS_LABELS[basis] ?? basis) : null;

  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant={variant}>{copy.label}</Badge>
      {label !== null && kind !== 'none' && (
        <span className="text-[11px] text-text-muted font-mono">{label}</span>
      )}
    </span>
  );
}

function SignalRow({ signal }: { readonly signal: IncidentSignal }) {
  const kind = basisKind(signal.correlation_basis);
  const copy = BASIS_KIND_COPY[kind];
  return (
    <div
      role="group"
      aria-label={`Signal ${signal.signal_id}`}
      className={cn(
        'border rounded p-2 space-y-1',
        kind === 'deterministic' ? 'border-success/40' : 'border-warning/40',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-mono text-text-primary">{signal.signal_id}</span>
        <CorrelationBasisBadge basis={signal.correlation_basis} />
        <span className="text-[11px] text-text-muted font-mono">
          confidence <CountText value={signal.correlation_confidence} />
        </span>
      </div>
      <div className="text-[11px] text-text-secondary">
        {signal.source} · {signal.signal_type}
        {signal.service ? ` · ${signal.service}` : ''}
        {signal.error_signature ? ` · ${signal.error_signature}` : ''}
      </div>
      <div className="text-[11px] text-text-muted">{copy.note}</div>
    </div>
  );
}

function ResumeCardView({ card }: { readonly card: ResumeCard }) {
  const pending = card.pending_verification ?? [];
  return (
    <div
      role="group"
      aria-label={`Resume card ${card.incident_id}`}
      className="border border-border-default rounded p-3 space-y-1"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-text-primary">{card.title}</span>
        <Badge variant={severityVariant(card.severity)}>{card.severity}</Badge>
        <Badge variant="default">{titleCase(card.status)}</Badge>
        <span className="text-[11px] text-text-muted font-mono">
          priority <ScoreText value={card.priority_score} />
        </span>
      </div>
      <div className="text-[11px] text-text-secondary">
        Last action: {card.last_action ?? 'none recorded'}
      </div>
      <div className="text-[11px] text-text-secondary">
        Next action: {card.next_action ?? 'none recorded — this incident cannot be resumed as written'}
      </div>
      <div className="text-[11px] text-text-secondary">
        Blocked by: {card.blocked_by ?? 'nothing recorded'}
      </div>
      <div className="text-[11px] text-text-secondary">
        Pending verification:{' '}
        {pending.length === 0 ? 'nothing recorded' : pending.join(', ')}
      </div>
      {(card.missing_inputs ?? []).length > 0 && (
        <div className="text-[11px] text-warning font-mono">
          Missing inputs: {(card.missing_inputs ?? []).join(', ')}
        </div>
      )}
    </div>
  );
}

function IncidentDetailPanel({ detail }: { readonly detail: IncidentDetail }) {
  if (!detail.found || detail.incident === null) {
    return <EmptyState title="That incident could not be read" />;
  }
  const incident: Incident = detail.incident;
  // Tri-state on purpose. `?? []` rendered a null timeline as "Attached signals (0)"
  // plus "No signals attached to this incident" — an unread timeline presented as an
  // incident with nothing behind it, which is exactly the reading that closes an
  // investigation early.
  const timeline: readonly IncidentSignal[] | null = detail.timeline ?? null;
  const weakLinks = detail.weak_links ?? [];

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-text-primary">{incident.title}</span>
          <Badge variant={severityVariant(incident.severity)}>{incident.severity}</Badge>
          <Badge variant="default">{titleCase(incident.status)}</Badge>
        </div>
        <div className="text-[11px] text-text-secondary">
          Root cause: {incident.root_cause ?? 'not established'}
        </div>
      </div>

      {detail.resume_card && <ResumeCardView card={detail.resume_card} />}

      <div className="space-y-2">
        <h3 className="text-xs font-mono text-text-primary">
          Attached signals ({timeline === null ? UNKNOWN_LABEL : timeline.length})
        </h3>
        {timeline === null ? (
          <div
            role="status"
            className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
          >
            <div className="font-semibold font-mono">
              Timeline {UNKNOWN_LABEL} — no signal list came back with this incident
            </div>
            <div className="mt-1 text-text-secondary">
              How many signals are attached, and which, could not be read. That is not
              the same as none being attached, and this incident cannot be judged on the
              evidence shown here.
            </div>
          </div>
        ) : timeline.length === 0 ? (
          <EmptyState title="No signals attached to this incident" />
        ) : (
          timeline.map(signal => <SignalRow key={signal.signal_id} signal={signal} />)
        )}
      </div>

      {weakLinks.length > 0 && (
        <div className="rounded border border-warning/40 bg-warning/10 p-3 space-y-1">
          <div className="text-xs text-warning font-semibold font-mono">
            Weak links — declined, not merged
          </div>
          <div className="text-[11px] text-text-secondary">
            These incidents coincided in time with this one. Time proximity is not
            evidence of a shared cause, so nothing was merged on it.
          </div>
          <ul className="text-[11px] text-text-secondary space-y-0.5">
            {weakLinks.map(link => (
              <li key={link.incident_id}>
                · {link.incident_id} — {BASIS_LABELS[link.basis ?? ''] ?? link.basis ?? UNKNOWN_LABEL}
                {link.note ? ` (${link.note})` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function IncidentsCard() {
  const [selected, setSelected] = useState<string | null>(null);
  const { data, loading, error, refresh } = useIncidents('open');
  const detail = useIncident(selected);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Correlated incidents</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading && data === null ? (
          <LoadingState lines={4} />
        ) : error !== null ? (
          <ErrorState title="Unable to load incidents" message={error} onRetry={refresh} />
        ) : data === null || data.incidents.length === 0 ? (
          <EmptyState
            title="No open incidents"
            description="Nothing is currently correlated into an open incident."
          />
        ) : (
          <div className="space-y-2">
            {data.incidents.map(incident => (
              <button
                key={incident.incident_id}
                type="button"
                onClick={() => setSelected(incident.incident_id)}
                className="w-full text-left border border-border-default rounded p-2 hover:bg-surface-raised"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-text-primary">{incident.title}</span>
                  <Badge variant={severityVariant(incident.severity)}>
                    {incident.severity}
                  </Badge>
                  <Badge variant="default">{titleCase(incident.status)}</Badge>
                  <span className="text-[11px] text-text-muted font-mono">
                    signals <CountText value={incident.signal_count} /> · priority{' '}
                    <ScoreText value={incident.priority_score} />
                  </span>
                </div>
                <div className="text-[11px] text-text-secondary">
                  Next action: {incident.next_action ?? 'none recorded'}
                </div>
              </button>
            ))}
          </div>
        )}

        {selected !== null && (
          <div className="border-t border-border-default pt-3">
            {detail.loading && detail.data === null ? (
              <LoadingState lines={3} />
            ) : detail.error !== null ? (
              <ErrorState
                title="Unable to load the incident timeline"
                message={detail.error}
                onRetry={detail.refresh}
              />
            ) : detail.data === null ? (
              <EmptyState title="No incident detail returned" />
            ) : (
              <IncidentDetailPanel detail={detail.data} />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Resume cards ─────────────────────────────────────────────────────────────

function ResumeCardsCard() {
  const { data, loading, error, refresh } = useResumeCards();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cards for half-finished responses</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[11px] text-text-secondary">
          Deterministic fields only — last action, next action, what is blocking and what
          is still pending verification. The card has to be readable when no summariser
          is available.
        </p>
        {loading && data === null ? (
          <LoadingState lines={3} />
        ) : error !== null ? (
          <ErrorState title="Unable to load resume cards" message={error} onRetry={refresh} />
        ) : data === null || data.cards.length === 0 ? (
          <EmptyState
            title="No half-finished investigations"
            description="Nothing is part-way through a response right now."
          />
        ) : (
          <div className="space-y-2">
            {data.cards.map(card => (
              <ResumeCardView key={card.incident_id} card={card} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function KyberExceptionsPage() {
  return (
    <PageWrapper title="Exceptions & incidents" subtitle={PAGE_SUBTITLE}>
      <Tabs defaultValue="queue">
        <TabsList>
          <TabsTrigger value="queue">Exception queue</TabsTrigger>
          <TabsTrigger value="incidents">Incidents</TabsTrigger>
          <TabsTrigger value="resume">Resume cards</TabsTrigger>
        </TabsList>
        <TabsContent value="queue">
          <ExceptionQueueCard />
        </TabsContent>
        <TabsContent value="incidents">
          <IncidentsCard />
        </TabsContent>
        <TabsContent value="resume">
          <ResumeCardsCard />
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
