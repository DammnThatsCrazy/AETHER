import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PatternDiscoveryPage } from '@kyber/pages/pattern-discovery';

const authState = vi.hoisted(() => ({
  capabilities: ['kyber.approvals.decide', 'kyber.diagnostics.read'] as string[],
}));

vi.mock('@kyber/features/auth', () => ({
  useAuth: () => ({
    status: 'authenticated' as const,
    isAuthenticated: true,
    isLoading: false,
    error: null,
    session: null,
    lastSyncedAt: Date.now(),
    principal: {
      operator_id: 'op_001', email: 'operator@aether.dev', display_name: 'Operator',
      employment_status: 'active', environment: 'local', session_id: 'sess_001', session_status: 'active',
      authentication_strength: 'device_bound', device_id: 'dev_001', device_approval_state: 'approved',
      role_template_ids: ['kyber.role.engineering'], capabilities: authState.capabilities,
      max_disclosure: 5, max_action_class: 5, presence_expires_at: null, authority_expires_at: null,
      idle_expires_at: null, step_up_expires_at: null, active_scope: null, may_approve_devices: true,
    },
    login: vi.fn(), logout: vi.fn(), refresh: vi.fn(),
  }),
}));

const SUMMARY = {
  pattern_id: 'tenant-pd:pat:abc',
  kind: 'cross_domain',
  title: '14 entities linked across 6 independent signals',
  summary: '14 entities appear in 12 patterns of 6 different kinds.',
  status: 'needs_review',
  priority: 'high',
  severity: 'high',
  severity_score: 0.3,
  confidence: 0.5,
  confidence_cap: 0.85,
  novelty: 1,
  affected_entity_count: 14,
  risk_categories: ['payment', 'infrastructure'],
  first_observed_at: '2026-11-02T14:00:20Z',
  last_observed_at: '2026-11-02T16:02:00Z',
  version: 1,
  times_observed: 1,
  suppressed_by_feedback: false,
  claim_state: 'inferred',
};

const DETAIL = {
  ...SUMMARY,
  evidence: [{ type: 'independent_detector_agreement', basis: 'inferred', strength: 0.5, detail: { kinds: ['sequence'] }, source_event_refs: [] }],
  competing_explanations: [{ id: 'common_cause', note: 'One upstream cause can surface in several detectors.' }],
  affected_entities: [{ kind: 'user', id: 'r0', key: 'user:r0' }],
  review_history: [],
  similar_patterns: [],
  members: [{ ...SUMMARY, pattern_id: 'tenant-pd:pat:m1', kind: 'sequence', title: 'Recurring sequence: login → add_card!fail+' }],
  promotion: null,
};

const api = vi.hoisted(() => ({
  patternQueue: vi.fn(),
  patternDetail: vi.fn(),
  reviewPattern: vi.fn(),
  promotePattern: vi.fn(),
  deprecatePattern: vi.fn(),
  runPatternDiscovery: vi.fn(),
  patternStats: vi.fn(),
}));

vi.mock('@kyber/lib/api', () => ({ api: { admin: { kyber: api } } }));

describe('Pattern Discovery queue', () => {
  beforeEach(() => {
    Object.values(api).forEach(fn => fn.mockReset());
    api.patternQueue.mockResolvedValue({ items: [SUMMARY], count: 1, total: 1 });
    api.patternDetail.mockResolvedValue(DETAIL);
    api.reviewPattern.mockResolvedValue({ ...DETAIL, status: 'confirmed_malicious' });
    api.runPatternDiscovery.mockResolvedValue({ patterns_detected: 3 });
  });

  it('asks for a tenant before loading anything', () => {
    render(<MemoryRouter><PatternDiscoveryPage /></MemoryRouter>);
    expect(screen.getByText('Choose a tenant')).toBeInTheDocument();
    expect(api.patternQueue).not.toHaveBeenCalled();
  });

  it('opens the queue, shows evidence and competing explanations, and records a verdict', async () => {
    render(<MemoryRouter><PatternDiscoveryPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Tenant ID'), { target: { value: 'tenant-pd' } });
    fireEvent.click(screen.getByText('Open queue'));
    await waitFor(() => expect(api.patternQueue).toHaveBeenCalledWith('tenant-pd', { status: undefined, kind: undefined, limit: 100 }));
    fireEvent.click(await screen.findByText(SUMMARY.title));
    await waitFor(() => expect(api.patternDetail).toHaveBeenCalledWith('tenant-pd', SUMMARY.pattern_id));
    expect(await screen.findByText(/One upstream cause/)).toBeInTheDocument();
    expect(screen.getByText(/Recurring sequence/)).toBeInTheDocument();

    const promote = screen.getByText('Promote to risk').closest('button')!;
    expect(promote).toBeDisabled(); // not confirmed yet

    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'confirmed card-testing ring' } });
    const select = screen.getByDisplayValue('valid');
    fireEvent.change(select, { target: { value: 'malicious' } });
    fireEvent.click(screen.getByText('Record verdict'));
    await waitFor(() => expect(api.reviewPattern).toHaveBeenCalledWith('tenant-pd', SUMMARY.pattern_id, {
      verdict: 'malicious', reason: 'confirmed card-testing ring',
    }));
  });

  it('runs discovery for the chosen tenant and refreshes the queue', async () => {
    render(<MemoryRouter><PatternDiscoveryPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Tenant ID'), { target: { value: 'tenant-pd' } });
    fireEvent.click(screen.getByText('Open queue'));
    await screen.findByText(SUMMARY.title);
    fireEvent.click(screen.getByText('Run discovery'));
    await waitFor(() => expect(api.runPatternDiscovery).toHaveBeenCalledWith('tenant-pd'));
    await waitFor(() => expect(api.patternQueue).toHaveBeenCalledTimes(2));
  });
});
