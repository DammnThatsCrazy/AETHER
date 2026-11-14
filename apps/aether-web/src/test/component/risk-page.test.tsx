import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider, queryCache } from '@aether/ui';
import { RiskPage } from '@aether-app/pages/risk';

type Q = { data: unknown; isLoading: boolean; error: string | null; refetch: () => void };

const s = vi.hoisted(() => ({
  findings: null as unknown,
  cases: [] as unknown,
  quality: {} as unknown,
  transition: vi.fn(),
}));

const settled = (data: unknown): Q => ({ data, isLoading: false, error: null, refetch: vi.fn() });

function settle<T>(value: T | Error): Promise<T> {
  return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
}

vi.mock('@aether-app/features/auth', () => ({ useAuth: () => ({ user: { id: 't1', displayName: 'Owner' } }) }));
vi.mock('@aether-app/features/agent-access', () => ({ useCapabilityRiskFindings: () => s.findings }));
vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    investigations: {
      list: () => settle(s.cases),
      transitionStatus: (id: string, body: unknown) => s.transition(id, body),
    },
    dataQuality: { overview: () => settle(s.quality) },
  },
}));

const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

function findingsResult(items: unknown[], byLevel: Record<string, number>, scope = 'all_matching_findings') {
  return {
    items,
    count: items.length,
    limit: 100,
    offset: 0,
    counts: { total: items.length, scope, by_risk_level: byLevel, by_code: {} },
  };
}

function caseRow(over: Record<string, unknown>) {
  return {
    id: 'c1',
    tenantId: 't1',
    title: 'Case',
    status: 'open',
    subjects: [],
    evidence: [],
    annotations: [],
    createdBy: 'analyst',
    createdAt: ago(3),
    updatedAt: ago(1),
    ...over,
  };
}

const EMPTY_QUALITY = { score: {}, dimensions: {}, open_drift_event_count: 0, drift_by_severity: {} };

