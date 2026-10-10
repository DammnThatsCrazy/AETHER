import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { App } from '@site/app/app';
import { leaveFor } from './leave';

vi.mock('./leave', () => ({ leaveFor: vi.fn() }));
vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

/**
 * Every route the previous Aether marketing app published in its sitemap
 * (apps/marketing-aether/seo-data.json), except the ones the unified site
 * serves at the same path. Each must land somewhere other than the 404 page.
 */
const LEGACY_PATHS = [
  '/solutions', '/developers', '/integrations', '/resources', '/company',
  '/platform/identity-resolution', '/platform/intelligence-graph', '/platform/journey-intelligence',
  '/platform/campaign-intelligence', '/platform/communications-intelligence',
  '/platform/financial-observability', '/platform/agent-access-intelligence',
  '/platform/rewards-and-activation', '/platform/outcome-attribution',
  '/platform/governance-and-consent', '/platform/integrations-and-data-quality',
  '/solutions/customer-intelligence', '/solutions/commerce', '/solutions/saas', '/solutions/fintech',
  '/solutions/web3', '/solutions/ai-native-businesses', '/solutions/enterprise',
  '/solutions/public-sector', '/solutions/agent-governance', '/solutions/communications',
  '/solutions/ecommerce', '/solutions/financial-services', '/solutions/operations',
  '/architecture', '/campaign-attribution', '/faq', '/governance', '/identity-resolution',
  '/intelligence-graph', '/perspectives', '/product', '/profile-360', '/proof-partner',
  '/proof/benchmark', '/proof/customer-case-study', '/proof/customer-outcomes',
  '/proof/methodology', '/proof/research-brief', '/start-pilot', '/stories',
  '/developers/api-reference', '/developers/changelog', '/developers/events',
  '/developers/integrations', '/developers/quickstart/android', '/developers/quickstart/backend',
  '/developers/quickstart/electron', '/developers/quickstart/ios',
  '/developers/quickstart/react-native', '/developers/quickstart/rest', '/developers/quickstart/web',
  '/developers/sdk/android', '/developers/sdk/ios', '/developers/sdk/react-native',
  '/developers/sdk/web', '/developers/start-here', '/developers/troubleshooting',
];

let landedAt = '';
function Probe() {
  const location = useLocation();
  landedAt = `${location.pathname}${location.search}`;
  return null;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App site="aether" />
      <Probe />
    </MemoryRouter>,
  );
}

describe('Legacy Aether marketing URLs', () => {
  afterEach(() => {
    vi.mocked(leaveFor).mockClear();
    document.title = '';
  });

  it('detects the 404 page (control)', () => {
    renderAt('/no-such-page');
    expect(document.title).toContain('Page not found');
  });

  it.each(LEGACY_PATHS)('%s does not land on the 404 page', (path) => {
    renderAt(path);
    expect(document.title).not.toContain('Page not found');
    expect(screen.queryByRole('heading', { level: 1, name: /not found/i })).toBeNull();
  });

  it.each([
    ['/platform/identity-resolution', '/platform/profiles'],
    ['/platform/governance-and-consent', '/trust/governance'],
    ['/solutions/fintech', '/applications'],
    ['/integrations', '/connect'],
    ['/connections', '/connect'],
    ['/start-pilot', '/contact?type=pilot'],
    ['/developers/quickstart/ios', '/docs/quickstart-ios'],
    ['/developers/sdk/react-native', '/docs/sdk-react-native'],
    ['/developers/unknown-page', '/docs'],
    ['/faq', '/docs/faq'],
  ])('redirects %s to %s', (from, to) => {
    renderAt(from);
    expect(landedAt).toBe(to);
  });

  it('sends pages that moved to Olympus Labs to that site', () => {
    renderAt('/perspectives');
    expect(leaveFor).toHaveBeenCalledWith('https://olympuslabsml.com/research');
    expect(screen.getByRole('link', { name: 'Olympus Labs' }).getAttribute('href')).toBe(
      'https://olympuslabsml.com/research',
    );
  });
});
