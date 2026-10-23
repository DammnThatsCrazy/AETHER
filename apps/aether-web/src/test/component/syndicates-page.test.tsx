import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider, queryCache } from '@aether/ui';
import { SyndicatesPage } from '@aether-app/pages/syndicates';

const s = vi.hoisted(() => ({
  groups: (() => Promise.resolve({ groups: [], count: 0 })) as () => Promise<unknown>,
  clusters: (() => Promise.resolve({ nodes: [], edges: [] })) as () => Promise<unknown>,
  group: ((id: string) => Promise.resolve({ id, name: id })) as (id: string) => Promise<unknown>,
  members: ((id: string) => Promise.resolve({ population_id: id, members: [], count: 0 })) as (id: string) => Promise<unknown>,
  createGroup: vi.fn(),
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    me: { profile: () => Promise.resolve({ tenant_id: 't1' }) },
    population: {
      groups: () => s.groups(),
      group: (id: string) => s.group(id),
      groupMembers: (id: string) => s.members(id),
      createGroup: (body: unknown) => s.createGroup(body),
    },
    graphIntelligence: { query: () => s.clusters() },
  },
}));

const DAY = 86_400_000;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * DAY).toISOString();

const GROUPS = [
  {
    id: 'g1', name: 'Repeat buyers', population_type: 'segment', member_count: 3, definition_version: '2',
    definition: { rules: [{ field: 'order_count', op: '>=', value: 2 }, 'Purchased in the last 60 days'] },
    created_at: iso(40), updated_at: iso(2),
  },
  { id: 'g2', name: 'Agent delegators', population_type: 'cohort', member_count: 2, definition: {}, created_at: iso(90), updated_at: iso(60) },
];

const CLUSTER_NODES = {
  nodes: [{ id: 'c1', kind: 'householdcluster', label: 'Shared address 14 Elm', properties: { member_count: 4, lifecycle_state: 'active', updated_at: iso(1) } }],
  edges: [],
};

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname}{l.search}</div>;
}

