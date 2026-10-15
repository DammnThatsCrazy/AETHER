/**
 * KYBER — Commands & containment (operator).
 *
 * This page has real authority. A mistake here changes production state, so every
 * rendering decision below is made against the question "what would this make an
 * operator believe, and what would they do next if it were wrong?".
 *
 *  · **`executed_unverified` is never drawn as success.** It is the honest answer
 *    between "the call returned" and "the system is in the state we wanted", and those
 *    are different questions. It gets a warning treatment; `verified` is the only
 *    status that gets a success one. A `verification` of `null` is rendered as an open
 *    question rather than omitted, because an absent field reads as a question nobody
 *    asked.
 *
 *  · **Blast radius is shown before the operator can execute, not after.** When the
 *    assessment is unavailable, or ran with a missing input, the reach renders as
 *    Unknown with the inputs that were absent, and no number is drawn anywhere in the
 *    reach region. An unknown reach displayed as a small one is how a fleet-wide
 *    action gets waved through. The execute control is gated on the reach being
 *    *known* — `reachIsKnown`, not `available` — because an assessment that ran with a
 *    missing input measured nothing, and an unmeasured reach must not be dispatchable.
 *    A reach dimension the assessor did not report is Unknown too: `null` tenants are
 *    "we do not know which tenants", never "no tenants are affected".
 *
 *  · **`executed_unverified` has a way out.** `/verify` re-runs the postconditions and
 *    is the only path off that status. It is offered only from that status, and it is
 *    not a way to declare a command verified — the checks decide. Without the control
 *    the state is a dead end, and a dead end is how it decays into "probably fine".
 *
 *  · **A refusal is shown with its reason.** Self-approval, an unqualified approver and
 *    a duplicate approval are refused and audited by the backend; those refusals are
 *    rendered in the backend's own words. A step-up-required response is an expected,
 *    explainable state with a next action — not a generic error.
 *
 *  · **Safe mode does not stop ingestion**, and the control says so. Losing inbound
 *    events during an incident turns a recoverable outage into permanent data loss, so
 *    an operator must not infer from a quiet pipeline that ingestion was contained.
 *
 *  · **Routing is not a grant.** Reaching this URL proves nothing. The page reads the
 *    backend-supplied capability list and renders its own forbidden state, and every
 *    destructive control sits behind a `PermissionGate` naming the capability the
 *    backend will actually enforce.
 */

import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Select,
  StatusIndicator,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useMutation,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { PermissionGate, useCapabilities } from '@kyber/features/permissions';
import { cn } from '@kyber/lib/utils';
import {
  APPROVAL_GAP_LABELS,
  UNVERIFIED_STATUS,
  VERIFIED_STATUS,
  activateContainment,
  activateSafeMode,
  approveCommand,
  deactivateContainment,
  dryRunCommand,
  executeCommand,
  isStepUpRequired,
  reachIsKnown,
  reachMissingInputs,
  releaseSafeMode,
  requestCommand,
  useCommand,
  useCommandTypes,
  useCommands,
  useContainment,
  verifyCommand,
  CommandReceiptsPanel,
} from '@kyber/features/kyber-ops';
import {
  ContinuationCreateButton,
  OperatorContinuationPanel,
} from '@kyber/features/continuation';
import type {
  BlastRadius,
  CommandDetail,
  CommandRequestInput,
  CommandRequestResult,
  CommandSpec,
  ContainmentInput,
  ContainmentState,
  ContainmentSwitch,
  DryRunPlan,
  SafeModeResult,
} from '@kyber/features/kyber-ops';

const PAGE_SUBTITLE =
  'The governed command plane. A 200 is not success: a command is unverified until its postconditions are checked, and reach is shown before anything is dispatched.';

/** Capabilities the ops router enforces on these routes. */
const AUDIT_READ = 'kyber.audit.read';
const INCIDENT_READ = 'kyber.incident.read';
const PAUSE_CAPABILITY = 'kyber.command.pause';
const KILL_SWITCH_CAPABILITY = 'kyber.command.kill_switch';

export const UNKNOWN_LABEL = 'Unknown';

// ── Honest primitives ────────────────────────────────────────────────────────

function CountText({ value }: { readonly value: number | null | undefined }) {
  if (value === null || value === undefined) {
    return <span className="text-warning font-mono">{UNKNOWN_LABEL}</span>;
  }
  return <span className="font-mono text-text-primary">{value}</span>;
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, ' ');
}

function readStringArray(
  record: Record<string, unknown> | null | undefined,
  key: string,
): readonly string[] {
  if (!record) return [];
  const value = record[key];
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === 'string');
}

function splitList(value: string): string[] {
  return value
    .split(',')
    .map(entry => entry.trim())
    .filter(entry => entry !== '');
}

/** A denial that has a next action attached, rendered as such rather than as a failure. */
function StepUpNotice({ message }: { readonly message: string }) {
  return (
    <div
      role="status"
      className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
    >
      <div className="font-semibold font-mono">Step-up required</div>
      <div className="mt-1 text-text-secondary">{message}</div>
      <div className="mt-1 text-[11px] text-text-muted">
        A class 4 or 5 command needs a live step-up grant. This is an expected state with
        a next action — re-authenticate and retry — not a fault in the command.
      </div>
    </div>
  );
}

/**
 * The backend's own refusal text. Approval refusals in particular (self-approval, an
 * unqualified approver, the same operator twice) each name what was wrong; replacing
 * them with a generic message throws away the only actionable part.
 */
