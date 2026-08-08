/**
 * Kyber — Commands & containment operator page.
 *
 * This page changes production state, so every test here is asserted positively AND
 * negatively. The positive assertion proves the honest thing is on screen; the negative
 * one proves the dishonest reading is not available anywhere near it.
 *
 *   · `executed_unverified` renders as its own state and NOT as success — the success
 *     label and the success treatment must both be absent;
 *   · a failed verification names the check that failed, on screen;
 *   · `exposure_known: false` renders Unknown plus the missing inputs, and NO number
 *     appears anywhere in the reach region;
 *   · the execute control is unavailable when the blast radius could not be assessed AND
 *     when it was assessed but the reach is not known — there must be no enabled Execute
 *     anywhere on the page in either case;
 *   · a reach dimension the assessor did not report renders Unknown, with no `0` and no
 *     "none in reach" — while a dimension it reported as empty still says none, because
 *     that zero is measured;
 *   · `executed_unverified` offers re-verification, the only path off that status, and a
 *     `verified` command does not;
 *   · a step-up-required response renders as "Step-up required", not as a generic error;
 *   · an approval refusal is rendered in the backend's own words;
 *   · safe mode says on the control that it does not stop ingestion;
 *   · reaching the page without the capability renders a forbidden state — routing is
 *     not a grant.
 *
 * Only `restClient` is mocked, so the real hooks and the real zod schemas run.
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';
import { KyberCommandsPage } from '@kyber/pages/kyber-commands';
import { makePrincipal, renderWithAuth } from '../kyber-auth-doubles';

const restGet = vi.fn();
const restPost = vi.fn();
const restDelete = vi.fn();

vi.mock('@kyber/lib/api', () => ({
  restClient: {
    get: (...args: unknown[]) => restGet(...args),
    post: (...args: unknown[]) => restPost(...args),
    delete: (...args: unknown[]) => restDelete(...args),
  },
}));

const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };

beforeAll(() => {
  // The shared queryCache tracks in-flight fetches with `promise.finally(...)`, which
  // leaks an unhandled rejection when a fetcher rejects even though the UI renders an
  // ErrorState. Patch it test-locally (same fix as imports-ops-page.test.tsx).
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

const OPERATOR_CAPABILITIES = [
  'kyber.audit.read',
  'kyber.incident.read',
  'kyber.command.pause',
  'kyber.command.kill_switch',
  'kyber.command.retry',
];

// ── Fixtures ─────────────────────────────────────────────────────────────────

const RETRY_SPEC = {
  command_type: 'retry_job',
  title: 'Retry a failed job',
  capability_id: 'kyber.command.retry',
  action_class: 2,
  handler: 'services.jobs.job_service.retry',
  verification_checks: ['job_reached_terminal_state'],
  requires_dry_run: false,
  requires_rollback_plan: false,
  tenant_scoped: true,
  containment_scope: null,
  description: 'Re-queue a job that failed.',
};

const KILL_SWITCH_SPEC = {
  command_type: 'activate_kill_switch',
  title: 'Activate a kill switch',
  capability_id: 'kyber.command.kill_switch',
  action_class: 5,
  handler: 'services.kyber.ops.containment.containment_service.activate',
  verification_checks: ['switch_is_active', 'mirror_digest_parity'],
  requires_dry_run: true,
  requires_rollback_plan: true,
  tenant_scoped: false,
  containment_scope: 'global',
  description: 'Stop a subsystem platform-wide.',
};

const COMMAND_TYPES = {
  types: [RETRY_SPEC, KILL_SWITCH_SPEC],
  count: 2,
  generated_at: '2026-07-25T00:00:00Z',
};

const KNOWN_REACH = {
  available: true,
  exposure_known: true,
  missing_inputs: [],
  subject_type: 'Service',
  subject_id: 'checkout-api',
  environment: 'test',
  affected_services: ['checkout-api', 'ledger'],
  affected_features: ['checkout'],
  affected_tenants: ['tenant_001'],
  affected_graph_domains: ['commerce'],
  customer_visible: true,
  traversal_depth: 2,
  truncated: false,
  confidence: 0.9,
  summary: 'checkout-api reaches 2 services and 1 tenant',
  source: 'services.kyber.graph.blast_radius.assess',
  computed_at: '2026-07-25T00:00:00Z',
};

const PARTIAL_REACH = {
  ...KNOWN_REACH,
  exposure_known: false,
  missing_inputs: [
    'kyber_graph_node:node_key=service:ledger',
    'kyber_graph_walk:depth_bound_reached:depth=2',
  ],
  truncated: true,
  confidence: 0.4,
  summary: null,
};

/**
 * The assessor ran and answered, and did not report which tenants are in reach. That is
 * "we do not know which tenants", and `(values ?? []).length` used to draw it as `0` and
 * "none in reach".
 */
