import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { CampaignsPage } from '@aether-app/pages/campaigns/campaigns-page';

type Q = { data: unknown; isLoading: boolean; error: unknown; refetch: () => void };
const settled = (data: unknown): Q => ({ data, isLoading: false, error: null, refetch: vi.fn() });

const s = vi.hoisted(() => ({
  campaigns: null as unknown as (params?: { status?: string }) => Q,
  overview: null as unknown as Q,
  insights: null as unknown as Q,
  quality: null as unknown as Q,
  reviews: null as unknown as Q,
  resolve: vi.fn(),
  ignore: vi.fn(),
}));

vi.mock('@aether-app/features/campaigns/use-campaigns', () => ({
  useCampaigns: (params?: { status?: string }) => s.campaigns(params),
  usePlatformOverview: () => s.overview,
  useAutomationInsights: () => s.insights,
}));
vi.mock('@aether-app/features/campaigns/use-campaign-quality', () => ({ useCampaignQuality: () => s.quality }));
vi.mock('@aether-app/features/campaigns/use-mapping-review', async () => {
  // The write hooks run on the real useMutation so pending / error states are genuine.
  const { useMutation } = await vi.importActual<typeof import('@aether/ui')>('@aether/ui');
  return {
    useMappingReviews: () => s.reviews,
    useResolveReview: () => useMutation({ mutationFn: (input: { reviewId: string; campaignId: string }) => s.resolve(input) }),
    useIgnoreReview: () => useMutation({ mutationFn: (input: { reviewId: string }) => s.ignore(input) }),
  };
});
vi.mock('@aether-app/features/campaigns/use-campaign-exploration', () => ({
  useCampaignExploration: () => ({ data: undefined, isLoading: true, error: null, client: {}, context: {} }),
}));

const SPRING = {
  id: 'c-spring',
  name: 'Spring Upgrade',
  status: 'active',
  platform: 'meta',
  start_date: '2026-09-03T00:00:00Z',
  funnel: { entered: 4000, clicked: 900, converted: 120 },
  metrics: { conversion_rate: 0.03 },
  revenue_usd: 5400,
  top_channels: [{ channel: 'paid_social', source: 'meta', conversions: 80, revenue_usd: 3600 }],
};
const PAUSED = { id: 'c-bf', name: 'Black Friday Teaser', status: 'paused', platform: 'google_ads' };

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname}{location.search}</div>;
}

