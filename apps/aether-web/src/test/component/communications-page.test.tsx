import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { CommunicationDetailPage, CommunicationsPage } from '@aether-app/pages/communications';
import { fetchCommsIndex } from '@aether-app/features/communications/use-communications';

type Read = { data: unknown; isLoading: boolean; error: string | null; refetch: () => void };
const settled = (data: unknown): Read => ({ data, isLoading: false, error: null, refetch: vi.fn() });
const loading = (): Read => ({ data: null, isLoading: true, error: null, refetch: vi.fn() });
const failed = (error: string): Read => ({ data: null, isLoading: false, error, refetch: vi.fn() });

const s = vi.hoisted(() => ({
  index: null as unknown,
  health: null as unknown,
  campaign: null as unknown,
  message: null as unknown,
  funnel: null as unknown,
  recipients: {} as Record<string, unknown>,
  journeys: null as unknown,
  conversions: null as unknown,
  apiList: null as unknown,
  apiMessages: {} as Record<string, unknown>,
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    campaigns: {
      list: () => Promise.resolve(s.apiList),
      messages: (id: string) => {
        const v = s.apiMessages[id];
        return v instanceof Error ? Promise.reject(v) : Promise.resolve(v);
      },
    },
  },
}));

vi.mock('@aether-app/features/communications/use-communications', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aether-app/features/communications/use-communications')>();
  return {
    ...actual,
    useCommsIndex: () => s.index,
    useCommsHealth: () => s.health,
    useCommsCampaign: () => s.campaign,
    useCommsMessage: () => s.message,
    useCommsFunnel: () => s.funnel,
    useCommsRecipients: (_id: string, stage: string) => s.recipients[stage] ?? loading(),
    useCommsJourneys: () => s.journeys,
    useCommsConversions: () => s.conversions,
  };
});

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname}{loc.search}</div>;
}

