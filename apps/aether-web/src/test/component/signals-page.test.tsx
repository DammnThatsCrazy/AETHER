import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider, queryCache } from '@aether/ui';
import { SignalsPage } from '@aether-app/pages/signals';

const s = vi.hoisted(() => ({
  inbox: [] as unknown[] | Error | 'pending',
  rules: [] as unknown[] | Error,
  config: { tenant_id: 't1', digest: null, timezone: null } as unknown,
  archive: vi.fn(),
  markRead: vi.fn(),
  createAlert: vi.fn(),
  release: null as null | (() => void),
}));

function settle<T>(value: T | Error | 'pending'): Promise<T> {
  if (value === 'pending') return new Promise<T>(resolve => { s.release = () => resolve([] as T); });
  return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
}

vi.mock('@aether-app/features/auth', () => ({ useAuth: () => ({ user: { id: 't1', displayName: 'Owner' } }) }));
vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    inbox: {
      list: () => settle(s.inbox),
      archive: (id: string) => s.archive(id),
      markRead: (id: string) => s.markRead(id),
    },
    notifications: { alerts: () => settle(s.rules), createAlert: (body: unknown) => s.createAlert(body) },
    notificationChannels: { getConfig: () => Promise.resolve(s.config) },
  },
}));

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function row(over: Record<string, unknown>) {
  return {
    id: 'n1',
    tenant_id: 't1',
    category: 'alert',
    severity: 'info',
    title: 'Signal',
    body: null,
    link: null,
    correlation_id: null,
    dedupe_key: null,
    read: false,
    read_at: null,
    archived: false,
    archived_at: null,
    count: 1,
    created_at: ago(5),
    ...over,
  };
}

