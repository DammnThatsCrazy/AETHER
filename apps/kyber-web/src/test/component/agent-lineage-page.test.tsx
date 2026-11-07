import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentLineagePage } from '@kyber/pages/agent-lineage';

const mocks = vi.hoisted(() => ({
  isFeatureEnabled: vi.fn(() => true),
  agentLineageInvestigation: vi.fn(),
  agentLineageAgents: vi.fn(),
  agentLineageAgent: vi.fn(),
}));

vi.mock('@kyber/lib/featureFlags', () => ({ isFeatureEnabled: mocks.isFeatureEnabled, featureFlags: {} }));
vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    agentLineageInvestigation: mocks.agentLineageInvestigation,
    agentLineageAgents: mocks.agentLineageAgents,
    agentLineageAgent: mocks.agentLineageAgent,
  } } },
}));

const VIEW = {
  summary: {
    direct_agents: 1, indirect_agents: 30000, active_agents: 8911, max_delegation_depth: 14,
    agent_instances: null, agent_runs: 4700000,
    disclosure: { as_of: '2026-10-01T10:00:00.000Z', completeness: 'partial', truncation_reasons: ['cyclic:3'] },
  },
  linkage: { verified_links: 5000, inferred_links: 25001, probabilistic_links: 0, unresolved_links: 12 },
  risk: {
    assessment_level: 'elevated', triggered_signals: ['out_of_scope_execution_rate'],
    segments: { no_indicators: 100, unresolved: 12, elevated_risk: 29889, confirmed_abusive: null },
  },
  spawn_acceleration: { spawn_rate: 300, baseline_agent_count: 2, acceleration: 9000 },
  common_tools: ['wallet_scan'], common_providers: [], wallets: ['wallet-1'],
  verified_external_effects: 200, reported_external_effects: null,
  clusters: { items: [{
    cluster_id: 'lc_1', kind: 'infrastructure_cluster', member_count: 3741, attribution_class: 'suspected_cluster',
    implies_common_control: false, bases: [{ basis: 'shared_infrastructure' }],
  }] },
  authority_boundary_crossings: { items: [] }, revoked_agents: { items: [] }, active_agents: { items: [] }, unresolved_agents: { items: [] },
};

async function investigate() {
  const user = userEvent.setup();
  render(<MemoryRouter><AgentLineagePage /></MemoryRouter>);
  await user.type(screen.getByLabelText('Tenant'), 'tenant-1');
  await user.type(screen.getByLabelText('Principal'), 'human:h1');
  await user.click(screen.getByRole('button', { name: 'Investigate' }));
  return user;
}

describe('AgentLineagePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.isFeatureEnabled.mockReturnValue(true);
    mocks.agentLineageInvestigation.mockResolvedValue(VIEW);
  });

  it('is gated by the telemetry flag', () => {
    mocks.isFeatureEnabled.mockReturnValue(false);
    render(<MemoryRouter><AgentLineagePage /></MemoryRouter>);
    expect(screen.getByText('Agent lineage is not enabled')).toBeTruthy();
    expect(mocks.agentLineageInvestigation).not.toHaveBeenCalled();
  });

  it('separates link strengths, shows unknown as unknown, and discloses completeness', async () => {
    await investigate();
    expect(await screen.findByText('5,000')).toBeTruthy();
    expect(screen.getByText('25,001')).toBeTruthy();
    expect(mocks.agentLineageInvestigation).toHaveBeenCalledWith('tenant-1', 'human:h1');
    // agent_instances and reported effects are null: never rendered as zero.
    expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/Completeness: partial/)).toBeTruthy();
    expect(screen.getByText(/cyclic:3/)).toBeTruthy();
  });

  it('never presents a suspected cluster as common control', async () => {
    await investigate();
    expect(await screen.findByText('does not establish common control')).toBeTruthy();
    expect(screen.getByText('suspected_cluster')).toBeTruthy();
  });

  it('drills from a cluster to one agent and its original evidence', async () => {
    mocks.agentLineageAgents.mockResolvedValue({
      items: [{ agent_entity_id: 'mal-42', depth: 4, attribution_class: 'inferred', evidence_class: 'PROVIDER_ASSERTED' }],
      next_cursor: null,
    });
    mocks.agentLineageAgent.mockResolvedValue({
      agent_entity_id: 'mal-42',
      ancestors: [{ agent_entity_id: 'mal-1' }, { agent_entity_id: 'mal-orch' }],
      principals: [{ principal_entity_id: 'human:h1', attribution_class: 'inferred', evidence_class: 'PROVIDER_ASSERTED' }],
      node: { agent_run_count: 1, agent_run_sample: ['run-42'], evidence_refs: ['ev-991'], verified_effects: ['effect-fraud-42'] },
    });
    const user = await investigate();
    await user.click(await screen.findByRole('button', { name: /3,741 agents/ }));
    await user.click(await screen.findByRole('button', { name: 'mal-42' }));
    await waitFor(() => expect(screen.getByText(/mal-1 → mal-orch/)).toBeTruthy());
    expect(screen.getByText(/ev-991/)).toBeTruthy();
    expect(screen.getByText(/effect-fraud-42/)).toBeTruthy();
    expect(screen.getByText(/human:h1 \(inferred, PROVIDER_ASSERTED\)/)).toBeTruthy();
    expect(mocks.agentLineageAgents).toHaveBeenCalledWith('tenant-1', 'human:h1', { cluster_id: 'lc_1', page_size: '50' });
  });

  it('reports a failed read instead of an empty population', async () => {
    mocks.agentLineageInvestigation.mockRejectedValue(new Error('boom'));
    await investigate();
    expect(await screen.findByText('Unable to load lineage')).toBeTruthy();
  });
});