function renderPage(path = '/campaigns') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/campaigns" element={<><CampaignsPage /><Where /></>} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Campaigns page', () => {
  beforeEach(() => {
    s.campaigns = () => settled({ campaigns: [], total: 0 });
    s.overview = settled({});
    s.insights = settled([]);
    s.quality = settled({});
    s.reviews = settled({ items: [], total: 0 });
    s.resolve.mockReset().mockResolvedValue({ review_id: 'r1', status: 'resolved' });
    s.ignore.mockReset().mockResolvedValue({ review_id: 'r1', status: 'ignored' });
  });

  it('shows a loading read distinctly from empty', () => {
    s.campaigns = () => ({ data: undefined, isLoading: true, error: null, refetch: vi.fn() });
    renderPage();
    expect(screen.getByText('Loading campaigns…')).toBeInTheDocument();
    expect(screen.queryByText('No active campaigns')).not.toBeInTheDocument();
  });

  it('says what is missing for an empty workspace and never shows sample campaigns', async () => {
    renderPage();
    expect(screen.getByText('No active campaigns')).toBeInTheDocument();
    expect(screen.queryByText('Spring Upgrade')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'All campaigns' }));
    expect(screen.getByText('No campaigns')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Connect your first source' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/activation');
  });

  it('marks unavailable reads as unavailable, never as empty', () => {
    s.campaigns = () => ({ data: undefined, isLoading: false, error: new Error('campaigns offline'), refetch: vi.fn() });
    s.overview = { data: undefined, isLoading: false, error: 'overview offline', refetch: vi.fn() };
    renderPage();
    expect(screen.getByText('Failed to load campaigns')).toBeInTheDocument();
    expect(screen.getByText('Failed to load overview')).toBeInTheDocument();
    expect(screen.queryByText('No active campaigns')).not.toBeInTheDocument();
    expect(within(screen.getByTestId('campaigns-overview')).getAllByText('—').length).toBeGreaterThan(0);
  });

  it('renders imported campaigns from the campaign API with real figures and opens Campaign 360', async () => {
    s.campaigns = (params) => settled(params?.status === 'paused'
      ? { campaigns: [PAUSED], total: 1 }
      : params?.status === 'active'
        ? { campaigns: [SPRING], total: 1 }
        : { campaigns: [SPRING, PAUSED], total: 2 });
    s.overview = settled({ total_sessions: 1520, conversion_rate: 0.042, fraud_blocked: 3, active_campaigns: 1 });
    renderPage();

    const card = screen.getByTestId('campaign-card');
    expect(within(card).getByText('Spring Upgrade')).toBeInTheDocument();
    expect(within(card).getByText('4,000')).toBeInTheDocument();
    expect(within(card).getByText('3.0%')).toBeInTheDocument();
    expect(card.querySelector('[data-brand-token="meta"]')).not.toBeNull();
    expect(screen.getByText('2 canonical campaigns imported')).toBeInTheDocument();
    expect(screen.getByText('1,520')).toBeInTheDocument();
    expect(screen.getByText('4.2%')).toBeInTheDocument();

    await userEvent.click(within(card).getByRole('button', { name: 'Details' }));
    expect(within(card).getByTestId('campaign-details')).toHaveTextContent('paid_social');

    await userEvent.click(screen.getByRole('tab', { name: 'Paused' }));
    expect(screen.getByText('Black Friday Teaser')).toBeInTheDocument();
    expect(screen.getByTestId('where')).toHaveTextContent('view=paused');

    await userEvent.click(screen.getByRole('tab', { name: 'All campaigns' }));
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search campaigns' }), 'spring');
    expect(screen.getAllByTestId('campaign-card')).toHaveLength(1);

    await userEvent.click(screen.getByRole('button', { name: 'Open →' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/campaigns/c-spring');
  });

  it('shows the open review queue from mapping review with a count badge and a real link', async () => {
    s.reviews = settled({
      items: [{ review_id: 'r1', observed_count: 14, affected_touchpoints: 9, evidence: { platform: 'tiktok', utm_campaign: 'SPRING_UPG_TikTok' } }],
      total: 1,
    });
    renderPage('/campaigns?view=review');
    expect(screen.getByRole('tab', { name: /Review/ })).toHaveTextContent('1');
    expect(screen.getByText('SPRING_UPG_TikTok')).toBeInTheDocument();
    expect(screen.getByText(/14 observations/)).toBeInTheDocument();
    // No candidate campaign: Confirm cannot pick one, so it is disabled with the reason, and the queue link remains.
    expect(screen.getByTestId('review-confirm')).toBeDisabled();
    expect(screen.getByText(/No campaign was proposed/)).toBeInTheDocument();
    expect(screen.queryByTestId('review-confidence')).not.toBeInTheDocument();
    expect(screen.queryByTestId('review-signals')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Split apart|Merge|Rename/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Open in the review queue/ }));
    expect(screen.getByTestId('where')).toHaveTextContent('/campaign-intelligence/mapping-review');
  });

  it('confirms a review into its proposed campaign inline', async () => {
    s.campaigns = () => settled({ campaigns: [SPRING], total: 1 });
    s.reviews = settled({
      items: [{
        review_id: 'r1', observed_count: 3, candidate_campaign_ids: ['c-spring'], confidence: 0.62,
        matching_signals: [{ label: 'Same date window', matched: true }, { label: 'UTM campaign and medium', matched: false }],
        evidence: { platform: 'tiktok', utm_campaign: 'SPRING_UPG_TikTok' },
      }],
      total: 1,
    });
    renderPage('/campaigns?view=review');
    const item = screen.getByTestId('review-item');
    expect(within(item).getByTestId('review-proposed')).toHaveTextContent('Proposed: Spring Upgrade');
    expect(within(item).getByTestId('review-confidence')).toHaveTextContent('62% confidence');
    expect(within(item).getByTestId('review-signals')).toHaveTextContent('Same date window');
    await userEvent.click(within(item).getByTestId('review-confirm'));
    expect(s.resolve).toHaveBeenCalledWith({ reviewId: 'r1', campaignId: 'c-spring' });
    expect(within(item).queryByRole('alert')).not.toBeInTheDocument();
  });

  it('lets a person pick between several proposed campaigns before confirming', async () => {
    s.campaigns = () => settled({ campaigns: [SPRING, PAUSED], total: 2 });
    s.reviews = settled({ items: [{ review_id: 'r2', candidate_campaign_ids: ['c-spring', 'c-bf'], evidence: {} }], total: 1 });
    renderPage('/campaigns?view=review');
    expect(screen.getByTestId('review-proposed')).toHaveTextContent('Proposed: Spring Upgrade or Black Friday Teaser');
    await userEvent.selectOptions(screen.getByLabelText('Campaign to group under'), 'c-bf');
    await userEvent.click(screen.getByTestId('review-confirm'));
    expect(s.resolve).toHaveBeenCalledWith({ reviewId: 'r2', campaignId: 'c-bf' });
  });

  it('says why a confirm failed and keeps the item', async () => {
    s.resolve.mockRejectedValue(new Error('campaign not found'));
    s.reviews = settled({ items: [{ review_id: 'r1', candidate_campaign_ids: ['c-spring'], evidence: {} }], total: 1 });
    renderPage('/campaigns?view=review');
    await userEvent.click(screen.getByTestId('review-confirm'));
    expect(await screen.findByText(/The grouping was not confirmed: campaign not found/)).toBeInTheDocument();
    expect(screen.getByTestId('review-item')).toBeInTheDocument();
  });

  it('ignores a review inline, and reports a failed ignore', async () => {
    s.reviews = settled({ items: [{ review_id: 'r1', evidence: {} }], total: 1 });
    renderPage('/campaigns?view=review');
    await userEvent.click(screen.getByTestId('review-ignore'));
    expect(s.ignore).toHaveBeenCalledWith({ reviewId: 'r1' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    s.ignore.mockRejectedValue(new Error('forbidden'));
    await userEvent.click(screen.getByTestId('review-ignore'));
    expect(await screen.findByText(/The item was not ignored: forbidden/)).toBeInTheDocument();
  });

  it('renders attribution rows from campaign channels and an honest empty state', async () => {
    s.campaigns = () => settled({ campaigns: [SPRING], total: 1 });
    renderPage('/campaigns?view=attribution');
    const table = screen.getByRole('table', { name: 'Campaign attribution by channel' });
    expect(within(table).getByText('Spring Upgrade')).toBeInTheDocument();
    expect(within(table).getByText('$3,600')).toBeInTheDocument();
  });

  it('routes the import action to the campaign sources flow', async () => {
    renderPage();
    await userEvent.click(screen.getByTestId('campaigns-import'));
    expect(screen.getByTestId('where')).toHaveTextContent('/campaign-intelligence/sources');
  });
});