function renderSignals(path = '/signals') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/signals" element={<SignalsPage />} />
          <Route path="/users/:id" element={<div>USER PAGE</div>} />
          <Route path="/settings/notification-preferences" element={<div>NOTIFICATION PREFERENCES</div>} />
          <Route path="/settings/notifications" element={<div>NOTIFICATION CHANNELS</div>} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Signals', () => {
  beforeEach(() => {
    queryCache.invalidate('signals:t1:feed');
    queryCache.invalidate('signals:t1:rules');
    queryCache.invalidate('notification-config-t1');
    s.inbox = [];
    s.rules = [];
    s.config = { tenant_id: 't1', digest: null, timezone: null };
    s.archive.mockReset().mockResolvedValue({ id: 'n1', archived: true });
    s.markRead.mockReset().mockResolvedValue({ id: 'n1', read: true });
    s.createAlert.mockReset().mockResolvedValue({ id: 'r-new' });
  });

  it('shows a loading state while the feed is read', async () => {
    s.inbox = 'pending';
    renderSignals();
    expect(screen.getByText('Loading signals…')).toBeInTheDocument();
    expect(screen.queryByTestId('signals-counts')).not.toBeInTheDocument();
    // Settle the read so the shared query cache holds no in-flight request.
    s.release?.();
    expect(await screen.findByTestId('signals-inbox-empty')).toBeInTheDocument();
  });

  it('says the inbox is empty rather than showing sample signals', async () => {
    renderSignals();
    expect(await screen.findByTestId('signals-inbox-empty')).toBeInTheDocument();
    expect(screen.getByTestId('signals-counts')).toHaveTextContent('0 open · 0 critical');
  });

  it('marks an unavailable feed as unavailable, never as empty', async () => {
    s.inbox = new Error('inbox offline');
    renderSignals();
    expect(await screen.findByText(/Signals are unavailable right now/)).toBeInTheDocument();
    expect(screen.queryByTestId('signals-inbox-empty')).not.toBeInTheDocument();
  });

  it('renders real signals on a timeline, filters by severity and type, and acknowledges through the inbox', async () => {
    s.inbox = [
      row({ id: 'a', severity: 'P0', category: 'agent_authority', title: 'Agent exceeded its ceiling', body: 'Two orders over limit.', link: '/users/u-9', created_at: ago(10) }),
      row({ id: 'b', severity: 'P2', category: 'data_freshness', title: 'Salesforce is behind', created_at: ago(180), read: true, read_at: ago(60) }),
      row({ id: 'c', severity: 'info', category: 'data_freshness', title: 'Export ready', link: '/v1/exports/x/download', created_at: ago(30) }),
      row({ id: 'old', severity: 'P1', title: 'Older than the range', created_at: ago(60 * 24 * 3) }),
      row({ id: 'z', severity: 'P1', title: 'Already acknowledged', archived: true, archived_at: ago(20), created_at: ago(40) }),
    ];
    renderSignals();
    const inbox = await screen.findByTestId('signals-inbox');
    expect(screen.getByTestId('signals-counts')).toHaveTextContent('3 open · 1 critical');
    expect(within(inbox).getAllByTestId('signal-card')).toHaveLength(3);
    expect(within(screen.getByTestId('signals-bucket-hour')).getByText('Agent exceeded its ceiling')).toBeInTheDocument();
    expect(within(screen.getByTestId('signals-bucket-today')).getByText('Salesforce is behind')).toBeInTheDocument();
    expect(screen.queryByText('Older than the range')).not.toBeInTheDocument();
    expect(screen.getByText('Critical · P0')).toBeInTheDocument();
    // API links are not app pages, so only the app route gets an Open link.
    expect(screen.getAllByText('Open →')).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: /Watch · 1/ }));
    expect(within(inbox).getAllByTestId('signal-card')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: /All · 3/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Data freshness' }));
    expect(within(inbox).getAllByTestId('signal-card')).toHaveLength(2);

    // Widening the range brings the older signal in.
    fireEvent.click(screen.getByRole('button', { name: 'All types' }));
    fireEvent.click(screen.getByTestId('signals-range-168'));
    expect(screen.getByText('Older than the range')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('signals-range-24'));

    const card = screen.getByText('Agent exceeded its ceiling').closest('[data-testid="signal-card"]') as HTMLElement;
    fireEvent.click(within(card).getByTestId('signal-acknowledge'));
    await waitFor(() => expect(s.archive).toHaveBeenCalledWith('a'));
    fireEvent.click(within(card).getByTestId('signal-mark-read'));
    await waitFor(() => expect(s.markRead).toHaveBeenCalledWith('a'));
  });

  it('reports a failed acknowledge instead of hiding the signal', async () => {
    s.inbox = [row({ id: 'a', title: 'Needs a look' })];
    s.archive.mockRejectedValue(new Error('nope'));
    renderSignals();
    fireEvent.click(await screen.findByTestId('signal-acknowledge'));
    expect(await screen.findByText('That signal could not be acknowledged. Try again.')).toBeInTheDocument();
    expect(screen.getByText('Needs a look')).toBeInTheDocument();
  });

  it('opens a signal link in the app', async () => {
    s.inbox = [row({ id: 'a', title: 'Profile changed', link: '/users/u-9' })];
    renderSignals();
    fireEvent.click(await screen.findByText('Open →'));
    expect(await screen.findByText('USER PAGE')).toBeInTheDocument();
  });

  it('groups by type and jumps to the filtered inbox', async () => {
    s.inbox = [
      row({ id: 'a', severity: 'P0', category: 'consent', title: 'Contacts lack consent' }),
      row({ id: 'b', severity: 'P3', category: 'wallet', title: 'Wallet linked' }),
    ];
    renderSignals('/signals?tab=types');
    const cards = await screen.findAllByTestId('signals-type-card');
    expect(cards).toHaveLength(2);
    fireEvent.click(cards.find(c => within(c).queryByText('Consent')) as HTMLElement);
    const inbox = await screen.findByTestId('signals-inbox');
    expect(within(inbox).getAllByTestId('signal-card')).toHaveLength(1);
    expect(within(inbox).getByText('Contacts lack consent')).toBeInTheDocument();
  });

  it('lists stored alert rules read-only, with empty and unavailable states', async () => {
    renderSignals('/signals?tab=rules');
    expect(await screen.findByTestId('signals-rules-empty')).toBeInTheDocument();
  });

  it('renders alert rules from the backend as cards and links to channels', async () => {
    s.rules = [
      { id: 'r1', name: 'Ceiling breach', condition: 'agent.spend > ceiling', channels: ['slack'], recipients: ['owner@x.io'], severity: 'P1' },
      { id: 'r2', name: 'Stale connector', condition: 'connector.age > 30m', channels: ['in_app'], recipients: [] },
    ];
    renderSignals('/signals?tab=rules');
    const [rule, plain] = await screen.findAllByTestId('signals-rule');
    expect(within(rule!).getByText('Ceiling breach')).toBeInTheDocument();
    expect(within(rule!).getByText('agent.spend > ceiling')).toBeInTheDocument();
    expect(within(rule!).getByText('notifies owner@x.io · via slack')).toBeInTheDocument();
    expect(within(rule!).getByText('Critical')).toBeInTheDocument();
    // No severity is stored on this rule, so no pill is invented for it.
    expect(within(plain!).queryByText(/Critical|Watch|Info/)).not.toBeInTheDocument();
    expect(within(plain!).getByText('no recipients recorded · via in_app')).toBeInTheDocument();
    // Toggle / edit have no endpoint, so they are not offered.
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Save rule/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Notification channels →'));
    expect(await screen.findByText('NOTIFICATION CHANNELS')).toBeInTheDocument();
  });

  it('creates a rule with the backend body and refreshes the list', async () => {
    renderSignals('/signals?tab=rules');
    await screen.findByTestId('signals-rules-empty');
    fireEvent.click(screen.getByTestId('signals-new-rule'));
    const form = screen.getByTestId('signals-rule-form');
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: '  Ceiling breach ' } });
    fireEvent.change(within(form).getByLabelText('Condition'), { target: { value: 'agent.spend > ceiling' } });
    fireEvent.change(within(form).getByLabelText('Recipients'), { target: { value: 'owner, admin, owner' } });
    fireEvent.click(within(form).getByTestId('rule-channel-email'));
    s.rules = [{ id: 'r-new', name: 'Ceiling breach', condition: 'agent.spend > ceiling', channels: ['in_app', 'email'], recipients: ['owner', 'admin'] }];
    fireEvent.click(within(form).getByTestId('signals-rule-save'));
    await waitFor(() => expect(screen.queryByTestId('signals-rule-form')).not.toBeInTheDocument());
    expect(s.createAlert).toHaveBeenCalledWith({
      name: 'Ceiling breach', condition: 'agent.spend > ceiling', channels: ['in_app', 'email'], recipients: ['owner', 'admin'],
    });
    expect(await screen.findByText('Ceiling breach')).toBeInTheDocument();
  });

  it('validates the rule form before writing', async () => {
    renderSignals('/signals?tab=rules');
    await screen.findByTestId('signals-rules-empty');
    fireEvent.click(screen.getByTestId('signals-new-rule'));
    const form = screen.getByTestId('signals-rule-form');
    fireEvent.click(within(form).getByTestId('rule-channel-in_app'));
    fireEvent.click(within(form).getByTestId('signals-rule-save'));
    expect(await within(form).findByText('Give the rule a name.')).toBeInTheDocument();
    expect(within(form).getByText('Describe the condition that raises a signal.')).toBeInTheDocument();
    expect(within(form).getByText('Pick at least one channel.')).toBeInTheDocument();
    expect(within(form).getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true');
    expect(s.createAlert).not.toHaveBeenCalled();
  });

  it('keeps the form open and says why when the create fails', async () => {
    s.createAlert.mockRejectedValue(new Error('permission denied'));
    renderSignals('/signals?tab=rules');
    await screen.findByTestId('signals-rules-empty');
    fireEvent.click(screen.getByTestId('signals-new-rule'));
    const form = screen.getByTestId('signals-rule-form');
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'Ceiling breach' } });
    fireEvent.change(within(form).getByLabelText('Condition'), { target: { value: 'agent.spend > ceiling' } });
    fireEvent.click(within(form).getByTestId('signals-rule-save'));
    expect(await within(form).findByText(/The rule was not saved: permission denied/)).toBeInTheDocument();
    expect(screen.getByTestId('signals-rule-form')).toBeInTheDocument();
    expect(screen.getByTestId('signals-rules-empty')).toBeInTheDocument();
  });

  it('marks unavailable rules as unavailable', async () => {
    s.rules = new Error('rules offline');
    renderSignals('/signals?tab=rules');
    expect(await screen.findByText(/Alert rules are unavailable right now/)).toBeInTheDocument();
  });

  it('shows acknowledged signals in History', async () => {
    s.inbox = [row({ id: 'z', title: 'Already acknowledged', archived: true, archived_at: ago(20) })];
    renderSignals('/signals?tab=history');
    const history = await screen.findByTestId('signals-history');
    expect(within(history).getByText('Already acknowledged')).toBeInTheDocument();
  });

  it('says History is empty when nothing is acknowledged', async () => {
    renderSignals('/signals?tab=history');
    expect(await screen.findByTestId('signals-history-empty')).toBeInTheDocument();
  });

  it('previews the digest from open signals and shows the stored schedule', async () => {
    s.inbox = [row({ id: 'a', severity: 'P1', title: 'Critical thing' }), row({ id: 'b', severity: 'P3', title: 'Watch thing' })];
    s.config = { tenant_id: 't1', timezone: 'Europe/London', digest: { enabled: true, frequency: 'weekly', send_time: '08:00' } };
    renderSignals('/signals?tab=digest');
    expect(await screen.findByText('2 signals need a look, 1 critical')).toBeInTheDocument();
    const schedule = await screen.findByTestId('signals-digest-schedule');
    expect(schedule).toHaveTextContent('Weekly digest');
    expect(schedule).toHaveTextContent('Sent at 08:00 · Europe/London');
    fireEvent.click(screen.getByTestId('signals-digest-settings'));
    expect(await screen.findByText('NOTIFICATION PREFERENCES')).toBeInTheDocument();
  });

  it('says the digest is off when no schedule is stored', async () => {
    renderSignals('/signals?tab=digest');
    expect(await screen.findByText('Digest is off')).toBeInTheDocument();
    expect(screen.getByText('Nothing open needs a look')).toBeInTheDocument();
  });
});