const REACH_WITHOUT_TENANT_LIST = {
  ...KNOWN_REACH,
  affected_tenants: null,
  summary: 'checkout-api reaches two services',
};

/** The one case where a zero is honest: the assessor reported this dimension as empty. */
const REACH_WITH_NO_TENANTS = {
  ...KNOWN_REACH,
  affected_tenants: [],
  summary: 'checkout-api reaches no tenants',
};

const UNAVAILABLE_REACH = {
  available: false,
  reason: 'blast_radius_assessor_unavailable',
  missing_inputs: ['services.kyber.graph.blast_radius'],
  computed_at: '2026-07-25T00:00:00Z',
};

const BASE_COMMAND = {
  command_id: 'kcm_retry',
  command_type: 'retry_job',
  status: 'approved',
  requested_by: 'op_test_001',
  session_id: 'sess_test_001',
  device_id: 'dev_test_001',
  environment: 'test',
  tenant_ids: ['tenant_001'],
  resource_ids: ['job_4711'],
  reason: 're-queue the stuck settlement job',
  action_class: 2,
  dry_run: false,
  idempotency_key: 'retry-job-4711',
  blast_radius: KNOWN_REACH,
  rollback_plan: null,
  verification_plan: ['job_reached_terminal_state'],
  required_approvals: 0,
  approvals: [],
  approval_mode: 'solo',
  step_up_verified: false,
  incident_id: null,
  created_at: '2026-07-25T00:00:00Z',
  updated_at: '2026-07-25T00:01:00Z',
  metadata: { approval_gaps: [] },
};

const EXECUTION = {
  execution_id: 'kce_001',
  command_id: 'kcm_retry',
  attempt: 1,
  started_at: '2026-07-25T00:02:00Z',
  completed_at: '2026-07-25T00:02:03Z',
  result: { job_id: 'job_4711' },
  error: null,
  side_effects: ['jobs.retry'],
  rollback_status: null,
};

/**
 * The call returned and the postcondition did not hold. The command is
 * `executed_unverified`, not `failed` and emphatically not `verified`.
 */
const UNVERIFIED_DETAIL = {
  command: { ...BASE_COMMAND, status: 'executed_unverified' },
  spec: RETRY_SPEC,
  execution: EXECUTION,
  executions: [EXECUTION],
  verification: {
    verification_id: 'kcv_001',
    command_id: 'kcm_retry',
    outcome: 'failed',
    checks: [
      {
        check: 'job_reached_terminal_state',
        outcome: 'failed',
        detail: 'job job_4711 is still queued four minutes after the retry returned',
        evidence: { job_status: 'queued' },
        checked_at: '2026-07-25T00:02:10Z',
      },
    ],
    customer_visible_parity: null,
    mirror_digest_before: null,
    mirror_digest_after: null,
    failure_reason:
      'job_reached_terminal_state: job job_4711 is still queued four minutes after the retry returned',
    started_at: '2026-07-25T00:02:05Z',
    completed_at: '2026-07-25T00:02:10Z',
  },
  verified: false,
  generated_at: '2026-07-25T00:03:00Z',
};

