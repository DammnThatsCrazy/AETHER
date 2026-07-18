import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MockModeBanner } from './index';

describe('MockModeBanner', () => {
  it('renders nothing in live mode', () => {
    const html = renderToStaticMarkup(
      <MockModeBanner mode="live" envVarName="VITE_AETHER_ENV" envExplicit={true} />,
    );
    expect(html).toBe('');
  });

  it('surfaces an explicit "not live" caveat in mocked mode', () => {
    const html = renderToStaticMarkup(
      <MockModeBanner mode="mocked" envVarName="VITE_KYBER_ENV" envExplicit={true} />,
    );
    expect(html).toContain('data-mock-mode="active"');
    expect(html).toContain('Mock data');
    expect(html).toContain('not live');
    expect(html).toContain('VITE_KYBER_ENV');
  });

  it('escalates when the env var is missing (defaulted to local-mocked)', () => {
    const explicit = renderToStaticMarkup(
      <MockModeBanner mode="mocked" envVarName="VITE_AETHER_ENV" envExplicit={true} />,
    );
    const defaulted = renderToStaticMarkup(
      <MockModeBanner mode="mocked" envVarName="VITE_AETHER_ENV" envExplicit={false} />,
    );
    expect(explicit).not.toBe(defaulted);
    expect(defaulted).toContain('data-env-explicit="false"');
    expect(defaulted).toContain('is not set');
    expect(defaulted).toContain('shipping mocks that look live');
    // The dangerous defaulted case uses the danger tone, not warning.
    expect(defaulted).toContain('text-danger');
  });
});