function RefusalNotice({ title, message }: { readonly title: string; readonly message: string }) {
  if (isStepUpRequired(message)) return <StepUpNotice message={message} />;
  return (
    <div role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-xs">
      <div className="font-semibold font-mono text-danger">{title}</div>
      <div className="mt-1 text-text-secondary">{message}</div>
    </div>
  );
}

// ── Command status ───────────────────────────────────────────────────────────

/**
 * `verified` is the only status that gets a success treatment. `executed_unverified`
 * gets a warning one: the side effect landed and the postconditions did not confirm,
 * and drawing that as success is the single most damaging thing this page could do.
 * Drawing it as `failed` would be the second, because it would tell an operator that
 * nothing happened.
 */
function CommandStatusBadge({ status }: { readonly status: string }) {
  if (status === VERIFIED_STATUS) return <Badge variant="success">Verified</Badge>;
  if (status === UNVERIFIED_STATUS) {
    return <Badge variant="warning">Executed — not verified</Badge>;
  }
  if (status === 'failed' || status === 'rejected' || status === 'expired') {
    return <Badge variant="danger">{titleCase(status)}</Badge>;
  }
  return <Badge variant="default">{titleCase(status)}</Badge>;
}

const STAGE_ORDER = [
  'Requested',
  'Dry run',
  'Approval',
  'Execution',
  'Verification',
] as const;

type StageState = 'done' | 'open' | 'blocked' | 'skipped';

const STAGE_VARIANT: Record<StageState, 'success' | 'warning' | 'default' | 'danger'> = {
  done: 'success',
  open: 'default',
  blocked: 'warning',
  skipped: 'default',
};

function stageStates(detail: CommandDetail): Record<string, { state: StageState; note: string }> {
  const command = detail.command;
  const gaps = readStringArray(command.metadata, 'approval_gaps');
  const dryRunAt = command.metadata?.['dry_run_at'];
  const requiresDryRun = detail.spec?.requires_dry_run === true;
  const executed = detail.execution !== null;

  return {
    Requested: { state: 'done', note: `requested by ${command.requested_by}` },
    'Dry run': {
      state:
        typeof dryRunAt === 'string'
          ? 'done'
          : requiresDryRun
            ? 'blocked'
            : 'skipped',
      note:
        typeof dryRunAt === 'string'
          ? 'handler resolved and arguments bound; nothing was dispatched'
          : requiresDryRun
            ? 'required by this command type and not yet run'
            : 'not required by this command type',
    },
    Approval: {
      state: gaps.length === 0 ? 'done' : 'blocked',
      note:
        gaps.length === 0
          ? 'no approval gap outstanding'
          : `${gaps.length} gate(s) outstanding`,
    },
    Execution: {
      state: executed ? 'done' : 'open',
      note: executed ? 'the handler was dispatched' : 'not dispatched',
    },
    Verification: {
      state:
        detail.verification === null
          ? 'open'
          : detail.verification.outcome === 'passed'
            ? 'done'
            : 'blocked',
      note:
        detail.verification === null
          ? 'no verification record — the question is still open'
          : `postconditions ${detail.verification.outcome}`,
    },
  };
}

function StageStrip({ detail }: { readonly detail: CommandDetail }) {
  const states = stageStates(detail);
  return (
    <div className="flex flex-wrap gap-2">
      {STAGE_ORDER.map(stage => {
        const entry = states[stage];
        const state: StageState = entry?.state ?? 'open';
        return (
          <div
            key={stage}
            className="border border-border-default rounded px-2 py-1 text-[11px] font-mono"
          >
            <div className="flex items-center gap-1">
              <span className="text-text-primary">{stage}</span>
              <Badge variant={STAGE_VARIANT[state]} size="sm">
                {state}
              </Badge>
            </div>
            <div className="text-text-muted">{entry?.note ?? ''}</div>
          </div>
        );
      })}
    </div>
  );
}

// ── Blast radius, shown before anything can be dispatched ────────────────────

/**
 * One dimension of the reach.
 *
 * Two separate things can be unknown here and both render as Unknown. `known` is the
 * assessment-level answer — the assessor was unreachable, or it ran with a missing
 * input. A nullish `values` is the dimension-level one: the assessment ran and did not
 * report this dimension at all. `(values ?? []).length` would draw that second case as
 * `0` and "none in reach", which is "no tenants are affected" written over "we do not
 * know which tenants" — the most dangerous possible reading on a blast-radius panel.
 *
 * An empty array is different again, and is the one case a zero is honest: the assessor
 * reported this dimension and found nothing in it.
 */
function ReachTile({
  label,
  values,
  known,
}: {
  readonly label: string;
  readonly values: readonly string[] | null | undefined;
  readonly known: boolean;
}) {
  const reported = values !== null && values !== undefined;
  return (
    <div className="border border-border-default rounded p-2">
      <div className="text-[11px] text-text-muted font-mono">{label}</div>
      {known && reported ? (
        <>
          <div className="text-sm font-mono text-text-primary">
            <CountText value={values.length} />
          </div>
          <div className="text-[10px] text-text-secondary break-words">
            {values.length === 0 ? 'none in reach' : values.join(', ')}
          </div>
        </>
      ) : (
        <>
          <div className="text-sm font-mono text-warning">{UNKNOWN_LABEL}</div>
          {known && (
            <div className="text-[10px] text-text-muted break-words">
              The assessment did not report this dimension. Unknown, not none.
            </div>
          )}
        </>
      )}
    </div>
  );
}