function renderRisk(path = '/risk') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/risk" element={<RiskPage />} />
          <Route path="/users/:id" element={<div>USER PAGE</div>} />
          <Route path="/agents/:id" element={<div>AGENT PAGE</div>} />
          <Route path="/agent-access" element={<div>AGENTS PAGE</div>} />
          <Route path="/data-quality" element={<div>DATA QUALITY PAGE</div>} />
          <Route path="/explore" element={<div>EXPLORE PAGE</div>} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Risk', () => {
  beforeEach(() => {
    queryCache.invalidate('risk:t1:cases');
    queryCache.invalidate('risk:t1:data-quality');
    s.findings = settled(findingsResult([], {}));
    s.cases = [];
    s.quality = EMPTY_QUALITY;
    s.transition.mockReset().mockResolvedValue({});
  });

  it('shows loading states while the reads are in flight', () => {
    s.findings = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    renderRisk();
    expect(screen.getByText('Loading findings…')).toBeInTheDocument();
    expect(screen.queryByTestId('risk-counts')).not.toBeInTheDocument();
  });

  it('says nothing is open instead of showing illustrative risks, and never computes a posture score', async () => {
    renderRisk();
    expect(await screen.findByTestId('risk-severity-empty')).toBeInTheDocument();
    expect(screen.getByTestId('risk-top-empty')).toBeInTheDocument();
    expect(screen.getByText('Quality score not computed yet')).toBeInTheDocument();
    expect(screen.getByTestId('risk-counts')).toHaveTextContent('0 open · 0 critical');
    expect(screen.queryByText(/posture score/i)).not.toBeInTheDocument();
  });

  it('marks unavailable reads as unavailable, never as empty', async () => {
    s.findings = { data: null, isLoading: false, error: 'findings offline', refetch: vi.fn() };
    s.cases = new Error('cases offline');
    s.quality = new Error('dq offline');
    renderRisk();
    expect(screen.getAllByText(/Agent access findings are unavailable right now/).length).toBeGreaterThan(0);
    expect(await screen.findByText(/Investigations are unavailable right now/)).toBeInTheDocument();
    expect(await screen.findByText(/Data quality is unavailable right now/)).toBeInTheDocument();
    expect(screen.queryByTestId('risk-severity-empty')).not.toBeInTheDocument();
    expect(screen.queryByTestId('risk-top-empty')).not.toBeInTheDocument();
    expect(screen.queryByTestId('risk-counts')).not.toBeInTheDocument();
  });

  it('renders real findings, drift and cases, and opens the register from the overview', async () => {
    s.findings = settled(findingsResult(
      [
        { code: 'over_ceiling', risk_level: 'critical', summary: 'Agent acted above its ceiling', evidence: 'Order 520 vs 500', capability_id: 'cap-1', source: 'scan' },
        { code: 'drifted_identity', risk_level: 'medium', summary: null, evidence: null, capability_id: null, source: null },
      ],
      { critical: 1, medium: 1 },
    ));
    s.quality = { score: { overall_intelligence_quality_score: 0.82, status: 'healthy' }, open_drift_event_count: 2, drift_by_severity: { high: 2 } };
    s.cases = [
      caseRow({ id: 'c1', title: 'Shared wallet review', status: 'escalated', subjects: [{ kind: 'user', id: 'u-9', label: 'Priya' }] }),
      caseRow({ id: 'c2', title: 'Closed case', status: 'closed' }),
    ];
    renderRisk();
    expect(await screen.findByText('Intelligence quality score')).toBeInTheDocument();
    expect(screen.getByText('82%')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('risk-counts')).toHaveTextContent('5 open · 1 critical'));
    expect(screen.getByTestId('risk-severity-high')).toHaveTextContent('0 agent access · 2 data quality');

    const top = screen.getByTestId('risk-top');
    const rows = within(top).getAllByTestId('risk-row');
    expect(rows[0]).toHaveTextContent('Agent acted above its ceiling');
    expect(within(top).queryByText('Closed case')).not.toBeInTheDocument();

    fireEvent.click(within(top).getByText('Shared wallet review'));
    const detail = await screen.findByTestId('risk-detail');
    expect(within(detail).getByText('Escalated')).toBeInTheDocument();
    expect(within(detail).getByText('Severity is not rated for investigation cases.')).toBeInTheDocument();
    // Escalated cases may only close.
    expect(within(detail).queryByTestId('risk-case-active')).not.toBeInTheDocument();
    fireEvent.click(within(detail).getByTestId('risk-case-closed'));
    await waitFor(() => expect(s.transition).toHaveBeenCalledWith('c1', { tenantId: 't1', status: 'closed' }));

    fireEvent.click(within(detail).getByText('Priya'));
    expect(await screen.findByText('USER PAGE')).toBeInTheDocument();
  });

  it('filters the register by severity from the overview and shows finding detail', async () => {
    s.findings = settled(findingsResult(
      [
        { code: 'over_ceiling', risk_level: 'critical', summary: 'Agent acted above its ceiling', evidence: 'Order 520 vs 500', capability_id: 'cap-1', source: 'scan' },
        { code: 'drifted_identity', risk_level: 'low', summary: 'Capability identity drifted' },
      ],
      { critical: 1, low: 1 },
    ));
    s.cases = [caseRow({ id: 'c1', title: 'Open case' })];
    s.quality = { ...EMPTY_QUALITY, drift_by_severity: { critical: 3 } };
    renderRisk();
    fireEvent.click(await screen.findByTestId('risk-severity-critical'));
    const register = await screen.findByTestId('risk-register');
    expect(within(register).getAllByTestId('risk-row')).toHaveLength(1);
    expect(within(register).getByText(/3 critical data-quality drift events are listed in/)).toBeInTheDocument();
    const detail = screen.getByTestId('risk-detail');
    expect(within(detail).getByText('Order 520 vs 500')).toBeInTheDocument();
    expect(within(detail).getByText('cap-1')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Not rated' }));
    expect(within(register).getAllByTestId('risk-row')).toHaveLength(1);
    expect(within(register).getByTestId('risk-row')).toHaveTextContent('Open case');

    fireEvent.click(screen.getByRole('button', { name: 'Low' }));
    fireEvent.click(within(screen.getByTestId('risk-detail')).getByText('Open Agents →'));
    expect(await screen.findByText('AGENTS PAGE')).toBeInTheDocument();
  });

  it('starts mitigation on an open case and reports a failed transition', async () => {
    s.cases = [caseRow({ id: 'c9', title: 'Wallet sign-in failures', subjects: [{ kind: 'agent', id: 'atlas' }] })];
    s.transition.mockRejectedValueOnce(new Error('denied'));
    renderRisk('/risk?view=register');
    const detail = await screen.findByTestId('risk-detail');
    fireEvent.click(within(detail).getByTestId('risk-case-active'));
    expect(await within(detail).findByText('The case status could not be changed. Try again.')).toBeInTheDocument();
    fireEvent.click(within(detail).getByTestId('risk-case-active'));
    await waitFor(() => expect(s.transition).toHaveBeenLastCalledWith('c9', { tenantId: 't1', status: 'active' }));
    fireEvent.click(within(detail).getByText('atlas'));
    expect(await screen.findByText('AGENT PAGE')).toBeInTheDocument();
  });

  it('links the quality card to Data Quality and the case to Explore', async () => {
    s.cases = [caseRow({ id: 'c1', title: 'Open case' })];
    renderRisk();
    fireEvent.click(await screen.findByText('Open Data Quality →'));
    expect(await screen.findByText('DATA QUALITY PAGE')).toBeInTheDocument();
  });

  it('opens Explore from a case', async () => {
    s.cases = [caseRow({ id: 'c1', title: 'Open case' })];
    renderRisk('/risk?view=register');
    fireEvent.click(await screen.findByText('Open in Explore →'));
    expect(await screen.findByText('EXPLORE PAGE')).toBeInTheDocument();
  });

  it('says the register is empty when nothing is open', async () => {
    renderRisk('/risk?view=register');
    expect(await screen.findByTestId('risk-register-empty')).toHaveTextContent('Nothing open in the register.');
  });
});
