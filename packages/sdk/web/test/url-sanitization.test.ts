// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest';

import {
  configureUrlSanitization,
  getCampaignContext,
  getPageContext,
  sanitizeSearch,
  sanitizeUrl,
} from '../src/utils';

afterEach(() => {
  // Reset module-level sanitization state to privacy-safe defaults.
  configureUrlSanitization({});
  window.history.replaceState({}, '', '/');
});

describe('sanitizeUrl', () => {
  it('strips aether_ref, aether_cid, click IDs, and token params', () => {
    const url =
      'https://app.example.test/landing?utm_source=partner&aether_ref=tok-1' +
      '&aether_cid=c-1&gclid=g-1&access_token=a-1&keep=yes';
    const sanitized = sanitizeUrl(url);
    expect(sanitized).toContain('utm_source=partner');
    expect(sanitized).toContain('keep=yes');
    expect(sanitized).not.toContain('aether_ref');
    expect(sanitized).not.toContain('aether_cid');
    expect(sanitized).not.toContain('gclid');
    expect(sanitized).not.toContain('access_token');
  });

  it('strips fragments (OAuth implicit tokens live there)', () => {
    expect(sanitizeUrl('https://x.test/p?a=1#access_token=abc')).toBe(
      'https://x.test/p?a=1',
    );
  });

  it('drops unparsable values that visibly carry a sensitive param', () => {
    expect(sanitizeUrl('::not a url::aether_ref=leak')).toBe('');
  });

  it('honors additional configured params and the disable toggle', () => {
    configureUrlSanitization({ additionalParams: ['patient_id'] });
    expect(sanitizeUrl('https://x.test/p?patient_id=99&ok=1')).toBe(
      'https://x.test/p?ok=1',
    );

    configureUrlSanitization({ enabled: false });
    expect(sanitizeUrl('https://x.test/p?aether_ref=tok')).toContain('aether_ref=tok');
  });
});

describe('sanitizeSearch', () => {
  it('filters sensitive params from a query string', () => {
    expect(sanitizeSearch('?utm_source=x&aether_ref=tok')).toBe('?utm_source=x');
    expect(sanitizeSearch('?aether_ref=tok')).toBe('');
  });
});

describe('getPageContext', () => {
  it('never transmits aether_ref or fragments', () => {
    window.history.replaceState(
      {},
      '',
      '/page?utm_source=x&aether_ref=tok#secret-fragment',
    );
    const ctx = getPageContext();
    expect(ctx.url).not.toContain('aether_ref');
    expect(ctx.url).not.toContain('secret-fragment');
    expect(ctx.search).toBe('?utm_source=x');
    expect(ctx.hash).toBe('');
  });
});

describe('getCampaignContext', () => {
  it('does not classify referrers client-side — referrerType is always unknown', () => {
    Object.defineProperty(document, 'referrer', {
      value: 'https://www.google.com/search?q=aether',
      configurable: true,
    });
    window.history.replaceState({}, '', '/?utm_source=google&gclid=g-1');

    const ctx = getCampaignContext();

    expect(ctx.referrerType).toBe('unknown');
    expect(ctx.source).toBe('google');
    expect(ctx.clickId).toBe('g-1');
    expect(ctx.referrerDomain).toBe('www.google.com');
  });
});
