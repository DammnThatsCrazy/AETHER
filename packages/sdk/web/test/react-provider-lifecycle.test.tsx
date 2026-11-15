// @vitest-environment jsdom
// packages/sdk/web/test/react-provider-lifecycle.test.tsx
//
// Render-level lifecycle of <AetherProvider>: Strict Mode double-mount,
// restart on identity-config changes only, cancellation of a pending import,
// and cleanup on unmount. The SDK singleton is mocked; the React wrapper is
// what is under test.
import { StrictMode } from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const sdk = vi.hoisted(() => ({
  init: vi.fn(),
  destroy: vi.fn(),
  pageView: vi.fn(),
}));

vi.mock('@olympuslabs/aether-web', () => ({ default: sdk }));

import { AetherProvider, useAether } from '../src/react';

function Child() {
  useAether();
  return <span>ready</span>;
}

async function settle() {
  // Let the dynamic import and the resulting state update flush.
  await act(async () => {
    await vi.dynamicImportSettled();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe('AetherProvider lifecycle', () => {
  beforeEach(() => {
    sdk.init.mockClear();
    sdk.destroy.mockClear();
  });
  afterEach(() => cleanup());

  it('initializes exactly once under React Strict Mode', async () => {
    render(
      <StrictMode>
        <AetherProvider config={{ apiKey: 'pk_1', siteId: 'site_1' }}>
          <Child />
        </AetherProvider>
      </StrictMode>,
    );
    await settle();
    expect(screen.getByText('ready')).toBeTruthy();
    expect(sdk.init).toHaveBeenCalledTimes(1);
    expect(sdk.init).toHaveBeenCalledWith({ apiKey: 'pk_1', siteId: 'site_1' });
  });

  it('does not restart when an inline config object is recreated with the same keys', async () => {
    const view = render(
      <AetherProvider config={{ apiKey: 'pk_1', siteId: 'site_1' }}>
        <Child />
      </AetherProvider>,
    );
    await settle();
    view.rerender(
      <AetherProvider config={{ apiKey: 'pk_1', siteId: 'site_1' }}>
        <Child />
      </AetherProvider>,
    );
    await settle();
    expect(sdk.init).toHaveBeenCalledTimes(1);
    expect(sdk.destroy).not.toHaveBeenCalled();
  });

  it('restarts with the new config when the site changes', async () => {
    const view = render(
      <AetherProvider config={{ apiKey: 'pk_1', siteId: 'site_1' }}>
        <Child />
      </AetherProvider>,
    );
    await settle();
    view.rerender(
      <AetherProvider config={{ apiKey: 'pk_2', siteId: 'site_2' }}>
        <Child />
      </AetherProvider>,
    );
    await settle();
    expect(sdk.destroy).toHaveBeenCalledTimes(1);
    expect(sdk.init).toHaveBeenCalledTimes(2);
    expect(sdk.init).toHaveBeenLastCalledWith({ apiKey: 'pk_2', siteId: 'site_2' });
  });

  it('ignores a non-identity option change after init and warns in development', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const view = render(
      <AetherProvider config={{ apiKey: 'pk_1', debug: false }}>
        <Child />
      </AetherProvider>,
    );
    await settle();
    view.rerender(
      <AetherProvider config={{ apiKey: 'pk_1', debug: true }}>
        <Child />
      </AetherProvider>,
    );
    await settle();
    expect(sdk.init).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('config.debug changed after init'));
    warn.mockRestore();
  });

  it('does not initialize when unmounted before the SDK import resolves', async () => {
    const view = render(
      <AetherProvider config={{ apiKey: 'pk_1' }}>
        <Child />
      </AetherProvider>,
    );
    view.unmount(); // before the dynamic import settles
    await settle();
    expect(sdk.init).not.toHaveBeenCalled();
    expect(sdk.destroy).not.toHaveBeenCalled();
  });

  it('destroys the SDK on unmount after init', async () => {
    const view = render(
      <AetherProvider config={{ apiKey: 'pk_1' }}>
        <Child />
      </AetherProvider>,
    );
    await settle();
    view.unmount();
    expect(sdk.destroy).toHaveBeenCalledTimes(1);
  });
});