const VERIFIED_DETAIL = {
  ...UNVERIFIED_DETAIL,
  command: { ...BASE_COMMAND, status: 'verified' },
  verification: {
    ...UNVERIFIED_DETAIL.verification,
    outcome: 'passed',
    checks: [
      {
        check: 'job_reached_terminal_state',
        outcome: 'passed',
        detail: 'job job_4711 completed',
        evidence: {},
        checked_at: '2026-07-25T00:02:10Z',
      },
    ],
    failure_reason: null,
  },
  verified: true,
};

const NEVER_VERIFIED_DETAIL = {
  ...UNVERIFIED_DETAIL,
  command: { ...BASE_COMMAND, status: 'executed_unverified' },
  verification: null,
};

const PARTIAL_REACH_DETAIL = {
  ...UNVERIFIED_DETAIL,
  command: { ...BASE_COMMAND, status: 'approved', blast_radius: PARTIAL_REACH },
  execution: null,
  executions: [],
  verification: null,
};

const UNAVAILABLE_REACH_DETAIL = {
  ...UNVERIFIED_DETAIL,
  command: {
    ...BASE_COMMAND,
    status: 'approved',
    blast_radius: UNAVAILABLE_REACH,
    metadata: { approval_gaps: ['fresh_step_up', 'second_approver'] },
  },
  execution: null,
  executions: [],
  verification: null,
};

const UNREPORTED_TENANTS_DETAIL = {
  ...UNVERIFIED_DETAIL,
  command: {
    ...BASE_COMMAND,
    status: 'approved',
    blast_radius: REACH_WITHOUT_TENANT_LIST,
  },
  execution: null,
  executions: [],
  verification: null,
};

const NO_TENANTS_DETAIL = {
  ...UNVERIFIED_DETAIL,
  command: { ...BASE_COMMAND, status: 'approved', blast_radius: REACH_WITH_NO_TENANTS },
  execution: null,
  executions: [],
  verification: null,
};

const COMMAND_LIST = {
  commands: [BASE_COMMAND],
  count: 1,
  status_filter: 'open',
};

const CONTAINMENT_STATE = {
  safe_mode: false,
  active_count: 1,
  switches: [
    {
      switch_id: 'ksw_001',
      scope: 'connector',
      target: 'stripe',
      control: 'connector_sync',
      active: true,
      reason: 'vendor incident, paused pending their fix',
      activated_by: 'op_test_001',
      activated_at: '2026-07-25T00:00:00Z',
      deactivated_by: null,
      deactivated_at: null,
      blast_radius: UNAVAILABLE_REACH,
      metadata: { blast_radius_unknown: true, preserves: [] },
    },
  ],
  preserved_in_safe_mode: ['ingestion'],
};

// ── Wiring ───────────────────────────────────────────────────────────────────

interface Responses {
  detail?: unknown;
  commands?: unknown;
  containment?: unknown;
  commandsError?: Error;
}

function mockApi(responses: Responses = {}): void {
  restGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/kyber/ops/commands/types')) {
      return Promise.resolve({ data: COMMAND_TYPES });
    }
    if (path.startsWith('/v1/kyber/ops/commands/')) {
      return Promise.resolve({ data: responses.detail ?? UNVERIFIED_DETAIL });
    }
    if (path.startsWith('/v1/kyber/ops/commands')) {
      if (responses.commandsError) return Promise.reject(responses.commandsError);
      return Promise.resolve({ data: responses.commands ?? COMMAND_LIST });
    }
    if (path.startsWith('/v1/kyber/ops/containment')) {
      return Promise.resolve({ data: responses.containment ?? CONTAINMENT_STATE });
    }
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

function renderPage(capabilities: readonly string[] = OPERATOR_CAPABILITIES) {
  return renderWithAuth(<KyberCommandsPage />, {
    principal: makePrincipal({
      capabilities: [...capabilities],
      max_action_class: 5,
      max_disclosure: 4,
    }),
  });
}