function renderAt(path: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/syndicates" element={<SyndicatesPage />} />
          <Route path="/syndicates/:syndicateId" element={<SyndicatesPage />} />
          <Route path="*" element={<div>elsewhere</div>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Syndicates', () => {
  beforeEach(() => {
    queryCache.invalidatePrefix('syndicates:');
    queryCache.invalidate('me-profile');
    s.groups = () => Promise.resolve({ groups: [], count: 0 });
    s.clusters = () => Promise.resolve({ nodes: [], edges: [] });
    s.group = (id: string) => Promise.resolve(GROUPS.find(g => g.id === id) ?? { id, name: id });
    s.members = (id: string) => Promise.resolve({ population_id: id, members: [], count: 0 });
    s.createGroup.mockReset();
  });

  it('shows a loading state before the reads settle', () => {
    s.groups = () => new Promise(() => {});
    s.clusters = () => new Promise(() => {});
    renderAt('/syndicates');
    expect(screen.getByText('Loading syndicates…')).toBeInTheDocument();
  });

  it('says there are no syndicates yet instead of inventing any', async () => {
    renderAt('/syndicates');
    expect(await screen.findByTestId('syndicates-empty')).toHaveTextContent(/No syndicates yet/);
    expect(screen.queryByTestId('syndicate-row')).not.toBeInTheDocument();
  });

  it('marks unavailable reads as unavailable, never as empty', async () => {
    s.groups = () => Promise.reject(new Error('population offline'));
    s.clusters = () => Promise.reject(new Error('graph offline'));
    renderAt('/syndicates');
    expect(await screen.findByText('Rule-defined syndicates are unavailable right now.')).toBeInTheDocument();
    expect(await screen.findByText('Discovered clusters are unavailable right now.')).toBeInTheDocument();
    expect(screen.queryByTestId('syndicates-empty')).not.toBeInTheDocument();
  });

  it('lists rule-defined groups and discovered clusters, each opening its real detail', async () => {
    s.groups = () => Promise.resolve({ groups: GROUPS, count: 2 });
    s.clusters = () => Promise.resolve(CLUSTER_NODES);
    renderAt('/syndicates');
    const rows = await screen.findAllByTestId('syndicate-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Repeat buyers');
    expect(rows[0]).toHaveTextContent('3 members');
    expect(rows[0]).toHaveTextContent('order count >= 2');
    const cluster = await screen.findByTestId('cluster-row');
    expect(cluster).toHaveTextContent('Shared address 14 Elm');
    expect(cluster).toHaveTextContent('Household cluster');
    expect(cluster).toHaveAttribute('href', '/clusters/c1');

    fireEvent.click(screen.getByRole('tab', { name: 'Discovered' }));
    expect(screen.queryByTestId('syndicate-row')).not.toBeInTheDocument();
    expect(screen.getByTestId('cluster-row')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Changed recently' }));
    expect(screen.getAllByTestId('syndicate-row')).toHaveLength(1);

    fireEvent.click(screen.getByRole('tab', { name: 'All' }));
    fireEvent.change(screen.getByLabelText('Search syndicates'), { target: { value: 'zzz' } });
    expect(screen.getByTestId('syndicates-empty')).toHaveTextContent('No syndicates match.');
    fireEvent.change(screen.getByLabelText('Search syndicates'), { target: { value: '' } });

    fireEvent.click(screen.getAllByTestId('syndicate-row')[0]!);
    expect(screen.getByTestId('where')).toHaveTextContent('/syndicates/g1');
  });

  it('computes overlap from real member reads', async () => {
    s.groups = () => Promise.resolve({ groups: GROUPS, count: 2 });
    s.members = (id: string) => Promise.resolve({
      population_id: id,
      members: id === 'g1'
        ? [{ entity_id: 'u1', entity_type: 'user' }, { entity_id: 'u2', entity_type: 'user' }, { entity_id: 'u3', entity_type: 'user' }]
        : [{ entity_id: 'u2', entity_type: 'user' }, { entity_id: 'a9', entity_type: 'agent' }],
    });
    renderAt('/syndicates?mode=overlap');
    const panel = await screen.findByTestId('overlap');
    fireEvent.click(within(panel).getByRole('button', { name: /Repeat buyers/ }));
    fireEvent.click(within(panel).getByRole('button', { name: /Agent delegators/ }));
    expect(await screen.findByTestId('overlap-note')).toHaveTextContent('1 active member belong to both Repeat buyers and Agent delegators.');
    expect(screen.getByTestId('overlap-note')).not.toHaveTextContent('lower bound');
  });

  it('opens a syndicate with rules, composition, movement and linked top members', async () => {
    s.members = () => Promise.resolve({
      population_id: 'g1',
      members: [
        { entity_id: 'u1', entity_type: 'user', basis: 'rule', confidence: 0.9, joined_at: iso(3) },
        { entity_id: 'agent-7', entity_type: 'agent', basis: 'rule', confidence: 0.6, joined_at: iso(45) },
        { entity_id: 'u3', entity_type: 'user', basis: 'manual', confidence: 0.8, joined_at: iso(100) },
      ],
    });
    renderAt('/syndicates/g1');
    expect(await screen.findByRole('heading', { name: 'Repeat buyers' })).toBeInTheDocument();
    expect(screen.getByTestId('syndicate-rules')).toHaveTextContent('Purchased in the last 60 days');
    expect(await screen.findByTestId('members-readout')).toHaveTextContent('3 members now');
    const movement = screen.getByTestId('movement');
    expect(movement).toHaveTextContent('+1');
    expect(movement).toHaveTextContent('Left · not reported');
    const top = screen.getAllByTestId('top-member');
    expect(top[0]).toHaveAttribute('href', '/users/u1');
    expect(top.find(a => a.textContent?.includes('agent-7'))).toHaveAttribute('href', '/agents/agent-7');
    expect(screen.getByTestId('composition')).toHaveTextContent('user');

    fireEvent.click(screen.getByRole('tab', { name: '90d' }));
    expect(movement).toHaveTextContent('+2');

    fireEvent.click(screen.getByRole('button', { name: /← Syndicates/ }));
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/syndicates$/);
  });

  it('reports "now" from the group member count when the member read is partial', async () => {
    s.group = (id: string) => Promise.resolve({ ...GROUPS[0], id, member_count: 8483 });
    s.members = () => Promise.resolve({
      population_id: 'g1',
      members: [
        { entity_id: 'u1', entity_type: 'user', basis: 'rule', confidence: 0.9, joined_at: iso(3) },
        { entity_id: 'u2', entity_type: 'user', basis: 'rule', confidence: 0.7, joined_at: iso(10) },
      ],
    });
    renderAt('/syndicates/g1');
    const readout = await screen.findByTestId('members-readout');
    // The header and the chart agree on the group's size, not the 2 members read.
    expect(readout).toHaveTextContent('8,483 members now');
    expect(readout).not.toHaveTextContent(/^2 members now/);
    expect(screen.getByTestId('members-chart-scope')).toHaveTextContent('Chart shows joins among the first 2 members read, of 8,483.');
    // The Joined tile and the movement card say their counts cover the members read.
    expect(screen.getAllByText(/among first 2 read/)).toHaveLength(2);
  });

  it('does not label the chart as partial when every member was read', async () => {
    s.members = () => Promise.resolve({
      population_id: 'g1',
      members: [
        { entity_id: 'u1', joined_at: iso(3) }, { entity_id: 'u2', joined_at: iso(4) }, { entity_id: 'u3', joined_at: iso(5) },
      ],
    });
    renderAt('/syndicates/g1');
    expect(await screen.findByTestId('members-readout')).toHaveTextContent('3 members now');
    expect(screen.queryByTestId('members-chart-scope')).not.toBeInTheDocument();
  });

  it('keeps an unavailable member read distinct from an empty one', async () => {
    s.members = () => Promise.reject(new Error('members offline'));
    renderAt('/syndicates/g1');
    expect(await screen.findByText('Members could not be read right now, so membership charts are unavailable.')).toBeInTheDocument();
    expect(screen.queryByText('No active members yet.')).not.toBeInTheDocument();
  });
  it('keeps the search and filter tabs visible in overlap mode, narrowing the chips', async () => {
    s.groups = () => Promise.resolve({ groups: GROUPS, count: 2 });
    renderAt('/syndicates?mode=overlap');
    const panel = await screen.findByTestId('overlap');
    expect(screen.getByLabelText('Search syndicates')).toBeInTheDocument();
    expect(screen.getByRole('tablist', { name: 'Syndicate filters' })).toBeInTheDocument();
    expect(screen.getByTestId('syndicate-new')).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole('button', { name: /Agent delegators/ }));
    fireEvent.change(screen.getByLabelText('Search syndicates'), { target: { value: 'repeat' } });
    // The selected group stays; the search narrows the rest.
    expect(within(panel).getByRole('button', { name: /Repeat buyers/ })).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: /Agent delegators/ })).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole('button', { name: /Agent delegators/ }));
    expect(within(panel).queryByRole('button', { name: /Agent delegators/ })).not.toBeInTheDocument();
  });

  it('creates a syndicate with typed rules, refreshes the list and opens it', async () => {
    let listed: unknown[] = [];
    s.groups = () => Promise.resolve({ groups: listed, count: listed.length });
    s.createGroup.mockImplementation((body: { name: string }) => {
      const created = { id: 'g-new', name: body.name, population_type: 'segment', definition: { rules: [{ field: 'order_count', op: '>=', value: 2 }] } };
      listed = [created];
      return Promise.resolve(created);
    });
    s.group = (id: string) => Promise.resolve(listed.find(g => (g as { id: string }).id === id) ?? { id, name: id });
    renderAt('/syndicates');
    await screen.findByTestId('syndicates-empty');
    fireEvent.click(screen.getByTestId('syndicate-new'));
    const form = screen.getByTestId('syndicate-form');
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: ' Repeat buyers ' } });
    fireEvent.change(within(form).getByLabelText('Rule 1 field'), { target: { value: 'order_count' } });
    fireEvent.change(within(form).getByLabelText('Rule 1 operator'), { target: { value: '>=' } });
    fireEvent.change(within(form).getByLabelText('Rule 1 value'), { target: { value: '2' } });
    fireEvent.click(within(form).getByRole('button', { name: '+ Add rule' }));
    fireEvent.change(within(form).getByLabelText('Rule 2 field'), { target: { value: 'country' } });
    fireEvent.change(within(form).getByLabelText('Rule 2 operator'), { target: { value: 'in' } });
    fireEvent.change(within(form).getByLabelText('Rule 2 value'), { target: { value: 'US, CA' } });
    fireEvent.click(within(form).getByTestId('syndicate-save'));
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/syndicates/g-new'));
    expect(s.createGroup).toHaveBeenCalledWith({
      name: 'Repeat buyers',
      population_type: 'segment',
      description: '',
      definition: { rules: [{ field: 'order_count', op: '>=', value: 2 }, { field: 'country', op: 'in', value: ['US', 'CA'] }] },
    });
    expect(await screen.findByTestId('syndicate-detail')).toHaveTextContent('Repeat buyers');
    // The list read was invalidated, so going back shows the new group.
    fireEvent.click(screen.getByRole('button', { name: /← Syndicates/ }));
    expect(await screen.findByTestId('syndicate-row')).toHaveTextContent('Repeat buyers');
  });

  it('validates the syndicate form before writing', async () => {
    renderAt('/syndicates');
    await screen.findByTestId('syndicates-empty');
    fireEvent.click(screen.getByTestId('syndicate-new'));
    const form = screen.getByTestId('syndicate-form');
    fireEvent.click(within(form).getByTestId('syndicate-save'));
    expect(await within(form).findByText('Give the syndicate a name.')).toBeInTheDocument();
    expect(within(form).getByText('A segment needs at least one rule.')).toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText('Rule 1 field'), { target: { value: 'order_count' } });
    fireEvent.click(within(form).getByTestId('syndicate-save'));
    expect(await within(form).findByText('Give the value to compare against.')).toBeInTheDocument();
    expect(s.createGroup).not.toHaveBeenCalled();
  });

  it('keeps the syndicate form open and says why when the create fails', async () => {
    s.createGroup.mockRejectedValue(new Error('write permission required'));
    renderAt('/syndicates');
    await screen.findByTestId('syndicates-empty');
    fireEvent.click(screen.getByTestId('syndicate-new'));
    const form = screen.getByTestId('syndicate-form');
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'Lookalikes' } });
    fireEvent.change(within(form).getByLabelText('Type'), { target: { value: 'lookalike' } });
    fireEvent.click(within(form).getByTestId('syndicate-save'));
    expect(await within(form).findByText(/The syndicate was not created: write permission required/)).toBeInTheDocument();
    expect(s.createGroup).toHaveBeenCalledWith(expect.objectContaining({ population_type: 'lookalike', definition: { rules: [] } }));
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/syndicates$/);
  });
});
