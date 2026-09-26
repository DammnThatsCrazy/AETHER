import { describe, expect, it } from 'vitest';
import { manualChunks } from '../../chunks';
import { resolveSite, siteHref, siteOrigins } from './site';

describe('resolveSite', () => {
  it('serves Olympus on the company hosts', () => {
    for (const host of ['olympuslabsml.com', 'www.olympuslabsml.com', 'staging.olympuslabsml.com', 'OlympusLabsML.com']) {
      expect(resolveSite(host, '', undefined)).toBe('olympus');
    }
  });

  it('serves Aether on product hosts and anything unrecognised', () => {
    for (const host of ['aether.olympuslabsml.com', 'aether.staging.olympuslabsml.com', 'pr-7.d39k0b8z1d75nj.amplifyapp.com', 'localhost']) {
      expect(resolveSite(host, '', undefined)).toBe('aether');
    }
  });

  it('lets a preview pick the site with ?site=', () => {
    expect(resolveSite('main.d1.amplifyapp.com', '?site=olympus', undefined)).toBe('olympus');
    expect(resolveSite('olympuslabsml.com', '?site=aether', undefined)).toBe('aether');
    expect(resolveSite('olympuslabsml.com', '?site=nope', undefined)).toBe('olympus');
  });

  it('prefers the build-time site over host and query', () => {
    expect(resolveSite('olympuslabsml.com', '?site=olympus', 'aether')).toBe('aether');
    expect(resolveSite('aether.olympuslabsml.com', '', 'olympus')).toBe('olympus');
  });
});

describe('siteHref', () => {
  const origins = { olympus: 'https://olympuslabsml.com', aether: 'https://aether.olympuslabsml.com' };

  it('keeps same-site links relative so every host works', () => {
    expect(siteHref('aether', 'aether', '/pricing', origins)).toBe('/pricing');
    expect(siteHref('olympus', 'olympus', 'company', origins)).toBe('/company');
  });

  it('makes cross-site links absolute', () => {
    expect(siteHref('olympus', 'aether', '/', origins)).toBe('https://aether.olympuslabsml.com/');
    expect(siteHref('aether', 'olympus', '/research', origins)).toBe('https://olympuslabsml.com/research');
  });

  it('passes through mailto and absolute URLs', () => {
    expect(siteHref('aether', 'olympus', 'mailto:contact@olympuslabsml.com', origins)).toBe('mailto:contact@olympuslabsml.com');
    expect(siteHref('aether', 'olympus', 'https://example.com/x', origins)).toBe('https://example.com/x');
  });
});

describe('siteOrigins', () => {
  it('defaults to production and trims trailing slashes', () => {
    expect(siteOrigins({})).toEqual({ olympus: 'https://olympuslabsml.com', aether: 'https://aether.olympuslabsml.com' });
    expect(
      siteOrigins({ VITE_SITE_OLYMPUS_URL: 'https://staging.olympuslabsml.com/', VITE_SITE_AETHER_URL: ' https://aether.staging.olympuslabsml.com// ' }),
    ).toEqual({ olympus: 'https://staging.olympuslabsml.com', aether: 'https://aether.staging.olympuslabsml.com' });
  });
});

describe('manualChunks', () => {
  const nm = (pkg: string, file = 'index.js') => `/repo/node_modules/${pkg}/${file}`;

  it('keeps React, ReactDOM and the scheduler together (no startup cycle)', () => {
    expect(new Set([manualChunks(nm('react')), manualChunks(nm('react-dom', 'client.js')), manualChunks(nm('scheduler'))])).toEqual(
      new Set(['react']),
    );
    expect(manualChunks(nm('react-router-dom'))).toBe('router');
    expect(manualChunks(nm('react-is'))).toBeUndefined();
  });
});
