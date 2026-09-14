import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LaunchPackPage } from '../../../marketing/src/LaunchPackPage';
import { getLaunchPackPage } from '../../../marketing/src/content-loader';

describe('launch-pack page rendering', () => {
  it('keeps ordered procedures as semantic lists with wrapped item text', () => {
    const page = getLaunchPackPage('Aether', '/developers');
    if (page === undefined) throw new Error('Aether developers launch-pack page is missing');

    render(<LaunchPackPage page={page} />);

    const orderedList = screen
      .getAllByRole('list')
      .find((list) => list.tagName.toLowerCase() === 'ol');
    expect(orderedList).toBeDefined();
    expect(orderedList?.querySelectorAll('li')).toHaveLength(8);
    expect(orderedList).toHaveTextContent(
      'Choose the smallest connection path: SDK, connector, webhook, import, API, or controlled agent/service observation.',
    );
  });

  it('makes joint legal content available to both public shells', () => {
    const privacy = getLaunchPackPage('Aether', '/legal/privacy');
    const terms = getLaunchPackPage('Olympus Labs', '/legal/terms');

    expect(privacy?.brand).toBe('Olympus Labs + Aether');
    expect(terms?.brand).toBe('Olympus Labs + Aether');
    expect(privacy?.body).toContain('privacy');
    expect(terms?.body).toContain('terms');
  });
});
