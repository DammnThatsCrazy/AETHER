import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider, queryCache } from '@aether/ui';
import { DeploymentsPage, DeploymentDetailPage } from '@aether-app/pages/deployments';

// jsdom 25 does not implement <dialog>.showModal()/close(); the shared Modal
// component relies on them. Polyfill minimally for these tests.
beforeAll(() => {
  if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
      this.setAttribute('open', '');
    };
    HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
      this.removeAttribute('open');
      this.dispatchEvent(new Event('close'));
    };
  }

  // The shared queryCache tracks in-flight fetches with `promise.finally(...)`,
  // which leaks an unhandled rejection when a fetcher rejects even though the
  // UI handles the error (useQuery sets its error state). Patch it test-locally
  // so the error-state test does not trip vitest's unhandled-error detector.
  const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

/** Badge text can collide with filter <option> text; scope to badge elements. */
function getBadge(text: string): HTMLElement {
  const match = screen.getAllByText(text).find(el => el.classList.contains('ui-badge'));
  expect(match).toBeDefined();
  return match as HTMLElement;
}

const mocks = vi.hoisted(() => ({
  fetchAgentDeployments: vi.fn(),
  fetchAgentDeployment: vi.fn(),
  fetchAgentDeploymentHealth: vi.fn(),
  fetchAgentDeploymentActivity: vi.fn(),
  createAgentDeployment: vi.fn(),
  updateAgentDeployment: vi.fn(),
  pauseAgentDeployment: vi.fn(),
  reactivateAgentDeployment: vi.fn(),
  revokeAgentDeployment: vi.fn(),
  archiveAgentDeployment: vi.fn(),
}));

vi.mock('@aether-app/features/deployments/api', () => mocks);

const DEPLOYMENT_FIXTURES = [
  {
    id: 'dep_001',
    tenant_id: 'tenant_demo_001',
    agent_id: 'agent_support_v2',
    display_name: 'Support Bot — Discord',
    external_platform: 'discord_bot',
    environment: 'production',
    status: 'active',
    consent_mode: 'platform_managed',
    allowed_event_families: ['agent.message'],
    required_consent_purposes: ['analytics'],
    capability_scopes: ['observe:conversations'],
    event_count_24h: 4210,
    accepted_count_24h: 4102,
    rejected_count_24h: 61,
    error_count_24h: 12,
    consent_blocked_count_24h: 35,
    health_score: 0.97,
    first_seen_at: '2026-05-02T09:15:00.000Z',
    last_seen_at: '2026-07-08T21:42:00.000Z',
    last_event_at: '2026-07-08T21:42:00.000Z',
    created_at: '2026-05-01T14:00:00.000Z',
    updated_at: '2026-07-01T10:30:00.000Z',
  },
  {
    id: 'dep_002',
    tenant_id: 'tenant_demo_001',
    agent_id: 'agent_concierge_v1',
    display_name: 'Shopping Concierge — Shopify',
    external_platform: 'shopify_app',
    environment: 'production',
    status: 'paused',
    consent_mode: 'tenant_managed',
    allowed_event_families: [],
    required_consent_purposes: [],
    capability_scopes: [],
    event_count_24h: 0,
    accepted_count_24h: 0,
    rejected_count_24h: 0,
    error_count_24h: 0,
    consent_blocked_count_24h: 0,
    health_score: null,
    first_seen_at: null,
    last_seen_at: null,
    last_event_at: null,
    created_at: '2026-04-10T12:00:00.000Z',
    updated_at: '2026-07-07T09:00:00.000Z',
  },
];