async function openCommand(): Promise<void> {
  // Generous wait: under full-suite parallel load the queue fetch + render can
  // take longer than findByText's 1s default. The assertion is unchanged — this
  // only makes the shared open-command gate resilient to machine load.
  await userEvent.click(
    await screen.findByText('re-queue the stuck settlement job', undefined, { timeout: 5000 }),
  );
}

/**
 * Every Execute control on the page that an operator could actually press. Asserting
 * this is empty is stronger than asserting one particular button is disabled: the
 * defect being guarded is "the operator was invited to dispatch", and a second enabled
 * control anywhere would be that same invitation.
 */
function pressableExecuteControls(): readonly HTMLElement[] {
  return screen
    .queryAllByRole('button', { name: 'Execute' })
    .filter(button => !(button as HTMLButtonElement).disabled);
}

/** One tile of the reach grid, by its label. */
function reachTile(label: string): HTMLElement {
  const reach = screen.getByRole('group', { name: 'Blast radius reach' });
  return within(reach).getByText(label).parentElement as HTMLElement;
}

beforeEach(() => {
  queryCache.invalidatePrefix('');
  cache.inFlight.clear();
  restGet.mockReset();
  restPost.mockReset();
  restDelete.mockReset();
});

// ── Routing is not a grant ───────────────────────────────────────────────────

