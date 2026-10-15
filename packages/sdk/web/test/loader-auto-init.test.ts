import { describe, expect, it } from 'vitest';

import {
  DEFAULT_AUTO_INIT,
  normalizeEndpoint,
  readScriptAttributes,
  resolveConfig,
} from '../src/loader/auto-init';

describe('one-tag auto-init', () => {
  describe('readScriptAttributes', () => {
    it('reads the mapped data-* attributes from a DOM element', () => {
      const values: Record<string, string> = {
        'data-key': 'pk_live_abc',
        'data-site': 'site_1',
        'data-autocapture': 'off',
      };
      const script = { getAttribute: (name: string) => values[name] ?? null };

      expect(readScriptAttributes(script as unknown as HTMLScriptElement)).toEqual({
        'data-key': 'pk_live_abc',
        'data-site': 'site_1',
        'data-autocapture': 'off',
      });
    });

    it('ignores absent and empty attributes', () => {
      const script = { getAttribute: (name: string) => (name === 'data-key' ? '' : null) };
      expect(readScriptAttributes(script as unknown as HTMLScriptElement)).toEqual({});
    });

    it('accepts a plain record so the contract is testable without a DOM', () => {
      expect(readScriptAttributes({ 'data-key': 'k' })).toEqual({ 'data-key': 'k' });
    });
  });

  describe('normalizeEndpoint', () => {
    it('strips trailing slashes so path joins cannot produce //v1/batch', () => {
      expect(normalizeEndpoint('https://api.aether.io/')).toEqual({
        endpoint: 'https://api.aether.io',
        error: null,
      });
      expect(normalizeEndpoint('https://api.aether.io///')).toEqual({
        endpoint: 'https://api.aether.io',
        error: null,
      });
    });

    it('preserves a real path prefix', () => {
      expect(normalizeEndpoint('https://edge.example.com/ingest/')).toEqual({
        endpoint: 'https://edge.example.com/ingest',
        error: null,
      });
    });

    it('rejects cleartext http off localhost', () => {
      const result = normalizeEndpoint('http://api.aether.io');
      expect(result.endpoint).toBeNull();
      expect(result.error).toContain('must use https');
    });

    it('allows http on localhost for development', () => {
      expect(normalizeEndpoint('http://localhost:8000')).toEqual({
        endpoint: 'http://localhost:8000',
        error: null,
      });
      expect(normalizeEndpoint('http://127.0.0.1:8000/').endpoint).toBe('http://127.0.0.1:8000');
    });

    it('rejects a non-URL', () => {
      const result = normalizeEndpoint('not a url');
      expect(result.endpoint).toBeNull();
      expect(result.error).toContain('not a valid URL');
    });
  });

  describe('resolveConfig', () => {
    const minimal = { 'data-key': 'pk_live_abc', 'data-site': 'site_1' };

    it('applies the documented defaults', () => {
      const { config, errors, warnings } = resolveConfig(minimal);
      expect(errors).toEqual([]);
      expect(warnings).toEqual([]);
      expect(config).toEqual({
        sdkKey: 'pk_live_abc',
        siteId: 'site_1',
        endpoint: DEFAULT_AUTO_INIT.endpoint,
        autocapture: 'safe',
        consentMode: 'deferred',
        debug: false,
        releaseChannel: 'managed_stable',
      });
    });

    it('defaults to the canonical ingestion host, not the CDN host', () => {
      // A snippet that ships no data-endpoint must reach the same API host the
      // SDK itself defaults to. These are separate origins by design.
      expect(DEFAULT_AUTO_INIT.endpoint).toBe('https://api.aether.io');
    });

    it('reports both missing required attributes at once', () => {
      const { config, errors } = resolveConfig({});
      expect(config).toBeNull();
      expect(errors).toEqual([
        'missing data-key (publishable SDK key)',
        'missing data-site (site id)',
      ]);
    });

    it('treats a whitespace-only value as missing', () => {
      const { config, errors } = resolveConfig({ 'data-key': '   ', 'data-site': 's' });
      expect(config).toBeNull();
      expect(errors).toEqual(['missing data-key (publishable SDK key)']);
    });

    it('returns null config when the endpoint is invalid', () => {
      const { config, errors } = resolveConfig({ ...minimal, 'data-endpoint': 'http://evil.test' });
      expect(config).toBeNull();
      expect(errors.some((e) => e.includes('must use https'))).toBe(true);
    });

    it('warns and falls back on an unknown enum value', () => {
      const { config, warnings } = resolveConfig({ ...minimal, 'data-autocapture': 'everything' });
      expect(config?.autocapture).toBe('safe');
      expect(warnings).toEqual([
        'unknown data-autocapture "everything"; falling back to "safe"',
      ]);
    });

    it('accepts every documented enum value', () => {
      for (const autocapture of ['off', 'safe', 'custom']) {
        expect(resolveConfig({ ...minimal, 'data-autocapture': autocapture }).config?.autocapture).toBe(
          autocapture,
        );
      }
      for (const consent of ['none', 'callback', 'deferred', 'required']) {
        expect(resolveConfig({ ...minimal, 'data-consent': consent }).config?.consentMode).toBe(consent);
      }
      for (const channel of [
        'managed_stable',
        'security_auto',
        'compatible_auto',
        'patch_auto',
        'pinned',
      ]) {
        expect(resolveConfig({ ...minimal, 'data-channel': channel }).config?.releaseChannel).toBe(
          channel,
        );
      }
    });

    it('is case-insensitive for enum values', () => {
      expect(resolveConfig({ ...minimal, 'data-autocapture': 'OFF' }).config?.autocapture).toBe('off');
    });

    it('parses the boolean-ish forms of data-debug', () => {
      for (const truthy of ['1', 'true', 'yes', 'on', 'TRUE']) {
        expect(resolveConfig({ ...minimal, 'data-debug': truthy }).config?.debug).toBe(true);
      }
      for (const falsy of ['0', 'false', 'no', 'off']) {
        expect(resolveConfig({ ...minimal, 'data-debug': falsy }).config?.debug).toBe(false);
      }
    });

    it('warns rather than failing on an unparseable data-debug', () => {
      const { config, warnings } = resolveConfig({ ...minimal, 'data-debug': 'maybe' });
      expect(config?.debug).toBe(false);
      expect(warnings).toEqual(['data-debug "maybe" is not a boolean; ignoring']);
    });

    it('lets explicit overrides win over attributes', () => {
      const { config } = resolveConfig(minimal, {
        overrides: { endpoint: 'https://edge.example.com', debug: true },
      });
      expect(config?.endpoint).toBe('https://edge.example.com');
      expect(config?.debug).toBe(true);
    });

    it('records the install mode for fleet attribution', () => {
      expect(resolveConfig(minimal).installMode).toBe('cdn_auto');
      expect(resolveConfig(minimal, { installMode: 'npm' }).installMode).toBe('npm');
    });

    it('still reports warnings alongside a fatal error', () => {
      const { config, warnings } = resolveConfig({ 'data-autocapture': 'nope' });
      expect(config).toBeNull();
      expect(warnings).toHaveLength(1);
    });
  });
});
