import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { DemoTenantBanner } from './demo-tenant-banner';

describe('DemoTenantBanner', () => {
  it('discloses backend-seeded synthetic records and their dataset version', () => {
    const html = renderToStaticMarkup(
      <DemoTenantBanner tenantName="Aether Demo" datasetVersion="v1" />,
    );

    expect(html).toContain('Demo tenant: Aether Demo');
    expect(html).toContain('synthetic records were seeded into the backend');
    expect(html).toContain('(v1)');
    expect(html).toContain('aria-label="Synthetic demo data"');
  });
});