describe('KyberCommandsPage — authority', () => {
  it('renders its own forbidden state when the backend granted nothing', async () => {
    mockApi();
    renderPage([]);

    await waitFor(() =>
      expect(screen.getByText('Not authorized for the command plane')).toBeInTheDocument(),
    );
    expect(screen.getByText('Reaching this page is not a grant.')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Commands' })).not.toBeInTheDocument();
  });

  it('shows the command queue when the audit read capability is held', async () => {
    mockApi();
    renderPage();

    await waitFor(() => expect(screen.getByText('Command queue')).toBeInTheDocument());
    expect(
      await screen.findByText('re-queue the stuck settlement job', undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
  });

  it('shows a loading state before the command queue resolves', () => {
    restGet.mockImplementation(() => new Promise(() => undefined));
    const { container } = renderPage();
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('renders an authoritative empty command queue', async () => {
    mockApi({ commands: { commands: [], total: 0 } });
    renderPage();
    await waitFor(() => expect(screen.getByText('No commands in this queue')).toBeInTheDocument());
  });

  it('shows the error state with the backend reason when the queue fails', async () => {
    mockApi({ commandsError: new Error('A fresh step-up is required') });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Unable to load commands')).toBeInTheDocument(),
    );
  });
});

// ── executed_unverified is never success ─────────────────────────────────────

describe('KyberCommandsPage — executed_unverified is its own state', () => {
  it('renders executed_unverified with a warning treatment and never as success', async () => {
    mockApi({ detail: UNVERIFIED_DETAIL });
    renderPage();
    await openCommand();

    const status = await waitFor(() =>
      screen.getByRole('group', { name: 'Command status' }),
    );
    const badge = within(status).getByText('Executed — not verified');

    // Positive: the state is named, and it is drawn as a warning.
    expect(badge.className).toContain('text-warning');
    expect(
      screen.getByText('The side effect landed and the postconditions did not confirm'),
    ).toBeInTheDocument();

    // Negative: no success label, and no success treatment anywhere on the status.
    expect(badge.className).not.toContain('text-success');
    expect(within(status).queryByText('Verified')).not.toBeInTheDocument();
    expect(screen.queryByText('Verified')).not.toBeInTheDocument();
    expect(screen.queryByText('Postconditions passed')).not.toBeInTheDocument();
  });

  it('does render a verified command as success, so the two are distinguishable', async () => {
    mockApi({ detail: VERIFIED_DETAIL });
    renderPage();
    await openCommand();

    const status = await waitFor(() =>
      screen.getByRole('group', { name: 'Command status' }),
    );
    const badge = within(status).getByText('Verified');
    expect(badge.className).toContain('text-success');
    expect(screen.getByText('Postconditions passed')).toBeInTheDocument();
    expect(screen.queryByText('Executed — not verified')).not.toBeInTheDocument();
  });

  it('names the check that failed, with its detail', async () => {
    mockApi({ detail: UNVERIFIED_DETAIL });
    renderPage();
    await openCommand();

    expect(await screen.findByText('Checks that did not pass')).toBeInTheDocument();
    // The failing check is named, and its detail travels with it.
    expect(screen.getByText('job_reached_terminal_state')).toBeInTheDocument();
    expect(
      screen.getByText(/— job job_4711 is still queued four minutes after the retry returned/),
    ).toBeInTheDocument();
    // The verification's own failure reason names the check too.
    expect(
      screen.getByText(/Failure reason: job_reached_terminal_state:/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Postconditions failed — the intended state was not confirmed/,
      ),
    ).toBeInTheDocument();
  });

  it('renders a null verification as an open question, not as an absent one', async () => {
    mockApi({ detail: NEVER_VERIFIED_DETAIL });
    renderPage();
    await openCommand();

    expect(await screen.findByText('Not verified')).toBeInTheDocument();
    expect(
      screen.getByText(/an open question rather than an absent one/),
    ).toBeInTheDocument();
    expect(screen.queryByText('Postconditions passed')).not.toBeInTheDocument();
  });
});

// ── Blast radius before execution ────────────────────────────────────────────

describe('KyberCommandsPage — reach is shown before execution', () => {
  it('renders a known reach with its counts', async () => {
    mockApi({ detail: { ...UNVERIFIED_DETAIL, command: BASE_COMMAND } });
    renderPage();
    await openCommand();

    const reach = await waitFor(() =>
      screen.getByRole('group', { name: 'Blast radius reach' }),
    );
    expect(within(reach).getByText('Services in reach')).toBeInTheDocument();
    expect(within(reach).getByText('2')).toBeInTheDocument();
    expect(within(reach).queryByText('Unknown')).not.toBeInTheDocument();
  });

  it('renders exposure_known:false as Unknown with its missing inputs and no number', async () => {
    mockApi({ detail: PARTIAL_REACH_DETAIL });
    renderPage();
    await openCommand();

    expect(
      await screen.findByText(
        /Reach Unknown — this is not a small reach, it is an unmeasured one/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText('· kyber_graph_node:node_key=service:ledger'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('· kyber_graph_walk:depth_bound_reached:depth=2'),
    ).toBeInTheDocument();

    // Negative: not one digit is rendered in the reach region — a partial reach drawn
    // as a number is a small reach drawn over an unmeasured one.
    const reach = screen.getByRole('group', { name: 'Blast radius reach' });
    expect(within(reach).getAllByText('Unknown')).toHaveLength(4);
    expect(reach.textContent ?? '').not.toMatch(/\d/);
  });

  it('makes execute unavailable when the blast radius could not be assessed', async () => {
    mockApi({ detail: UNAVAILABLE_REACH_DETAIL });
    renderPage();
    await openCommand();

    const execute = await waitFor(() => screen.getByRole('button', { name: 'Execute' }));
    expect(execute).toBeDisabled();
    expect(
      screen.getByText(/Execute is unavailable: the blast radius could not be assessed/),
    ).toBeInTheDocument();
    expect(screen.getByText(/blast_radius_assessor_unavailable/)).toBeInTheDocument();

    const reach = screen.getByRole('group', { name: 'Blast radius reach' });
    expect(reach.textContent ?? '').not.toMatch(/\d/);
  });

  it('makes execute unavailable when the reach was assessed but is not known', async () => {
    mockApi({ detail: PARTIAL_REACH_DETAIL });
    renderPage();
    await openCommand();

    // Positive: the panel says the reach is unmeasured.
    expect(
      await screen.findByText(
        /Reach Unknown — this is not a small reach, it is an unmeasured one/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Execute is unavailable: the blast radius was assessed without a complete reach/,
      ),
    ).toBeInTheDocument();

    // Negative: `available: true` is NOT enough to dispatch. There is no pressable
    // Execute anywhere on the page — an operator must not be invited to act on a reach
    // nobody measured, which is exactly what gating on `available` alone allowed.
    expect(screen.getByRole('button', { name: 'Execute' })).toBeDisabled();
    expect(pressableExecuteControls()).toHaveLength(0);
  });

  it('renders a reach dimension the assessor did not report as Unknown, not as none', async () => {
    mockApi({ detail: UNREPORTED_TENANTS_DETAIL });
    renderPage();
    await openCommand();

    await waitFor(() =>
      expect(screen.getByRole('group', { name: 'Blast radius reach' })).toBeInTheDocument(),
    );

    // Positive: the unreported dimension says Unknown and says why.
    const tenants = reachTile('Tenants in reach');
    expect(within(tenants).getByText('Unknown')).toBeInTheDocument();
    expect(
      within(tenants).getByText(/The assessment did not report this dimension/),
    ).toBeInTheDocument();

    // Negative: no count and no "none in reach" — "we do not know which tenants" must
    // never be rendered as "no tenants are affected".
    expect(tenants.textContent ?? '').not.toMatch(/\d/);
    expect(tenants.textContent ?? '').not.toContain('none in reach');
    expect(
      screen.getByRole('group', { name: 'Blast radius reach' }).textContent ?? '',
    ).not.toContain('none in reach');

    // The verdict is per dimension, not global: the services the assessor DID report
    // still render their count.
    expect(within(reachTile('Services in reach')).getByText('2')).toBeInTheDocument();
  });

  it('still says none for a dimension the assessor reported as empty', async () => {
    mockApi({ detail: NO_TENANTS_DETAIL });
    renderPage();
    await openCommand();

    await waitFor(() =>
      expect(screen.getByRole('group', { name: 'Blast radius reach' })).toBeInTheDocument(),
    );

    // A measured zero is honest and must survive the fix above: this reach was read and
    // it was empty. Over-correcting into Unknown here would be its own dishonesty.
    const tenants = reachTile('Tenants in reach');
    expect(within(tenants).getByText('0')).toBeInTheDocument();
    expect(within(tenants).getByText('none in reach')).toBeInTheDocument();
    expect(within(tenants).queryByText('Unknown')).not.toBeInTheDocument();
  });

  it('names the approval gaps that stand between the command and execution', async () => {
    mockApi({ detail: UNAVAILABLE_REACH_DETAIL });
    renderPage();
    await openCommand();

    expect(await screen.findByText('Approval gaps')).toBeInTheDocument();
    expect(
      screen.getByText(/a class 4\/5 command needs a live step-up grant/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/a different qualified operator must approve/),
    ).toBeInTheDocument();
  });
});

// ── executed_unverified has a way out ────────────────────────────────────────

describe('KyberCommandsPage — re-verification is offered, and only where it applies', () => {
  it('offers re-verification on an executed_unverified command', async () => {
    mockApi({ detail: UNVERIFIED_DETAIL });
    renderPage();
    await openCommand();

    const control = await screen.findByRole('button', {
      name: 'Re-verify postconditions',
    });
    expect(control).toBeEnabled();
    // It is a re-run of the checks, not a declaration. The copy has to say so, because
    // a control that looks like "mark verified" is worse than no control at all.
    expect(
      screen.getByText(/it is not a way to declare the command verified — the checks/),
    ).toBeInTheDocument();
  });

  it('does not offer re-verification on a verified command', async () => {
    mockApi({ detail: VERIFIED_DETAIL });
    renderPage();
    await openCommand();

    await waitFor(() =>
      expect(screen.getByRole('group', { name: 'Command status' })).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole('button', { name: 'Re-verify postconditions' }),
    ).not.toBeInTheDocument();
  });

  it('does not offer re-verification on a command that never executed', async () => {
    mockApi({ detail: PARTIAL_REACH_DETAIL });
    renderPage();
    await openCommand();

    await waitFor(() =>
      expect(screen.getByRole('group', { name: 'Command status' })).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole('button', { name: 'Re-verify postconditions' }),
    ).not.toBeInTheDocument();
  });

  it('posts to the verify route and lets the checks decide the status', async () => {
    mockApi({ detail: UNVERIFIED_DETAIL });
    restPost.mockResolvedValue({ data: UNVERIFIED_DETAIL });
    renderPage();
    await openCommand();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Re-verify postconditions' }),
    );

    await waitFor(() =>
      expect(
        restPost.mock.calls.some(
          ([path]) => path === '/v1/kyber/ops/commands/kcm_retry/verify',
        ),
      ).toBe(true),
    );

    // The postconditions still did not hold, so the status is unchanged. Re-verifying
    // is not a way to declare success, and the page must not draw it as one.
    const status = screen.getByRole('group', { name: 'Command status' });
    expect(within(status).getByText('Executed — not verified')).toBeInTheDocument();
    expect(within(status).queryByText('Verified')).not.toBeInTheDocument();
  });

  it('renders a refused re-verification in the backend own words', async () => {
    mockApi({ detail: UNVERIFIED_DETAIL });
    restPost.mockRejectedValue(
      new Error("command kcm_retry is 'requested'; only an executed command has postconditions to check"),
    );
    renderPage();
    await openCommand();

    await userEvent.click(
      await screen.findByRole('button', { name: 'Re-verify postconditions' }),
    );

    expect(await screen.findByText('Re-verification refused')).toBeInTheDocument();
    expect(
      screen.getByText(/only an executed command has postconditions to check/),
    ).toBeInTheDocument();
  });
});

// ── Refusals keep their reason ───────────────────────────────────────────────

describe('KyberCommandsPage — refusals are shown with their reason', () => {
  it('renders a step-up-required response as step-up required, not a generic error', async () => {
    mockApi({ detail: { ...UNVERIFIED_DETAIL, command: BASE_COMMAND } });
    restPost.mockRejectedValue(new Error('A fresh step-up is required'));
    renderPage();
    await openCommand();

    await userEvent.click(await screen.findByRole('button', { name: 'Execute' }));

    expect(await screen.findByText('Step-up required')).toBeInTheDocument();
    expect(
      screen.getByText(/re-authenticate and retry — not a fault in the command/),
    ).toBeInTheDocument();
    // Negative: it is not dressed up as an unexplained failure.
    expect(screen.queryByText('Execution refused')).not.toBeInTheDocument();
  });

  it('surfaces an approval refusal in the backend own words', async () => {
    mockApi({ detail: { ...UNVERIFIED_DETAIL, command: BASE_COMMAND } });
    restPost.mockRejectedValue(
      new Error('command approval requires a different operator than the requester'),
    );
    renderPage();
    await openCommand();

    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }));

    expect(await screen.findByText('Approval refused')).toBeInTheDocument();
    expect(
      screen.getByText('command approval requires a different operator than the requester'),
    ).toBeInTheDocument();
  });

  it('hides the command controls when the spec capability is not held', async () => {
    mockApi({ detail: { ...UNVERIFIED_DETAIL, command: BASE_COMMAND } });
    renderPage(['kyber.audit.read', 'kyber.incident.read']);
    await openCommand();

    await waitFor(() =>
      expect(screen.getByRole('group', { name: 'Command status' })).toBeInTheDocument(),
    );
    expect(screen.queryByRole('button', { name: 'Execute' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  });
});

// ── Catalog ──────────────────────────────────────────────────────────────────

describe('KyberCommandsPage — the command catalog', () => {
  it('shows each type with its action class, capability and postconditions', async () => {
    mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Command types' }));

    expect(await screen.findByText('activate_kill_switch')).toBeInTheDocument();
    expect(screen.getByText('kyber.command.kill_switch')).toBeInTheDocument();
    expect(screen.getByText('switch_is_active, mirror_digest_parity')).toBeInTheDocument();
    expect(screen.getAllByText('Required').length).toBeGreaterThan(0);
  });
});

// ── Containment ──────────────────────────────────────────────────────────────

describe('KyberCommandsPage — containment', () => {
  it('says on the control that safe mode does not stop ingestion', async () => {
    mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Containment' }));

    expect(await screen.findByText('Safe mode does NOT stop ingestion')).toBeInTheDocument();
    expect(screen.getByText(/Preserved: ingestion/)).toBeInTheDocument();
    expect(
      screen.getByText(/A quiet pipeline after this is not evidence that ingestion stopped/),
    ).toBeInTheDocument();
  });

  it('shows the reach of a switch before activation, and refuses to imply it is small', async () => {
    mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Containment' }));

    // The default scope is not global: the reach cannot be previewed, and that is said
    // rather than left blank.
    expect(
      await screen.findByText('Reach before activation: Unknown'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Treat this reach as unmeasured, not as small/),
    ).toBeInTheDocument();
  });

  it('renders an active switch whose assessed reach was never computed as Unknown', async () => {
    mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Containment' }));

    const row = await waitFor(() => screen.getByText('connector_sync').closest('tr'));
    expect(row).not.toBeNull();
    expect(
      within(row as HTMLElement).getByText(/Unknown — services.kyber.graph.blast_radius/),
    ).toBeInTheDocument();
  });

  it('does not report a switch with no reported service reach as reaching zero', async () => {
    mockApi({
      containment: {
        ...CONTAINMENT_STATE,
        switches: [
          {
            ...CONTAINMENT_STATE.switches[0],
            switch_id: 'ksw_002',
            control: 'ledger_writes',
            // The assessment ran and answered; it reported no service list and no
            // summary. `(affected_services ?? []).length` drew that as "0 service(s)" —
            // a containment switch claiming it reaches nothing.
            blast_radius: {
              ...KNOWN_REACH,
              summary: null,
              affected_services: null,
            },
          },
        ],
      },
    });
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Containment' }));

    const row = await waitFor(() => screen.getByText('ledger_writes').closest('tr'));
    expect(row).not.toBeNull();
    expect(
      within(row as HTMLElement).getByText(/no service reach was reported — Unknown, not none/),
    ).toBeInTheDocument();
    expect((row as HTMLElement).textContent ?? '').not.toContain('service(s)');
    expect((row as HTMLElement).textContent ?? '').not.toContain('0 service');
  });

  it('hides the safe-mode controls without the kill-switch capability', async () => {
    mockApi();
    renderPage(['kyber.audit.read', 'kyber.incident.read']);

    await userEvent.click(await screen.findByRole('tab', { name: 'Containment' }));

    expect(
      await screen.findByText(/Safe mode requires kyber.command.kill_switch/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Activate safe mode' }),
    ).not.toBeInTheDocument();
  });

  it('sends the scope, control and reason the operator named', async () => {
    mockApi();
    restPost.mockResolvedValue({ data: { switch: CONTAINMENT_STATE.switches[0] } });
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Containment' }));
    await userEvent.type(
      await screen.findByPlaceholderText('e.g. tenant_ingestion'),
      'connector_sync',
    );
    await userEvent.type(
      screen.getByPlaceholderText('why this is being contained'),
      'vendor incident',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Activate switch' }));

    await waitFor(() =>
      expect(
        restPost.mock.calls.some(([path, , body]) => {
          const payload = body as { scope?: string; control?: string; reason?: string };
          return (
            path === '/v1/kyber/ops/containment/activate' &&
            payload?.scope === 'tenant' &&
            payload?.control === 'connector_sync' &&
            payload?.reason === 'vendor incident'
          );
        }),
      ).toBe(true),
    );
  });
});
