import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CommandPage } from '@kyber/pages/command';

const mocks = vi.hoisted(() => ({
  isFeatureEnabled: vi.fn(() => true),
  health: vi.fn(),
  runs: vi.fn(),
  stuckRuns: vi.fn(),
  briefings: vi.fn(),
  generateBriefing: vi.fn(),
  opsAlerts: vi.fn(),
  killSwitch: vi.fn(),
  status: vi.fn(),
  audit: vi.fn(),
}));

vi.mock('@kyber/lib/featureFlags', () => ({
  isFeatureEnabled: mocks.isFeatureEnabled,
  featureFlags: {},
}));

vi.mock('@kyber/lib/api', () => ({
  api: {
    agent: {
      health: mocks.health,
      runs: mocks.runs,
      stuckRuns: mocks.stuckRuns,
      briefings: mocks.briefings,
      generateBriefing: mocks.generateBriefing,
      opsAlerts: mocks.opsAlerts,
      killSwitch: mocks.killSwitch,
    },
  },
}));

vi.mock('@kyber/lib/api/endpoints', () => ({
  api: {
    agent: {
      status: mocks.status,
      audit: mocks.audit,
    },
  },
}));

const HEALTH_FIXTURE = {
  status: 'degraded',
  kill_switch: false,
  queue_depth: 12,
  worker_count: 4,
  stale_workers: 1,
  active_runs: 3,
  failed_runs: 2,
  stuck_runs: 1,
};

const RUNS_FIXTURE = {
  runs: [
    {
      run_id: 'run_001',
      tenant_id: 'tenant_001',
      objective_id: 'obj_001',
      controller: 'nous',
      queue: 'agent:runs:default',
      status: 'running',
      attempt: 1,
      created_at: '2026-07-09T11:40:00.000Z',
      updated_at: '2026-07-09T11:58:00.000Z',
      error: null,
    },
    {
      run_id: 'run_003',
      tenant_id: 'tenant_002',
      objective_id: 'obj_002',
      controller: 'intake',
      queue: 'agent:runs:priority',
      status: 'failed',
      attempt: 2,
      created_at: '2026-07-09T09:30:00.000Z',
      updated_at: '2026-07-09T09:45:00.000Z',
      error: 'worker crashed: out of memory during graph projection',
    },
    {
      run_id: 'run_004',
      tenant_id: 'tenant_001',
      objective_id: 'obj_003',
      controller: 'nous',
      queue: 'agent:runs:default',
      status: 'stale',
      attempt: 3,
      created_at: '2026-07-09T08:00:00.000Z',
      updated_at: '2026-07-09T08:20:00.000Z',
      error: 'heartbeat lost — no worker update for 45m',
    },
  ],
};

const STUCK_FIXTURE = { runs: RUNS_FIXTURE.runs.filter(r => r.status === 'stale') };

const BRIEFINGS_FIXTURE = {
  briefings: [
    {
      id: 'brief_001',
      tenant_id: 'tenant_001',
      type: 'run_complete',
      title: 'Objective obj_001 step completed',
      body: 'Catalyst finished enrichment pass: 42 entities updated.',
      created_at: '2026-07-09T10:12:30.000Z',
    },
    {
      id: 'brief_002',
      tenant_id: 'tenant_001',
      type: 'daily',
      title: 'Daily operator briefing',
      body: '3 active runs, 2 failed runs need triage, 1 stuck run awaiting recovery.',
      created_at: '2026-07-09T06:00:00.000Z',
    },
  ],
};

const ALERTS_FIXTURE = {
  alerts: [
    {
      id: 'ops_alert_001',
      severity: 'critical',
      kind: 'worker_stale',
      message: 'Worker heartbeat missing on queue agent:runs:default',
      count: 5,
      dedupe_key: 'worker_stale:agent:runs:default',
      first_seen_at: '2026-07-09T08:20:00.000Z',
      last_seen_at: '2026-07-09T11:50:00.000Z',
    },
    {
      id: 'ops_alert_002',
      severity: 'medium',
      kind: 'run_failed',
      message: 'Run run_003 failed after 2 attempts',
      count: 1,
      dedupe_key: 'run_failed:run_003',
      first_seen_at: '2026-07-09T09:45:00.000Z',
      last_seen_at: '2026-07-09T09:45:00.000Z',
    },
  ],
};

function renderPage() {
  return render(<MemoryRouter><CommandPage /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.isFeatureEnabled.mockReturnValue(true);
  mocks.health.mockResolvedValue(HEALTH_FIXTURE);
  mocks.runs.mockImplementation((params?: { status?: string }) => {
    if (params?.status) {
      return Promise.resolve({ runs: RUNS_FIXTURE.runs.filter(r => r.status === params.status) });
    }
    return Promise.resolve(RUNS_FIXTURE);
  });
  mocks.stuckRuns.mockResolvedValue(STUCK_FIXTURE);
  mocks.briefings.mockResolvedValue(BRIEFINGS_FIXTURE);
  mocks.generateBriefing.mockResolvedValue({ generated: true });
  mocks.opsAlerts.mockResolvedValue(ALERTS_FIXTURE);
  mocks.killSwitch.mockResolvedValue({ kill_switch: true, action: 'engage' });
  mocks.status.mockResolvedValue({
    active_workers: 1,
    queued_tasks: 0,
    completed_tasks: 0,
    failed_tasks: 0,
    kill_switch: false,
    workers: [{ worker_type: 'nous', status: 'active', current_task: null }],
  });
  mocks.audit.mockResolvedValue({ records: [], total: 0 });
});

