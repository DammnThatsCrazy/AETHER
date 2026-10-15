import { describe, expect, it } from 'vitest';
import { resolveStatusConfig } from './config';

describe('resolveStatusConfig', () => {
  it('uses the configured environment origins for staging and preview builds', () => {
    expect(
      resolveStatusConfig({
        VITE_STATUS_API_URL: ' https://api.staging.example/health ',
        VITE_STATUS_DOCS_URL: 'https://docs.staging.example',
        VITE_STATUS_AETHER_MARKETING_URL: 'https://aether.staging.example',
      }),
    ).toEqual({
      statusApiUrl: 'https://api.staging.example/health',
      docsUrl: 'https://docs.staging.example',
      aetherMarketingUrl: 'https://aether.staging.example',
    });
  });

  it('keeps the public production origins as safe defaults', () => {
    expect(resolveStatusConfig({ VITE_STATUS_API_URL: '' })).toEqual({
      statusApiUrl: '',
      docsUrl: 'https://docs.olympuslabsml.com',
      aetherMarketingUrl: 'https://aether.olympuslabsml.com',
    });
  });
});