function BlastRadiusPanel({ radius }: { readonly radius: BlastRadius | null | undefined }) {
  const known = reachIsKnown(radius);
  const missing = reachMissingInputs(radius);

  return (
    <div className="space-y-2">
      <div className="text-xs font-mono text-text-primary">Blast radius</div>

      {radius === null || radius === undefined ? (
        <div
          role="status"
          className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
        >
          <div className="font-semibold font-mono">
            Reach {UNKNOWN_LABEL} — no assessment is attached to this command
          </div>
          <div className="mt-1 text-text-secondary">
            Nothing about the reach of this command is known. That is not the same as a
            small reach.
          </div>
        </div>
      ) : known ? (
        <div
          role="status"
          className="rounded border border-border-default bg-surface-raised px-3 py-2 text-xs text-text-secondary"
        >
          <span className="font-semibold font-mono text-success">Reach assessed</span>
          {radius.summary ? ` — ${radius.summary}` : ''}
          {radius.truncated === true && (
            <div className="mt-1 text-warning">
              The traversal hit its node budget, so nodes that exist were dropped from
              this answer.
            </div>
          )}
        </div>
      ) : (
        <div
          role="status"
          className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
        >
          <div className="font-semibold font-mono">
            Reach {UNKNOWN_LABEL} — this is not a small reach, it is an unmeasured one
          </div>
          {radius.reason && (
            <div className="mt-1 text-text-secondary">Reason: {radius.reason}</div>
          )}
          {missing.length > 0 && (
            <ul className="mt-1 text-[11px] text-text-secondary space-y-0.5 font-mono">
              {missing.map(entry => (
                <li key={entry}>· {entry}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div role="group" aria-label="Blast radius reach" className="grid gap-2 md:grid-cols-4">
        <ReachTile label="Services in reach" values={radius?.affected_services} known={known} />
        <ReachTile label="Features in reach" values={radius?.affected_features} known={known} />
        <ReachTile label="Tenants in reach" values={radius?.affected_tenants} known={known} />
        <ReachTile
          label="Graph domains in reach"
          values={radius?.affected_graph_domains}
          known={known}
        />
      </div>
    </div>
  );
}

// ── Approvals ────────────────────────────────────────────────────────────────

function ApprovalsPanel({ detail }: { readonly detail: CommandDetail }) {
  const command = detail.command;
  const gaps = readStringArray(command.metadata, 'approval_gaps');
  const approvals = command.approvals ?? [];

  return (
    <div className="space-y-2">
      <div className="text-xs font-mono text-text-primary">Approvals</div>
      <div className="text-[11px] text-text-secondary font-mono">
        Required approvals: <CountText value={command.required_approvals} /> · mode{' '}
        {command.approval_mode ?? UNKNOWN_LABEL} · step-up{' '}
        {command.step_up_verified === true ? 'verified' : 'not verified'}
      </div>

      {approvals.length === 0 ? (
        <div className="text-[11px] text-text-muted font-mono">
          No approval has been recorded.
        </div>
      ) : (
        <ul className="text-[11px] text-text-secondary space-y-0.5 font-mono">
          {approvals.map(approval => (
            <li key={approval.approver_id}>
              · {approval.approver_id} — {approval.approved_at ?? UNKNOWN_LABEL}
            </li>
          ))}
        </ul>
      )}

      {gaps.length > 0 && (
        <div className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
          <div className="font-semibold font-mono">Approval gaps</div>
          <ul className="mt-1 space-y-0.5 text-text-secondary">
            {gaps.map(gap => (
              <li key={gap}>· {APPROVAL_GAP_LABELS[gap] ?? titleCase(gap)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Verification ─────────────────────────────────────────────────────────────

function VerificationPanel({ detail }: { readonly detail: CommandDetail }) {
  const verification = detail.verification;

  if (verification === null) {
    return (
      <div className="space-y-2">
        <div className="text-xs font-mono text-text-primary">Verification</div>
        <div
          role="status"
          className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
        >
          <div className="font-semibold font-mono">Not verified</div>
          <div className="mt-1 text-text-secondary">
            No verification record exists for this command. The postconditions were never
            confirmed, which is an open question rather than an absent one.
          </div>
        </div>
      </div>
    );
  }

  const checks = verification.checks ?? [];
  const failing = checks.filter(check => check.outcome !== 'passed');
  const passed = verification.outcome === 'passed';

  return (
    <div className="space-y-2">
      <div className="text-xs font-mono text-text-primary">Verification</div>
      <div
        role="status"
        className={cn(
          'rounded border px-3 py-2 text-xs',
          passed
            ? 'border-border-default bg-surface-raised text-text-secondary'
            : 'border-warning/40 bg-warning/10 text-warning',
        )}
      >
        <div className="font-semibold font-mono">
          {passed
            ? 'Postconditions passed'
            : `Postconditions ${verification.outcome} — the intended state was not confirmed`}
        </div>
        {verification.failure_reason && (
          <div className="mt-1 text-text-secondary">
            Failure reason: {verification.failure_reason}
          </div>
        )}
      </div>

      {failing.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] text-text-muted font-mono">
            Checks that did not pass
          </div>
          <ul className="text-[11px] space-y-1">
            {failing.map(check => (
              <li key={check.check} className="font-mono">
                <span className="text-danger">{check.check}</span>{' '}
                <Badge variant={check.outcome === 'failed' ? 'danger' : 'warning'} size="sm">
                  {check.outcome}
                </Badge>
                {check.detail ? (
                  <span className="text-text-secondary"> — {check.detail}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {checks.length > 0 && failing.length === 0 && (
        <ul className="text-[11px] text-text-secondary space-y-0.5 font-mono">
          {checks.map(check => (
            <li key={check.check}>· {check.check} — {check.outcome}</li>
          ))}
        </ul>
      )}

      {(verification.mirror_digest_before || verification.mirror_digest_after) && (
        <div className="text-[10px] text-text-muted font-mono">
          Mirror digest before {verification.mirror_digest_before ?? UNKNOWN_LABEL} · after{' '}
          {verification.mirror_digest_after ?? UNKNOWN_LABEL}
        </div>
      )}
    </div>
  );
}

// ── One command ──────────────────────────────────────────────────────────────

function CommandDetailPanel({
  detail,
  onChanged,
}: {
  readonly detail: CommandDetail;
  readonly onChanged: () => void;
}) {
  const command = detail.command;
  const spec = detail.spec;
  const radius = command.blast_radius ?? null;
  // Not a styling decision: an action whose reach is not KNOWN must not be dispatchable
  // from this page. `available === true` is the weaker question — it only says the
  // assessor answered. `reachIsKnown` also requires `exposure_known`, because an
  // assessment that ran with a missing input or hit its node budget measured nothing,
  // and the panel three rows up says so in those words. Gating on `available` alone
  // printed "this is not a small reach, it is an unmeasured one" beside a live Execute
  // button.
  const reachKnown = reachIsKnown(radius);
  // Which of the two the operator is looking at, so the notice can say which.
  const assessorAnswered = radius !== null && radius.available === true;

  const dryRun = useMutation<string, DryRunPlan>({
    mutationFn: dryRunCommand,
    onSuccess: onChanged,
  });
  const approve = useMutation<string, unknown>({
    mutationFn: approveCommand,
    onSuccess: onChanged,
  });
  const execute = useMutation<string, CommandDetail>({
    mutationFn: executeCommand,
    onSuccess: onChanged,
  });
  const verify = useMutation<string, CommandDetail>({
    mutationFn: verifyCommand,
    onSuccess: onChanged,
  });

  return (
    <div className="space-y-4 border-t border-border-default pt-3">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-text-primary font-mono">{command.command_type}</span>
          <div role="group" aria-label="Command status">
            <CommandStatusBadge status={command.status} />
          </div>
          <span className="text-[11px] text-text-muted font-mono">{command.command_id}</span>
        </div>
        <div className="text-[11px] text-text-secondary">Reason: {command.reason}</div>
        {spec && (
          <div className="text-[11px] text-text-muted font-mono">
            action class {spec.action_class} · capability {spec.capability_id} · handler{' '}
            {spec.handler}
          </div>
        )}
      </div>

      <StageStrip detail={detail} />

      {command.status === UNVERIFIED_STATUS && (
        <div
          role="status"
          className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
        >
          <div className="font-semibold font-mono">
            The side effect landed and the postconditions did not confirm
          </div>
          <div className="mt-1 text-text-secondary">
            This is not a success and it is not a failure: the call returned, and whether
            the system reached the state you asked for is still open. Re-verify before
            acting on it.
          </div>
        </div>
      )}

      {command.status === UNVERIFIED_STATUS && (
        <div className="space-y-1">
          <PermissionGate capability={spec?.capability_id ?? 'kyber.command.dispatch'}>
            <Button
              size="sm"
              variant="secondary"
              disabled={verify.isLoading}
              onClick={() => void verify.mutate(command.command_id)}
            >
              Re-verify postconditions
            </Button>
          </PermissionGate>
          <div className="text-[11px] text-text-muted font-mono">
            Re-verification re-runs the declared postconditions. It is the only way off
            this status, and it is not a way to declare the command verified — the checks
            decide. Some of them can only be answered once the platform catches up.
          </div>
          {verify.error !== null && (
            <RefusalNotice title="Re-verification refused" message={verify.error} />
          )}
        </div>
      )}

      <BlastRadiusPanel radius={radius} />

      <ApprovalsPanel detail={detail} />

      {detail.execution !== null && (
        <div className="space-y-1">
          <div className="text-xs font-mono text-text-primary">Execution</div>
          <div className="text-[11px] text-text-secondary font-mono">
            attempt <CountText value={detail.execution.attempt} /> · started{' '}
            {detail.execution.started_at ?? UNKNOWN_LABEL} · completed{' '}
            {detail.execution.completed_at ?? UNKNOWN_LABEL}
          </div>
          {detail.execution.error && (
            <div className="text-[11px] text-danger font-mono">
              Handler error: {detail.execution.error}
            </div>
          )}
          {(detail.execution.side_effects ?? []).length > 0 && (
            <div className="text-[11px] text-text-secondary">
              Side effects: {(detail.execution.side_effects ?? []).join(', ')}
            </div>
          )}
        </div>
      )}

      <VerificationPanel detail={detail} />

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <PermissionGate capability={spec?.capability_id ?? 'kyber.command.dispatch'}>
            <Button
              size="sm"
              variant="secondary"
              disabled={dryRun.isLoading}
              onClick={() => void dryRun.mutate(command.command_id)}
            >
              Dry run
            </Button>
          </PermissionGate>
          <PermissionGate capability={spec?.capability_id ?? 'kyber.command.dispatch'}>
            <Button
              size="sm"
              variant="secondary"
              disabled={approve.isLoading}
              onClick={() => void approve.mutate(command.command_id)}
            >
              Approve
            </Button>
          </PermissionGate>
          <PermissionGate capability={spec?.capability_id ?? 'kyber.command.dispatch'}>
            <Button
              size="sm"
              variant="danger"
              disabled={!reachKnown || execute.isLoading}
              onClick={() => void execute.mutate(command.command_id)}
            >
              Execute
            </Button>
          </PermissionGate>
        </div>

        {!reachKnown && (
          <div role="status" className="text-[11px] text-warning font-mono">
            {assessorAnswered
              ? 'Execute is unavailable: the blast radius was assessed without a complete reach, so it is unmeasured rather than small, and an action whose reach is unknown is not dispatched from this console.'
              : 'Execute is unavailable: the blast radius could not be assessed, and an action whose reach is unknown is not dispatched from this console.'}
          </div>
        )}

        {dryRun.error !== null && (
          <RefusalNotice title="Dry run refused" message={dryRun.error} />
        )}
        {approve.error !== null && (
          <RefusalNotice title="Approval refused" message={approve.error} />
        )}
        {execute.error !== null && (
          <RefusalNotice title="Execution refused" message={execute.error} />
        )}

        {dryRun.data !== null && (
          <div className="rounded border border-border-default bg-surface-raised p-2 text-[11px] font-mono space-y-0.5">
            <div className="text-text-primary">Dry-run plan — nothing was dispatched</div>
            <div className="text-text-secondary">handler {dryRun.data.handler}</div>
            <div className="text-text-secondary">
              containment target{' '}
              {dryRun.data.containment_target === null
                ? 'none'
                : `${dryRun.data.containment_target.scope ?? UNKNOWN_LABEL}:${
                    dryRun.data.containment_target.control ?? UNKNOWN_LABEL
                  }`}
            </div>
            <div className="text-text-secondary">
              verification plan:{' '}
              {(dryRun.data.verification_plan ?? []).length === 0
                ? 'none declared'
                : (dryRun.data.verification_plan ?? []).join(', ')}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Command queue ────────────────────────────────────────────────────────────

const COMMAND_STATUS_OPTIONS = [
  { value: 'open', label: 'Open (includes executed but unverified)' },
  { value: 'verified', label: 'Verified only' },
  { value: 'executed_unverified', label: 'Executed but unverified only' },
  { value: 'failed', label: 'Failed only' },
];

function CommandQueueCard() {
  const [status, setStatus] = useState('open');
  const [selected, setSelected] = useState<string | null>(null);
  const { data, loading, error, refresh } = useCommands(status);
  const detail = useCommand(selected);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Command queue</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <Select
            label="Status"
            options={COMMAND_STATUS_OPTIONS}
            value={status}
            onChange={setStatus}
          />
          <Button size="sm" variant="secondary" onClick={refresh}>
            Refresh
          </Button>
        </div>
        <p className="text-[11px] text-text-secondary">
          The open queue includes commands that executed and were never verified. A
          command whose postconditions were not confirmed is still an open question,
          however long ago the call returned.
        </p>

        {loading && data === null ? (
          <LoadingState lines={4} />
        ) : error !== null ? (
          <ErrorState title="Unable to load commands" message={error} onRetry={refresh} />
        ) : data === null || data.commands.length === 0 ? (
          <EmptyState title="No commands in this queue" />
        ) : (
          <div className="space-y-2">
            {data.commands.map(command => (
              <button
                key={command.command_id}
                type="button"
                onClick={() => setSelected(command.command_id)}
                className="w-full text-left border border-border-default rounded p-2 hover:bg-surface-raised"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-mono text-text-primary">
                    {command.command_type}
                  </span>
                  <CommandStatusBadge status={command.status} />
                  <span className="text-[11px] text-text-muted font-mono">
                    class <CountText value={command.action_class} /> · {command.requested_by}
                  </span>
                </div>
                <div className="text-[11px] text-text-secondary">{command.reason}</div>
              </button>
            ))}
          </div>
        )}

        {selected !== null &&
          (detail.loading && detail.data === null ? (
            <LoadingState lines={3} />
          ) : detail.error !== null ? (
            <ErrorState
              title="Unable to load the command"
              message={detail.error}
              onRetry={detail.refresh}
            />
          ) : detail.data === null ? (
            <EmptyState title="No command detail returned" />
          ) : (
            <CommandDetailPanel
              detail={detail.data}
              onChanged={() => {
                detail.refresh();
                refresh();
              }}
            />
          ))}
      </CardContent>
    </Card>
  );
}

// ── Registered command types ─────────────────────────────────────────────────

function CommandTypesCard() {
  const { data, loading, error, refresh } = useCommandTypes();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Registered command types</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[11px] text-text-secondary">
          The catalog is readable by any authenticated operator. Knowing that a command
          exists confers nothing — running it needs the capability named here, its action
          class ceiling and, for class 4 and 5, a live step-up.
        </p>
        {loading && data === null ? (
          <LoadingState lines={4} />
        ) : error !== null ? (
          <ErrorState title="Unable to load the command catalog" message={error} onRetry={refresh} />
        ) : data === null || data.types.length === 0 ? (
          <EmptyState title="No command types registered" />
        ) : (
          <DataTable<CommandSpec>
            data={data.types}
            keyExtractor={spec => spec.command_type}
            columns={[
              {
                key: 'command_type',
                header: 'Command',
                render: spec => (
                  <div>
                    <div className="font-mono text-text-primary">{spec.command_type}</div>
                    <div className="text-[11px] text-text-secondary">{spec.title}</div>
                  </div>
                ),
              },
              {
                key: 'action_class',
                header: 'Action class',
                render: spec => (
                  <Badge variant={spec.action_class >= 4 ? 'danger' : 'default'}>
                    {spec.action_class}
                  </Badge>
                ),
              },
              {
                key: 'capability',
                header: 'Capability',
                render: spec => <span className="font-mono">{spec.capability_id}</span>,
              },
              {
                key: 'dry_run',
                header: 'Dry run',
                render: spec =>
                  spec.requires_dry_run === true ? (
                    <Badge variant="warning">Required</Badge>
                  ) : (
                    <span className="text-text-muted">not required</span>
                  ),
              },
              {
                key: 'rollback',
                header: 'Rollback plan',
                render: spec =>
                  spec.requires_rollback_plan === true ? (
                    <Badge variant="warning">Required</Badge>
                  ) : (
                    <span className="text-text-muted">not required</span>
                  ),
              },
              {
                key: 'verification',
                header: 'Postconditions checked',
                render: spec => (
                  <span className="font-mono text-[11px]">
                    {(spec.verification_checks ?? []).length === 0
                      ? 'none declared'
                      : (spec.verification_checks ?? []).join(', ')}
                  </span>
                ),
              },
            ]}
          />
        )}
      </CardContent>
    </Card>
  );
}

// ── Request a command ────────────────────────────────────────────────────────

function RequestCommandCard({ specs }: { readonly specs: readonly CommandSpec[] }) {
  const [commandType, setCommandType] = useState('');
  const [reason, setReason] = useState('');
  const [idempotencyKey, setIdempotencyKey] = useState('');
  const [tenantIds, setTenantIds] = useState('');
  const [rollbackPlan, setRollbackPlan] = useState('');
  const [typedConfirmation, setTypedConfirmation] = useState('');

  const request = useMutation<CommandRequestInput, CommandRequestResult>({
    mutationFn: requestCommand,
  });

  const spec = specs.find(entry => entry.command_type === commandType) ?? null;
  const ready =
    commandType !== '' && reason.trim() !== '' && idempotencyKey.trim() !== '';

  function submit(): void {
    const payload: CommandRequestInput = {
      command_type: commandType,
      reason: reason.trim(),
      idempotency_key: idempotencyKey.trim(),
      tenant_ids: splitList(tenantIds),
      ...(rollbackPlan.trim() === '' ? {} : { rollback_plan: rollbackPlan.trim() }),
      ...(typedConfirmation.trim() === ''
        ? {}
        : { typed_confirmation: typedConfirmation.trim() }),
    };
    void request.mutate(payload);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Request a command</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[11px] text-text-secondary">
          Requesting is not executing. The idempotency key is required and has no default:
          generating one per attempt would make every retry a fresh command, which is
          exactly the duplicate execution the plane exists to prevent.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <Select
            label="Command type"
            options={[
              { value: '', label: 'select a command type' },
              ...specs.map(entry => ({
                value: entry.command_type,
                label: `${entry.command_type} (class ${entry.action_class})`,
              })),
            ]}
            value={commandType}
            onChange={setCommandType}
          />
          <label className="text-[11px] text-text-muted font-mono">
            Reason (required)
            <Input
              value={reason}
              onChange={event => setReason(event.target.value)}
              placeholder="why this change is needed"
            />
          </label>
          <label className="text-[11px] text-text-muted font-mono">
            Idempotency key (required)
            <Input
              value={idempotencyKey}
              onChange={event => setIdempotencyKey(event.target.value)}
              placeholder="stable key for this intent"
            />
          </label>
          <label className="text-[11px] text-text-muted font-mono">
            Tenant IDs
            <Input
              value={tenantIds}
              onChange={event => setTenantIds(event.target.value)}
              placeholder="comma separated"
            />
          </label>
        </div>

        {spec?.requires_rollback_plan === true && (
          <label className="block text-[11px] text-warning font-mono">
            Rollback plan (required by this command type)
            <Input
              value={rollbackPlan}
              onChange={event => setRollbackPlan(event.target.value)}
              placeholder="how this is undone"
            />
          </label>
        )}

        {spec !== null && spec.action_class >= 4 && (
          <label className="block text-[11px] text-warning font-mono">
            Type the command type back to confirm ({spec.command_type})
            <Input
              value={typedConfirmation}
              onChange={event => setTypedConfirmation(event.target.value)}
              placeholder={spec.command_type}
            />
          </label>
        )}

        {spec !== null && (
          <div className="text-[11px] text-text-secondary font-mono">
            This is a class {spec.action_class} command gated on {spec.capability_id}
            {spec.action_class >= 4 ? ' and a live step-up grant' : ''}.
          </div>
        )}

        <PermissionGate
          capability={spec?.capability_id ?? 'kyber.command.dispatch'}
          fallback={
            <div className="text-[11px] text-text-muted font-mono">
              You do not hold {spec?.capability_id ?? 'the capability'} for this command
              type, so the request control is hidden. The backend would refuse it.
            </div>
          }
        >
          <Button size="sm" disabled={!ready || request.isLoading} onClick={submit}>
            Request command
          </Button>
        </PermissionGate>

        {request.error !== null && (
          <RefusalNotice title="Command request refused" message={request.error} />
        )}
        {request.data !== null && (
          <div className="text-[11px] text-text-secondary font-mono">
            Requested {request.data.command.command_id} — status{' '}
            {request.data.command.status}.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Containment ──────────────────────────────────────────────────────────────

const SCOPE_OPTIONS = [
  { value: 'global', label: 'global' },
  { value: 'environment', label: 'environment' },
  { value: 'region', label: 'region' },
  { value: 'tenant', label: 'tenant' },
  { value: 'feature', label: 'feature' },
  { value: 'connector', label: 'connector' },
  { value: 'worker', label: 'worker' },
  { value: 'model', label: 'model' },
];

/**
 * The reach of a containment switch is assessed server-side at the moment it is
 * flipped, and there is no endpoint that previews it. A global switch is the one case
 * where the reach is known in advance and certain; everything else is unknown, and
 * saying "unknown" is the only honest thing to put in front of the operator.
 */
function ContainmentReachPreview({ scope }: { readonly scope: string }) {
  if (scope === 'global') {
    return (
      <div
        role="status"
        className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger"
      >
        <div className="font-semibold font-mono">Reach before activation: platform-wide</div>
        <div className="mt-1 text-text-secondary">
          Every service, every tenant and every feature in this environment is in reach.
          That reach is certain, not estimated.
        </div>
      </div>
    );
  }
  return (
    <div
      role="status"
      className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
    >
      <div className="font-semibold font-mono">
        Reach before activation: {UNKNOWN_LABEL}
      </div>
      <div className="mt-1 text-text-secondary">
        Kyber assesses a containment blast radius when the switch is flipped, and exposes
        no endpoint that previews it. Treat this reach as unmeasured, not as small — the
        assessed radius is recorded on the switch and shown in the table once it exists.
      </div>
    </div>
  );
}

function SwitchReachCell({ radius }: { readonly radius: BlastRadius | null | undefined }) {
  if (!reachIsKnown(radius)) {
    return (
      <span className="text-warning font-mono text-[11px]">
        {UNKNOWN_LABEL}
        {reachMissingInputs(radius).length > 0
          ? ` — ${reachMissingInputs(radius).join(', ')}`
          : ''}
      </span>
    );
  }
  // The fallback used to be `(radius?.affected_services ?? []).length` — a switch whose
  // assessment reported no service list at all rendered as "0 service(s)", which is a
  // containment switch claiming it reaches nothing.
  const services = radius?.affected_services;
  if (radius?.summary) {
    return (
      <span className="text-[11px] font-mono text-text-secondary">{radius.summary}</span>
    );
  }
  if (services === null || services === undefined) {
    return (
      <span className="text-warning font-mono text-[11px]">
        Assessed, but no service reach was reported — {UNKNOWN_LABEL}, not none
      </span>
    );
  }
  return (
    <span className="text-[11px] font-mono text-text-secondary">
      {services.length} service(s)
    </span>
  );
}

function ContainmentCard() {
  const { data, loading, error, refresh } = useContainment();
  const [scope, setScope] = useState('tenant');
  const [control, setControl] = useState('');
  const [target, setTarget] = useState('');
  const [reason, setReason] = useState('');
  const [safeModeReason, setSafeModeReason] = useState('');

  const activate = useMutation<ContainmentInput, ContainmentSwitch>({
    mutationFn: activateContainment,
    onSuccess: refresh,
  });
  const deactivate = useMutation<ContainmentInput, unknown>({
    mutationFn: deactivateContainment,
    onSuccess: refresh,
  });
  const safeModeOn = useMutation<string, SafeModeResult>({
    mutationFn: activateSafeMode,
    onSuccess: refresh,
  });
  const safeModeOff = useMutation<string, SafeModeResult>({
    mutationFn: releaseSafeMode,
    onSuccess: refresh,
  });

  const containmentError =
    activate.error ?? deactivate.error ?? safeModeOn.error ?? safeModeOff.error;
  const ready = control.trim() !== '' && reason.trim() !== '';

  function payload(): ContainmentInput {
    return {
      scope,
      control: control.trim(),
      reason: reason.trim(),
      ...(target.trim() === '' ? {} : { target: target.trim() }),
    };
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Containment switches</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && data === null ? (
          <LoadingState lines={3} />
        ) : error !== null ? (
          <ErrorState title="Unable to load containment state" message={error} onRetry={refresh} />
        ) : data === null ? (
          <EmptyState title="No containment state returned" />
        ) : (
          <ContainmentBody state={data} />
        )}

        <div className="space-y-2 border-t border-border-default pt-3">
          <div className="text-xs font-mono text-text-primary">Flip a scoped switch</div>
          <div className="flex flex-wrap items-end gap-2">
            <Select label="Scope" options={SCOPE_OPTIONS} value={scope} onChange={setScope} />
            <label className="text-[11px] text-text-muted font-mono">
              Control (required)
              <Input
                value={control}
                onChange={event => setControl(event.target.value)}
                placeholder="e.g. tenant_ingestion"
              />
            </label>
            <label className="text-[11px] text-text-muted font-mono">
              Target
              <Input
                value={target}
                onChange={event => setTarget(event.target.value)}
                placeholder="scope target"
              />
            </label>
            <label className="text-[11px] text-text-muted font-mono">
              Reason (required)
              <Input
                value={reason}
                onChange={event => setReason(event.target.value)}
                placeholder="why this is being contained"
              />
            </label>
          </div>

          <ContainmentReachPreview scope={scope} />

          <div className="flex flex-wrap items-center gap-2">
            <PermissionGate capability={PAUSE_CAPABILITY}>
              <Button
                size="sm"
                variant="danger"
                disabled={!ready || activate.isLoading}
                onClick={() => void activate.mutate(payload())}
              >
                Activate switch
              </Button>
            </PermissionGate>
            <PermissionGate capability={PAUSE_CAPABILITY}>
              <Button
                size="sm"
                variant="secondary"
                disabled={!ready || deactivate.isLoading}
                onClick={() => void deactivate.mutate(payload())}
              >
                Deactivate switch
              </Button>
            </PermissionGate>
          </div>
        </div>

        <div className="space-y-2 border-t border-border-default pt-3">
          <div className="text-xs font-mono text-text-primary">Safe mode</div>
          <div
            role="status"
            className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
          >
            <div className="font-semibold font-mono">
              Safe mode does NOT stop ingestion
            </div>
            <div className="mt-1 text-text-secondary">
              Inbound events keep being accepted. Losing them during an incident turns a
              recoverable outage into permanent data loss, so safe mode stops mutations,
              automation, reward distribution and mirror writes and leaves ingestion
              running. A quiet pipeline after this is not evidence that ingestion stopped.
              Preserved:{' '}
              {(data?.preserved_in_safe_mode ?? []).length === 0
                ? UNKNOWN_LABEL
                : (data?.preserved_in_safe_mode ?? []).join(', ')}
              .
            </div>
          </div>
          <label className="block text-[11px] text-text-muted font-mono">
            Safe mode reason (required)
            <Input
              value={safeModeReason}
              onChange={event => setSafeModeReason(event.target.value)}
              placeholder="why the platform is being frozen"
            />
          </label>
          <PermissionGate
            capability={KILL_SWITCH_CAPABILITY}
            fallback={
              <div className="text-[11px] text-text-muted font-mono">
                Safe mode requires {KILL_SWITCH_CAPABILITY}, which you do not hold.
              </div>
            }
          >
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="danger"
                disabled={safeModeReason.trim() === '' || safeModeOn.isLoading}
                onClick={() => void safeModeOn.mutate(safeModeReason.trim())}
              >
                Activate safe mode
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={safeModeOff.isLoading}
                onClick={() => void safeModeOff.mutate(safeModeReason.trim())}
              >
                Release safe mode
              </Button>
            </div>
          </PermissionGate>
        </div>

        {containmentError !== null && containmentError !== undefined && (
          <RefusalNotice title="Containment change refused" message={containmentError} />
        )}
      </CardContent>
    </Card>
  );
}

function ContainmentBody({ state }: { readonly state: ContainmentState }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <StatusIndicator
          status={state.safe_mode ? 'degraded' : 'healthy'}
          label={state.safe_mode ? 'Safe mode ACTIVE' : 'Safe mode inactive'}
        />
        <span className="text-[11px] text-text-muted font-mono">
          active switches <CountText value={state.active_count} />
        </span>
      </div>

      {state.switches.length === 0 ? (
        <EmptyState title="No containment switch is active" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px] font-mono border-collapse">
            <thead>
              <tr className="border-b border-border-default text-text-muted">
                <th className="py-1 px-2 text-left">Scope</th>
                <th className="py-1 px-2 text-left">Target</th>
                <th className="py-1 px-2 text-left">Control</th>
                <th className="py-1 px-2 text-left">Reason</th>
                <th className="py-1 px-2 text-left">Activated by</th>
                <th className="py-1 px-2 text-left">Assessed reach</th>
              </tr>
            </thead>
            <tbody>
              {state.switches.map(entry => (
                <tr key={entry.switch_id} className="border-b border-border-subtle">
                  <td className="py-1 px-2 text-text-primary">{entry.scope}</td>
                  <td className="py-1 px-2 text-text-secondary">{entry.target ?? '—'}</td>
                  <td className="py-1 px-2 text-text-primary">{entry.control}</td>
                  <td className="py-1 px-2 text-text-secondary">{entry.reason ?? '—'}</td>
                  <td className="py-1 px-2 text-text-secondary">
                    {entry.activated_by ?? UNKNOWN_LABEL}
                  </td>
                  <td className="py-1 px-2">
                    <SwitchReachCell radius={entry.blast_radius} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

function ForbiddenPanel({ capabilities }: { readonly capabilities: readonly string[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Not authorized for the command plane</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div role="status" className="text-xs text-warning font-mono">
          Reaching this page is not a grant.
        </div>
        <p className="text-xs text-text-secondary">
          The backend did not include any of the capabilities this console needs in the
          grant it issued for your session, so nothing is read and nothing is offered.
          Required (any of): {capabilities.join(', ')}.
        </p>
      </CardContent>
    </Card>
  );
}

export function KyberCommandsPage() {
  const perms = useCapabilities();
  const commandTypes = useCommandTypes();

  const canReadCommands = perms.has(AUDIT_READ);
  const canReadContainment = perms.has(INCIDENT_READ);

  if (perms.isLoading) {
    return (
      <PageWrapper title="Commands & containment" subtitle={PAGE_SUBTITLE}>
        <LoadingState lines={4} />
      </PageWrapper>
    );
  }

  if (!canReadCommands && !canReadContainment) {
    return (
      <PageWrapper title="Commands & containment" subtitle={PAGE_SUBTITLE}>
        <ForbiddenPanel capabilities={[AUDIT_READ, INCIDENT_READ]} />
      </PageWrapper>
    );
  }

  return (
    <PageWrapper title="Commands & containment" subtitle={PAGE_SUBTITLE}>
      <Tabs defaultValue="commands">
        <TabsList>
          <TabsTrigger value="commands">Commands</TabsTrigger>
          <TabsTrigger value="catalog">Command types</TabsTrigger>
          <TabsTrigger value="containment">Containment</TabsTrigger>
        </TabsList>

        <TabsContent value="commands">
          <div className="space-y-4">
            {canReadCommands ? (
              <CommandQueueCard />
            ) : (
              <ForbiddenPanel capabilities={[AUDIT_READ]} />
            )}
            {canReadCommands && <CommandReceiptsPanel />}
            <RequestCommandCard specs={commandTypes.data?.types ?? []} />
            <OperatorContinuationPanel />
            <ContinuationCreateButton
              canCreate={canReadCommands}
              reason="Operator-initiated continuation from the Commands & containment console"
            />
          </div>
        </TabsContent>

        <TabsContent value="catalog">
          <CommandTypesCard />
        </TabsContent>

        <TabsContent value="containment">
          {canReadContainment ? (
            <ContainmentCard />
          ) : (
            <ForbiddenPanel capabilities={[INCIDENT_READ]} />
          )}
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
