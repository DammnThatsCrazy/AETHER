import type { ReactNode } from 'react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { GraphContextProvider } from '@aether/ui/exploration';
import { ThemeProvider } from '@aether/ui';
import { AgentLineagePanel, PrincipalAgentLineagePanel } from '@aether-app/features/agent360';

const API = 'http://localhost:8000';
const BASE = `${API}/v1/agent-lineage/principals/human%3Ah1`;

function envelope(data: unknown) {
  return { data, status: 'ok', timestamp: '2026-10-29T12:00:00Z' };
}

const disclosure = { as_of: '2026-10-01T10:00:00.000Z', completeness: 'partial', truncation_reasons: ['cyclic:3'], truncated: false };

const server = setupServer(
  http.get(`${BASE}/summary`, () => HttpResponse.json(envelope({
    direct_agents: 43, indirect_agents: 74238, active_agents: 8911, agent_instances: 318902, agent_runs: null,
    risk_flagged_agents: null, unresolved_agents: 819, probabilistic_agents: 7, max_delegation_depth: 14,
    verified_links: 100, inferred_links: 74181, revoked_agents: 3, out_of_scope_agents: 2, tools_used: 9, disclosure,
  }))),
  http.get(`${BASE}/clusters`, () => HttpResponse.json(envelope({
    items: [{ cluster_id: 'c1', kind: 'infrastructure_cluster', member_count: 3741, attribution_class: 'suspected_cluster', bases: [{ basis: 'shared_infrastructure' }] }],
    next_cursor: null, disclosure,
  }))),
  http.get(`${BASE}/tree`, ({ request }) => {
    const parent = new URL(request.url).searchParams.get('parent');
    return HttpResponse.json(envelope({
      items: parent
        ? [{ agent_entity_id: 'child-1', depth: 2, descendant_count: 0, attribution_class: 'inferred' }]
        : [{ agent_entity_id: 'agent-a', depth: 1, descendant_count: 4219, collapsed: true, attribution_class: 'verified' }],
      next_cursor: null, disclosure,
    }));
  }),
  http.get(`${BASE}/agents`, ({ request }) => {
    const url = new URL(request.url);
    const cursor = url.searchParams.get('cursor');
    expect(url.searchParams.get('relationship')).toBe('direct');
    return HttpResponse.json(envelope({
      items: [{ agent_entity_id: cursor ? 'direct-2' : 'direct-1', attribution_class: 'verified', depth: 1, active_state: 'active' }],
      next_cursor: cursor ? null : 'next', disclosure,
    }));
  }),
  http.get(`${API}/v1/agent-lineage/agents/agent-a`, () => HttpResponse.json(envelope({
    agent_entity_id: 'agent-a',
    node: {
      depth: 3, lineage_status: 'complete', agent_instance_count: 12, agent_run_count: 40,
      agent_definition_ids: ['def-1'], agent_deployment_ids: ['dep-1'], authority_refs: ['grant-1'],
      tool_sample: ['read_file'], service_sample: [], verified_effects: ['effect-1'], reported_effects: [],
      outcome_refs: ['outcome-1'], evidence_refs: ['ev-1'],
    },
    principals: [{ agent_entity_id: 'agent-a', principal_entity_id: 'human:h1', attribution_class: 'verified', relationship_type: 'SPAWNED', evidence_class: 'VERIFIED_AUTHORITY', authority_resolution_status: 'verified' }],
    ancestors: [{ agent_entity_id: 'parent-1' }, { agent_entity_id: 'root-1' }],
    counts: { direct_child_count: 2, recursive_descendant_count: 30, active_descendant_count: 5, risk_descendant_count: null, max_descendant_depth: 4 },
    disclosure: { ...disclosure, completeness: 'complete', truncation_reasons: [] },
  }))),
  http.get(`${API}/v1/agent-lineage/agents/agent-a/descendants`, () => HttpResponse.json(envelope({
    items: [{ agent_entity_id: 'desc-1', depth: 4 }], next_cursor: null, disclosure,
  }))),
  http.get(`${API}/v1/agent-lineage/agents/ghost`, () => HttpResponse.json(envelope({
    agent_entity_id: 'ghost', node: null, principals: [], ancestors: [], counts: {},
    disclosure: { completeness: 'unknown', truncation_reasons: [] },
  }))),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrap(node: ReactNode) {
  return (
    <ThemeProvider>
      <MemoryRouter>
        <GraphContextProvider scope={{ tenant_id: 'tenant-1', workspace_id: 'w', environment_id: 'production' }}>{node}</GraphContextProvider>
      </MemoryRouter>
    </ThemeProvider>
  );
}

describe('PrincipalAgentLineagePanel', () => {
  it('leads with the summary, keeps unknown as unknown, and discloses completeness', async () => {
    render(wrap(<PrincipalAgentLineagePanel principalId="human:h1" />));
    expect(await screen.findByText('74,281')).toBeTruthy();
    expect(screen.getByText('318,902')).toBeTruthy();
    expect(screen.getAllByText('Unknown').length).toBe(2);
    expect(screen.getByText(/Completeness: partial/)).toBeTruthy();
    expect(screen.getByText(/cyclic:3/)).toBeTruthy();
    // No agent rows until a cohort is chosen.
    expect(screen.queryByText('direct-1')).toBeNull();
  });

  it('pages a cohort through its cursor', async () => {
    const user = userEvent.setup();
    render(wrap(<PrincipalAgentLineagePanel principalId="human:h1" />));
    await user.click(await screen.findByRole('button', { name: 'Direct' }));
    expect(await screen.findByText('direct-1')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Load more' }));
    expect(await screen.findByText('direct-2')).toBeTruthy();
    expect(screen.getByText('direct-1')).toBeTruthy();
  });

  it('collapses a branch to its count and expands one level at a time', async () => {
    const user = userEvent.setup();
    render(wrap(<PrincipalAgentLineagePanel principalId="human:h1" />));
    const toggle = await screen.findByRole('button', { name: '[4,219 descendants]' });
    expect(screen.queryByText('child-1')).toBeNull();
    await user.click(toggle);
    expect(await screen.findByText('child-1')).toBeTruthy();
  });

  it('labels a cluster with why it is grouped and its attribution', async () => {
    render(wrap(<PrincipalAgentLineagePanel principalId="human:h1" />));
    expect(await screen.findByText(/grouped by shared infrastructure/)).toBeTruthy();
    expect(screen.getByText('Suspected cluster')).toBeTruthy();
  });
});

describe('AgentLineagePanel', () => {
  it('shows hierarchy, chain, principals, and keeps verified apart from reported effects', async () => {
    const user = userEvent.setup();
    render(wrap(<AgentLineagePanel agentId="agent-a" />));
    expect(await screen.findByText('parent-1')).toBeTruthy();
    expect(screen.getByText('root-1')).toBeTruthy();
    expect(screen.getByText('human:h1')).toBeTruthy();
    expect(screen.getByText('effect-1')).toBeTruthy();
    expect(screen.getByText('None reported.')).toBeTruthy();
    expect(screen.getByText('Unknown')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Show descendants' }));
    await waitFor(() => expect(screen.getByText('desc-1')).toBeTruthy());
  });

  it('does not read an unprojected agent as having no lineage', async () => {
    render(wrap(<AgentLineagePanel agentId="ghost" />));
    expect(await screen.findByText('Not in the lineage projection yet')).toBeTruthy();
  });
});