function renderAt(path: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/communications" element={<CommunicationsPage />} />
          <Route path="/communications/:campaignId/:messageId" element={<CommunicationDetailPage />} />
          <Route path="*" element={<div>OTHER PAGE</div>} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

const hubspotCampaign = { id: 'c1', name: 'Spring Upgrade', status: 'active', channel: 'email', primary_platform: 'hubspot' };
const smsCampaign = { id: 'c2', name: 'Cart Rescue', status: 'active', channel: 'sms', primary_platform: 'klaviyo' };

function populatedIndex() {
  return {
    campaigns: [
      {
        raw: hubspotCampaign,
        messages: [{ external_message_id: 'm1', name: 'Upgrade Reminder', status: 'active', sequence_step: 1, delivered: 1840, human_clicks: 210, replies: 12, bounces: 9, machine_events: 40, total_events: 400 }],
        error: null,
      },
      {
        raw: smsCampaign,
        messages: [{ external_message_id: 's1', name: 'Cart nudge', status: 'active', delivered: 600, human_clicks: 80, replies: 0, bounces: 0, machine_events: 0, total_events: 120 }],
        error: null,
      },
      { raw: { id: 'c3', name: 'Winback', status: 'active', channel: 'push' }, messages: null, error: 'timeout' },
    ],
    skipped: 0,
  };
}

describe('Communications list', () => {
  beforeEach(() => {
    s.index = loading();
    s.health = loading();
    s.campaign = loading();
    s.message = loading();
  });

  it('shows a loading state while the index is read', () => {
    renderAt('/communications');
    expect(screen.getByText('Reading communications from connected sources')).toBeInTheDocument();
  });

  it('says what is missing when no communications source has data', () => {
    s.index = settled({ campaigns: [], skipped: 0 });
    s.health = settled({ communication_facts: 0, last_event_at: null });
    renderAt('/communications');
    expect(screen.getByTestId('comms-empty')).toHaveTextContent('No communications yet');
    expect(screen.getByRole('link', { name: 'Connect a communications source' })).toHaveAttribute('href', '/settings/integrations');
  });

  it('marks an unavailable read as unavailable, never as empty', () => {
    s.index = failed('comms offline');
    s.health = failed('health offline');
    renderAt('/communications');
    expect(screen.getByText(/Communications are unavailable right now\. comms offline/)).toBeInTheDocument();
    expect(screen.getByText('Pipeline health unavailable')).toBeInTheDocument();
    expect(screen.queryByTestId('comms-empty')).not.toBeInTheDocument();
  });

  it('renders real messages with provider marks, discloses failed campaigns, filters by channel and opens a message', () => {
    s.index = settled(populatedIndex());
    s.health = settled({ communication_facts: 520, last_event_at: '2026-10-01T10:00:00Z' });
    renderAt('/communications');

    const cards = screen.getAllByTestId('communication-card');
    expect(cards).toHaveLength(2);
    expect(within(cards[0]!).getByText('Upgrade Reminder')).toBeInTheDocument();
    expect(within(cards[0]!).getByText(/Email · hubspot · Spring Upgrade/)).toBeInTheDocument();
    expect(cards[0]!.querySelector('[data-brand-token="hubspot"]')).not.toBeNull();
    expect(within(cards[0]!).getByText('1,840')).toBeInTheDocument();
    expect(screen.getByTestId('comms-health')).toHaveTextContent('520 communication events observed');
    expect(screen.getByText(/Messages for 1 campaign could not be read \(Winback\)/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('comms-channel-sms'));
    expect(screen.getAllByTestId('communication-card')).toHaveLength(1);
    expect(screen.getByText('Cart nudge')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('comms-channel-agent'));
    expect(screen.getByTestId('comms-no-match')).toHaveTextContent('No Agent communications observed');

    fireEvent.click(screen.getByTestId('comms-channel-all'));
    fireEvent.change(screen.getByLabelText('Search communications'), { target: { value: 'nothing-like-this' } });
    expect(screen.getByTestId('comms-no-match')).toHaveTextContent('No communications match.');

    fireEvent.change(screen.getByLabelText('Search communications'), { target: { value: 'upgrade' } });
    fireEvent.click(screen.getByText('Upgrade Reminder'));
    expect(screen.getByTestId('location')).toHaveTextContent('/communications/c1/m1');
    expect(screen.getByText('Reading this communication')).toBeInTheDocument();
  });
});

describe('Communications index fan-out', () => {
  it('reads messages only for communications campaigns and reports failures per campaign', async () => {
    s.apiList = { campaigns: [hubspotCampaign, smsCampaign, { id: 'ad1', name: 'Paid Social', channel: 'paid_social' }], total: 3 };
    s.apiMessages = { c1: { items: [{ external_message_id: 'm1' }] }, c2: new Error('boom') };
    const index = await fetchCommsIndex();
    expect(index.campaigns.map(c => c.raw.id)).toEqual(['c1', 'c2']);
    expect(index.campaigns[0]!.messages).toHaveLength(1);
    expect(index.campaigns[1]!.messages).toBeNull();
    expect(index.campaigns[1]!.error).toBe('boom');
  });
});

describe('Communication detail', () => {
  beforeEach(() => {
    s.campaign = settled(hubspotCampaign);
    s.message = settled({
      message: { name: 'Upgrade Reminder', provider: 'hubspot', channel: 'email', subject_redacted: 'Your upgrade is ready, [name]', external_template_id: 'tpl-9', status: 'active', first_seen_at: '2026-09-24T00:00:00Z' },
      stats: { delivered: 1840, human_clicks: 210, replies: 12, bounces: 9, machine_events: 40, total_events: 400 },
      links: [{ link_id: 'https://example.test/upgrade', human_clicks: 180, unique_clickers: 150 }],
    });
    s.funnel = loading();
    s.recipients = {};
    s.journeys = loading();
    s.conversions = loading();
  });

  it('shows loading, then unavailable, for the message read', () => {
    s.message = loading();
    const { unmount } = renderAt('/communications/c1/m1');
    expect(screen.getByText('Reading this communication')).toBeInTheDocument();
    unmount();
    s.message = failed('not found');
    renderAt('/communications/c1/m1');
    expect(screen.getByText(/This communication is unavailable right now\. not found/)).toBeInTheDocument();
  });

  it('replays the retained subject in a channel frame and links to the campaign and Explore', () => {
    renderAt('/communications/c1/m1');
    expect(screen.getByRole('heading', { name: 'Upgrade Reminder' })).toBeInTheDocument();
    const replay = screen.getByTestId('comms-replay');
    expect(replay.querySelector('[data-replay="email"]')).not.toBeNull();
    expect(within(replay).getByText('Your upgrade is ready, [name]')).toBeInTheDocument();
    expect(within(replay).getByText(/body stays in hubspot/)).toBeInTheDocument();
    expect(within(screen.getByTestId('comms-kpis')).getByText('1,840')).toBeInTheDocument();
    expect(within(screen.getByTestId('comms-next')).getByText('Suspected machine activity')).toBeInTheDocument();
    expect(screen.getByTestId('comms-links')).toHaveTextContent('150 people');

    expect(screen.getByRole('link', { name: /Campaign: Spring Upgrade/ })).toHaveAttribute('href', '/campaigns/c1?tab=messages');
    expect(screen.getByRole('link', { name: /Open in Explore/ })).toHaveAttribute('href', '/explore');
    fireEvent.click(screen.getByRole('link', { name: 'Communications' }));
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/communications$/);
  });

  it('passes governed rates through: observed with a Wilson band, withheld below the minimum sample', () => {
    s.funnel = settled({
      modes: {
        human_qualified: {
          sent: 1900, delivered: 1840, opens: 700, clicks: 210, replies: 12,
          open_rate_result: { value: 0.3804, value_state: 'observed', sufficiency: { sample_size: 1840, min_required: 100, met: true }, uncertainty: { method: 'wilson', lower: 0.36, upper: 0.4 } },
          click_rate_result: { value: 0.1141, value_state: 'observed', sufficiency: { sample_size: 1840, min_required: 100, met: true }, uncertainty: { method: 'wilson', lower: 0.1, upper: 0.13 } },
          reply_rate_result: { value: null, value_state: 'insufficient_data', sufficiency: { sample_size: 1840, min_required: 5000, met: false }, uncertainty: null },
        },
        provider_reported: { sent: 1900, delivered: 1840, opens: 900, clicks: 260 },
      },
      delivery: { hard_bounces: 4, complaints: 1, unsubscribes: 7 },
      quality: {},
    });
    renderAt('/communications/c1/m1?tab=response');
    const ladder = screen.getByTestId('comms-ladder');
    expect(within(ladder).getByText('38.0%')).toBeInTheDocument();
    expect(ladder.querySelector('[data-step="replied"] [data-value-state="insufficient_data"]')).toHaveTextContent('Withheld: below the minimum sample');
    expect(screen.getByText(/Rates are withheld until the governed minimum sample is met/)).toBeInTheDocument();

    fireEvent.click(ladder.querySelector('[data-step="opened"]')!);
    const detail = screen.getByTestId('comms-step-detail');
    expect(detail).toHaveTextContent('95% interval (wilson): 36.0% to 40.0%');
    expect(detail).toHaveTextContent('minimum 100');
  });

  it('empty-states and error-states the campaign tabs', () => {
    s.funnel = failed('funnel offline');
    renderAt('/communications/c1/m1?tab=response');
    expect(screen.getByText(/The response ladder is unavailable right now\. funnel offline/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Journeys' }));
    expect(screen.getByText('Reading journeys')).toBeInTheDocument();
  });

  it('lists recipients with profile links and filters by stage', () => {
    s.recipients = {
      all: settled({ items: [
        { recipient_key: 'a1', recipient_display: 'alias-7f2', entity_id: 'u-42', stage: 'replied', delivered: 1, human_clicks: 2, replies: 1 },
        { recipient_key: 'a2', recipient_display: 'alias-9c1', entity_id: null, stage: 'delivered', delivered: 1, human_clicks: 0, replies: 0, bounced: true },
      ], stage_counts: { replied: 1, delivered: 1 } }),
      replied: settled({ items: [], stage_counts: {} }),
    };
    renderAt('/communications/c1/m1?tab=recipients');
    const rows = screen.getAllByTestId('comms-recipient');
    expect(rows).toHaveLength(2);
    expect(rows[0]!).toHaveAttribute('href', '/users/u-42');
    expect(rows[1]!.tagName).toBe('DIV');
    expect(within(rows[1]!).getByText('bounced')).toBeInTheDocument();

    fireEvent.click(rows[0]!);
    expect(screen.getByTestId('location')).toHaveTextContent('/users/u-42');
  });

  it('shows an empty stage instead of the whole list', () => {
    s.recipients = { all: settled({ items: [], stage_counts: {} }), replied: settled({ items: [], stage_counts: {} }) };
    renderAt('/communications/c1/m1?tab=recipients');
    expect(screen.getByTestId('comms-recipients-empty')).toHaveTextContent('No recipients observed');
    fireEvent.click(screen.getByRole('button', { name: 'Replied' }));
    expect(screen.getByTestId('comms-recipients-empty')).toHaveTextContent('No recipients at this stage.');
  });

  it('links journeys to the journey explorer and summarises outcomes', () => {
    s.journeys = settled({ items: [{ journey_id: 'j1', profile_id: 'u-42', stage_count: 4, converted: true, started_at: '2026-09-25T00:00:00Z' }], pagination: { has_more: false } });
    renderAt('/communications/c1/m1?tab=journeys');
    const journey = screen.getByTestId('comms-journey');
    expect(journey).toHaveTextContent('4 touchpoints');
    expect(journey).toHaveTextContent('Converted');
    fireEvent.click(journey);
    expect(screen.getByTestId('location')).toHaveTextContent('/users/u-42/journey');
  });

  it('summarises conversions and delivery outcomes, with an empty state', () => {
    s.conversions = settled({ items: [{ conversion_id: 'cv1', conversion_type: 'purchase', gross_value: 120 }, { conversion_id: 'cv2', conversion_type: 'purchase', gross_value: 80 }], pagination: { has_more: false } });
    s.funnel = settled({ modes: {}, delivery: { unsubscribes: 7, complaints: 1, hard_bounces: 4 }, quality: {} });
    const { unmount } = renderAt('/communications/c1/m1?tab=outcomes');
    const outcomes = screen.getByTestId('comms-outcomes');
    expect(outcomes).toHaveTextContent('Attributed conversions2');
    expect(outcomes).toHaveTextContent('$200');
    expect(screen.getByTestId('comms-delivery-outcomes')).toHaveTextContent('Unsubscribed7');
    unmount();

    s.conversions = settled({ items: [] });
    renderAt('/communications/c1/m1?tab=outcomes');
    expect(screen.getByText('No conversions attributed to this campaign yet.')).toBeInTheDocument();
  });
});
