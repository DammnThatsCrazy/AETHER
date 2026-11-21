import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider, ToastProvider, queryCache } from '@aether/ui';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  linkWallet: vi.fn(),
  linkKey: vi.fn(),
  linkTenantPush: vi.fn(),
  oauthStart: vi.fn(),
  oauthComplete: vi.fn(),
  sync: vi.fn(),
  syncAll: vi.fn(),
  disconnect: vi.fn(),
  revoke: vi.fn(),
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({ api: { venueLinks: mocks } }));

import { VenueLinksPanel, VenueOAuthReturnPage } from '@aether-app/pages/derivatives/venue-links-panel';

function renderPanel(node: React.ReactNode) {
  return render(<ThemeProvider><ToastProvider>{node}</ToastProvider></ThemeProvider>);
}

const LINK = {
  link_id: 'val_1', venue: 'polymarket', subject_id: 'member_1', account_ref: '0xabc',
  method: 'wallet_proof', source_relationship: 'personal_account', status: 'active',
  sync_state: { synced_at: '2026-11-20T10:00:00Z' },
};

describe('VenueLinksPanel', () => {
  beforeEach(() => {
    queryCache.clear();
    Object.values(mocks).forEach(m => m.mockReset());
  });

  it('lists links with their source and offers lifecycle actions', async () => {
    mocks.list.mockResolvedValue({ items: [LINK] });
    mocks.disconnect.mockResolvedValue({});
    renderPanel(<VenueLinksPanel />);
    expect(await screen.findByText('0xabc')).toBeInTheDocument();
    expect(screen.getByText("Member's own account")).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }));
    await waitFor(() => expect(mocks.disconnect).toHaveBeenCalledWith('val_1'));
  });

  it('shows wallet fields for wallet venues and key fields for key venues', async () => {
    mocks.list.mockResolvedValue({ items: [] });
    renderPanel(<VenueLinksPanel />);
    expect(await screen.findByText('No linked venue accounts')).toBeInTheDocument();
    expect(screen.getByLabelText('Wallet address')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Venue'), { target: { value: 'kalshi' } });
    expect(await screen.findByLabelText('Read-only API key (or key id)')).toBeInTheDocument();
    expect(screen.queryByLabelText('Wallet address')).not.toBeInTheDocument();
  });

  it('submits a key link with read-only scope and no empty secrets', async () => {
    mocks.list.mockResolvedValue({ items: [] });
    mocks.linkKey.mockResolvedValue({});
    renderPanel(<VenueLinksPanel />);
    await screen.findByText('No linked venue accounts');
    fireEvent.change(screen.getByLabelText('Venue'), { target: { value: 'bybit' } });
    fireEvent.change(await screen.findByLabelText('Member (subject id)'), { target: { value: 'm1' } });
    fireEvent.change(screen.getByLabelText('Consent receipt id'), { target: { value: 'cr1' } });
    fireEvent.change(screen.getByLabelText('Venue account reference'), { target: { value: 'uid-1' } });
    fireEvent.change(screen.getByLabelText('Read-only API key (or key id)'), { target: { value: 'k' } });
    fireEvent.click(screen.getByRole('button', { name: 'Link account' }));
    await waitFor(() => expect(mocks.linkKey).toHaveBeenCalledWith({
      subject_id: 'm1', venue: 'bybit', consent_receipt_id: 'cr1', account_ref: 'uid-1', api_key: 'k', scopes: ['read'],
    }));
  });
});

describe('VenueOAuthReturnPage', () => {
  beforeEach(() => Object.values(mocks).forEach(m => m.mockReset()));

  it('redeems the state and code exactly once', async () => {
    mocks.oauthComplete.mockResolvedValue({});
    window.history.pushState({}, '', '/derivatives/oauth/return?state=s1&code=c1');
    renderPanel(<VenueOAuthReturnPage />);
    expect(await screen.findByText(/The account is linked/)).toBeInTheDocument();
    expect(mocks.oauthComplete).toHaveBeenCalledTimes(1);
    expect(mocks.oauthComplete).toHaveBeenCalledWith({ state: 's1', code: 'c1' });
  });

  it('reports a venue denial without redeeming', async () => {
    window.history.pushState({}, '', '/derivatives/oauth/return?error=access_denied');
    renderPanel(<VenueOAuthReturnPage />);
    expect(await screen.findByText('Linking did not finish')).toBeInTheDocument();
    expect(mocks.oauthComplete).not.toHaveBeenCalled();
  });
});