function renderListPage() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={['/deployments']}>
        <Routes>
          <Route path="/deployments" element={<DeploymentsPage />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

function renderDetailPage(id: string) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[`/deployments/${id}`]}>
        <Routes>
          <Route path="/deployments/:id" element={<DeploymentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  queryCache.invalidatePrefix('agent-deployments');
  mocks.fetchAgentDeployments.mockResolvedValue({ deployments: DEPLOYMENT_FIXTURES, notConfigured: false });
  mocks.fetchAgentDeployment.mockResolvedValue(DEPLOYMENT_FIXTURES[0]);
  mocks.fetchAgentDeploymentHealth.mockResolvedValue({
    event_count_24h: 4210,
    accepted_count_24h: 4102,
    rejected_count_24h: 61,
    error_count_24h: 12,
    consent_blocked_count_24h: 35,
    health_score: 0.97,
  });
  mocks.fetchAgentDeploymentActivity.mockResolvedValue([
    { id: 'act_001', action: 'created', actor: 'alex@acme.io', request_id: 'req_a1', occurred_at: '2026-05-01T14:00:00.000Z' },
  ]);
  mocks.pauseAgentDeployment.mockResolvedValue({ status: 'paused' });
  mocks.revokeAgentDeployment.mockResolvedValue({ status: 'revoked' });
  mocks.archiveAgentDeployment.mockResolvedValue({ status: 'archived' });
});

describe('Aether Deployments page', () => {
  it('renders deployment fixtures with status badges and health counters', async () => {
    renderListPage();
    await waitFor(() => expect(screen.getByText('Support Bot — Discord')).toBeInTheDocument());
    expect(screen.getByText('Shopping Concierge — Shopify')).toBeInTheDocument();
    expect(getBadge('active')).toBeInTheDocument();
    expect(getBadge('paused')).toBeInTheDocument();
    expect(screen.getByText('4,210')).toBeInTheDocument();
    expect(screen.getByText('4,102')).toBeInTheDocument();
    expect(screen.getByText(/Aether observes deployments — it does not publish, host, or execute agents\./)).toBeInTheDocument();
  });

  it('shows the empty state when there are no deployments', async () => {
    mocks.fetchAgentDeployments.mockResolvedValue({ deployments: [], notConfigured: false });
    renderListPage();
    await waitFor(() => expect(screen.getByText('No external agent deployments yet')).toBeInTheDocument());
  });

  it('shows the not-configured state when telemetry is not enabled', async () => {
    mocks.fetchAgentDeployments.mockResolvedValue({ deployments: [], notConfigured: true });
    renderListPage();
    await waitFor(() => expect(screen.getByText('External agent telemetry is not configured')).toBeInTheDocument());
  });

  it('shows the error state when the list request fails', async () => {
    mocks.fetchAgentDeployments.mockRejectedValue(new Error('boom'));
    renderListPage();
    await waitFor(() => expect(screen.getByText('Failed to load deployments')).toBeInTheDocument());
    expect(screen.getByText('boom')).toBeInTheDocument();
  });
});

describe('Aether Deployment detail page', () => {
  it('renders health counters, configuration, and activity feed', async () => {
    renderDetailPage('dep_001');
    await waitFor(() => expect(screen.getByText('Support Bot — Discord')).toBeInTheDocument());
    expect(screen.getByText('Events 24h')).toBeInTheDocument();
    expect(screen.getByText('Consent blocked 24h')).toBeInTheDocument();
    expect(screen.getByText('created')).toBeInTheDocument();
    expect(screen.getByText('alex@acme.io')).toBeInTheDocument();
    expect(screen.getByText('agent.message')).toBeInTheDocument();
  });

  it('pauses an active deployment without confirmation', async () => {
    renderDetailPage('dep_001');
    await waitFor(() => expect(screen.getByText('Pause')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Pause'));
    await waitFor(() => expect(mocks.pauseAgentDeployment).toHaveBeenCalledWith('dep_001'));
  });

  it('requires confirmation before revoking a deployment', async () => {
    renderDetailPage('dep_001');
    await waitFor(() => expect(screen.getByText('Revoke')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Revoke'));
    expect(mocks.revokeAgentDeployment).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText('Revoke deployment?')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Revoke deployment'));
    await waitFor(() => expect(mocks.revokeAgentDeployment).toHaveBeenCalledWith('dep_001'));
  });

  it('cancelling the revoke confirmation does not fire the mutation', async () => {
    renderDetailPage('dep_001');
    await waitFor(() => expect(screen.getByText('Revoke')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Revoke'));
    await waitFor(() => expect(screen.getByText('Revoke deployment?')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Cancel'));
    expect(mocks.revokeAgentDeployment).not.toHaveBeenCalled();
  });
});
