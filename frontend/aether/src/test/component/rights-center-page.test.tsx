import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { RightsCenterPage } from '@aether-app/pages/legal/rights-center-page';

const mocks = vi.hoisted(() => ({
  policies: vi.fn(),
  envelopes: vi.fn(),
  decisions: vi.fn(),
  evidenceManifests: vi.fn(),
  impacts: vi.fn(),
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    rights: {
      policies: mocks.policies,
      envelopes: mocks.envelopes,
      decisions: mocks.decisions,
      evidenceManifests: mocks.evidenceManifests,
      impacts: mocks.impacts,
    },
  },
}));

const emptyResponse = () => Promise.resolve({ items: [] });

describe('RightsCenterPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.policies.mockImplementation(emptyResponse);
    mocks.envelopes.mockImplementation(emptyResponse);
    mocks.decisions.mockImplementation(emptyResponse);
    mocks.evidenceManifests.mockImplementation(emptyResponse);
    mocks.impacts.mockImplementation(emptyResponse);
  });

  it('renders authority-backed successful empty states', async () => {
    render(<RightsCenterPage />);

    expect(await screen.findByText('Rights Center')).toBeInTheDocument();
    expect(screen.getByText('No policy authority is registered for this tenant')).toBeInTheDocument();
    expect(screen.getByText('No decisions recorded')).toBeInTheDocument();
    expect(screen.getByText('No rights impacts recorded')).toBeInTheDocument();
  });

  it('renders unavailable authority instead of treating a failed request as empty', async () => {
    mocks.policies.mockRejectedValueOnce(new Error('rights backend offline'));

    render(<RightsCenterPage />);

    expect(await screen.findByText('Rights Center unavailable')).toBeInTheDocument();
    expect(screen.getByText('rights backend offline')).toBeInTheDocument();
    expect(screen.queryByText('No policy authority is registered for this tenant')).not.toBeInTheDocument();
  });
});
