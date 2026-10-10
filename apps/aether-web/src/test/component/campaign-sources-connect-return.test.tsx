import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { CampaignSourcesPage } from '@aether-app/pages/campaigns/campaign-sources-page';

// Reconciled Settings ↔ Campaign Sources bridge: the advertising connect deep
// link (Settings → Integrations advertising rows) carries a ?return= target;
// a genuine connect completion must navigate back there, while a cancel stays
// on the sources list and an off-origin return value is never honored.
const flow = vi.hoisted(() => ({
  platform: null as string | null,
  onDone: null as (() => void) | null,
  onCancel: null as (() => void) | null,
}));

vi.mock('@aether-app/features/campaigns/ad-connect-flow', () => ({
  AdConnectFlow: (props: {
    platform: string;
    onDone?: () => void;
    onCancel?: () => void;
  }) => {
    flow.platform = props.platform;
    flow.onDone = props.onDone ?? null;
    flow.onCancel = props.onCancel ?? null;
    return (
      <div data-testid="ad-connect-stub">
        <button type="button" onClick={() => flow.onDone?.()}>finish connect</button>
        <button type="button" onClick={() => flow.onCancel?.()}>cancel connect</button>
      </div>
    );
  },
}));

vi.mock('@aether-app/features/campaigns/use-campaign-sources', () => ({
  useCampaignSources: () => ({
    data: { tenant_id: 't1', count: 0, items: [] },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useSyncCampaignSource: () => ({ mutate: vi.fn(), isLoading: false }),
}));

vi.mock('@aether-app/features/integrations', () => ({
  useTenantIntegrationReadiness: () => ({ data: { items: [] } }),
  contextualReadiness: () => ({ connect: null }),
}));

function LocationProbe({ log }: { log: string[] }) {
  const location = useLocation();
  log.push(`${location.pathname}${location.search}`);
  return null;
}

function renderSources(initialPath: string) {
  const log: string[] = [];
  const utils = render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[initialPath]}>
          <LocationProbe log={log} />
          <CampaignSourcesPage />
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
  return { ...utils, log };
}

describe('Campaign Sources → Settings connect bridge (return leg)', () => {
  beforeEach(() => {
    flow.platform = null;
    flow.onDone = null;
    flow.onCancel = null;
  });

  it('navigates back to a validated return target after a successful connect', async () => {
    const user = userEvent.setup();
    const { log } = renderSources(
      '/campaign-intelligence/sources?connect=google_ads&return=%2Fsettings%2Fintegrations',
    );
    expect(await screen.findByTestId('ad-connect-stub')).toBeInTheDocument();
    log.length = 0; // start from the settled route

    await user.click(screen.getByRole('button', { name: 'finish connect' }));

    await waitFor(() => expect(log.at(-1)).toBe('/settings/integrations'));
  });

  it('clears connect and stays on the sources list when no return target is given', async () => {
    const user = userEvent.setup();
    const { log } = renderSources('/campaign-intelligence/sources?connect=google_ads');
    expect(await screen.findByTestId('ad-connect-stub')).toBeInTheDocument();
    log.length = 0;

    await user.click(screen.getByRole('button', { name: 'finish connect' }));

    await waitFor(() => expect(log.at(-1)).toBe('/campaign-intelligence/sources'));
  });

  it('never navigates to an off-origin return value (open-redirect guard)', async () => {
    const user = userEvent.setup();
    const { log } = renderSources(
      '/campaign-intelligence/sources?connect=google_ads&return=https%3A%2F%2Fevil.example%2Fphish',
    );
    expect(await screen.findByTestId('ad-connect-stub')).toBeInTheDocument();
    log.length = 0;

    await user.click(screen.getByRole('button', { name: 'finish connect' }));

    await waitFor(() => expect(log.at(-1)).toBe('/campaign-intelligence/sources'));
    expect(log.join('|')).not.toContain('evil.example');
  });

  it('cancelling never navigates — connect is cleared and the sources list stays', async () => {
    const user = userEvent.setup();
    const { log } = renderSources(
      '/campaign-intelligence/sources?connect=google_ads&return=%2Fsettings%2Fintegrations',
    );
    expect(await screen.findByTestId('ad-connect-stub')).toBeInTheDocument();
    log.length = 0;

    await user.click(screen.getByRole('button', { name: 'cancel connect' }));

    await waitFor(() => expect(log.at(-1)).toBe('/campaign-intelligence/sources'));
  });
});