describe('Command Center ops panels (enableAgentCommandCenter on)', () => {
  it('renders the worker runtime health strip with counts and the kill switch state', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('command-center-ops')).toBeInTheDocument());

    await waitFor(() => expect(screen.getByTestId('ops-metric-queue-depth')).toHaveTextContent('12'));
    expect(screen.getByText('Worker runtime health')).toBeInTheDocument();
    expect(screen.getByTestId('ops-metric-worker-count')).toHaveTextContent('4');
    expect(screen.getByTestId('ops-metric-stale-workers')).toHaveTextContent('1');
    expect(screen.getByTestId('ops-metric-active-runs')).toHaveTextContent('3');
    expect(screen.getByTestId('ops-metric-failed-runs')).toHaveTextContent('2');
    expect(screen.getByTestId('ops-metric-stuck-runs')).toHaveTextContent('1');

    // Kill switch state indicator on the strip.
    expect(screen.getByText('kill switch clear')).toBeInTheDocument();
  });

  it('renders the run history table with error display and stuck highlighting', async () => {
    renderPage();

    const staleRow = await screen.findByTestId('run-row-run_004');
    expect(staleRow).toHaveAttribute('data-stuck', 'true');
    expect(screen.getByTestId('run-row-run_001')).not.toHaveAttribute('data-stuck');

    // Failed run error is displayed.
    expect(screen.getByText('worker crashed: out of memory during graph projection')).toBeInTheDocument();

    // Stuck-runs panel lists the stale run with its error.
    expect(await screen.findByTestId('stuck-run-run_004')).toBeInTheDocument();
    expect(screen.getAllByText('heartbeat lost — no worker update for 45m').length).toBeGreaterThan(0);
  });

  it('filters the run history by status', async () => {
    renderPage();
    await screen.findByTestId('run-row-run_001');
    expect(mocks.runs).toHaveBeenNthCalledWith(1, undefined);

    await userEvent.selectOptions(screen.getByLabelText('Filter runs by status'), 'failed');

    await waitFor(() => expect(mocks.runs).toHaveBeenCalledWith({ status: 'failed' }));
    await waitFor(() => expect(screen.queryByTestId('run-row-run_004')).toBeNull());
    expect(screen.getByTestId('run-row-run_003')).toBeInTheDocument();
  });

  it('generates a briefing and refreshes the feed on success', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Daily operator briefing')).toBeInTheDocument());
    expect(screen.getByText('Objective obj_001 step completed')).toBeInTheDocument();
    expect(mocks.briefings).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: 'Generate briefing' }));

    await waitFor(() => expect(mocks.generateBriefing).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('Briefing generated')).toBeInTheDocument());
    expect(mocks.briefings).toHaveBeenCalledTimes(2);
  });

  it('shows the briefing generation error state and preserves the API message', async () => {
    mocks.generateBriefing.mockRejectedValue(new Error('catalyst unavailable'));
    renderPage();
    await waitFor(() => expect(screen.getByText('Operator briefings')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'Generate briefing' }));

    await waitFor(() =>
      expect(screen.getByText('Briefing generation failed: catalyst unavailable')).toBeInTheDocument(),
    );
    expect(mocks.briefings).toHaveBeenCalledTimes(1);
  });

  it('renders ops alerts with severity badges and compressed count display', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Ops alerts')).toBeInTheDocument());

    await waitFor(() =>
      expect(screen.getByText('Worker heartbeat missing on queue agent:runs:default')).toBeInTheDocument(),
    );
    expect(screen.getByText('critical')).toBeInTheDocument();
    expect(screen.getByText('worker stale')).toBeInTheDocument();

    // Compressed occurrences: count=5 shows ×5; count=1 shows no compression badge.
    expect(screen.getByText('×5')).toBeInTheDocument();
    expect(screen.queryByText('×1')).toBeNull();
  });

  it('engages the kill switch only after confirmation and updates the indicator', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('kill switch clear')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'Engage kill switch…' }));
    expect(mocks.killSwitch).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Confirm engage' }));

    await waitFor(() => expect(mocks.killSwitch).toHaveBeenCalledWith('engage', 'kyber operator action'));
    await waitFor(() => expect(screen.getByText('kill switch engaged')).toBeInTheDocument());
  });
});

describe('Command Center ops panels (enableAgentCommandCenter off)', () => {
  it('renders nothing new and performs no ops fetches, leaving the page unchanged', async () => {
    mocks.isFeatureEnabled.mockReturnValue(false);
    renderPage();

    // Existing Command page still renders.
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Command' })).toBeInTheDocument());
    expect(await screen.findByText('Roster')).toBeInTheDocument();

    // No new panels, no new fetches.
    expect(screen.queryByTestId('command-center-ops')).toBeNull();
    expect(screen.queryByText('Worker runtime health')).toBeNull();
    expect(screen.queryByText('Run history')).toBeNull();
    expect(screen.queryByText('Operator briefings')).toBeNull();
    expect(screen.queryByText('Ops alerts')).toBeNull();
    expect(mocks.health).not.toHaveBeenCalled();
    expect(mocks.runs).not.toHaveBeenCalled();
    expect(mocks.stuckRuns).not.toHaveBeenCalled();
    expect(mocks.briefings).not.toHaveBeenCalled();
    expect(mocks.opsAlerts).not.toHaveBeenCalled();
  });
});
