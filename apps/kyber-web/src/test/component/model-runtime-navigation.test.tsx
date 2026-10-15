/**
 * Kyber — model-runtime operator navigation (ADR-008 D8/D9).
 *
 * Asserts the five model-runtime control-plane admin surfaces are reachable and
 * discoverable through the Kyber app:
 *
 *   · the sidebar lists the five pages when the `enableModelHarness` frontend
 *     flag is on (default OFF), each linking to its `/model-runtime/*` route;
 *   · the sidebar hides them when the flag is off;
 *   · each page renders when its route is navigated to (stub api injected via
 *     the `api` prop, mirroring the sibling page tests).
 *
 * Routing is not a grant — the backend /v1/model-runtime/* endpoints gate every
 * request; this test only proves the surfaces are wired and reachable.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { ComponentType } from 'react';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { Sidebar } from '@kyber/components/layout';
import {
  EntitlementsPage,
  ModelRegistryPage,
  ModelRuntimeHealthPage,
  TracesPage,
  UsagePage,
} from '@kyber/features/model-runtime';
import type { ModelRuntimeAdminApi } from '@kyber/features/model-runtime/types';

const state = vi.hoisted(() => ({ modelHarness: true }));

vi.mock('@kyber/lib/featureFlags', () => ({
  isFeatureEnabled: (flag: string) => (flag === 'enableModelHarness' ? state.modelHarness : false),
}));

vi.mock('@aether/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aether/ui')>();
  return {
    ...actual,
    useCapabilities: () => ({ capabilities: null, buildInfo: null, loading: false, error: null, refresh: vi.fn() }),
    useBuildInfo: () => null,
  };
});

const NAV_LINKS = [
  { path: '/model-runtime/registry', label: 'Model Registry' },
  { path: '/model-runtime/health', label: 'Model Health' },
  { path: '/model-runtime/entitlements', label: 'Model Entitlements' },
  { path: '/model-runtime/usage', label: 'Model Usage' },
  { path: '/model-runtime/traces', label: 'Model Traces' },
] as const;

function renderSidebar() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

const STUB_API: ModelRuntimeAdminApi = {
  fetchRegistry: () => Promise.resolve({ models: [] }),
  fetchHealth: () => Promise.resolve({ status: 'ok', providers: [], checks: {} }),
  fetchEntitlements: () => Promise.resolve({ entitlements: [] }),
  fetchUsage: () =>
    Promise.resolve({
      period: '2026-08',
      totals: { calls: 0, inputTokens: 0, outputTokens: 0, costUsd: 0 },
      byModel: [],
    }),
  fetchTraces: () => Promise.resolve({ traces: [] }),
};

const PAGES: ReadonlyArray<{
  readonly path: string;
  readonly Page: ComponentType<{ readonly api?: ModelRuntimeAdminApi }>;
  readonly title: string;
}> = [
  { path: '/model-runtime/registry', Page: ModelRegistryPage, title: 'Model Registry' },
  { path: '/model-runtime/health', Page: ModelRuntimeHealthPage, title: 'Model Runtime Health' },
  { path: '/model-runtime/entitlements', Page: EntitlementsPage, title: 'Model entitlements' },
  { path: '/model-runtime/usage', Page: UsagePage, title: 'Model Runtime Usage' },
  { path: '/model-runtime/traces', Page: TracesPage, title: 'Model routing traces' },
];

describe('Kyber model-runtime operator navigation', () => {
  it('lists the five model-runtime pages in the sidebar when enableModelHarness is on', () => {
    state.modelHarness = true;
    renderSidebar();
    for (const { path, label } of NAV_LINKS) {
      expect(screen.getByRole('link', { name: label })).toHaveAttribute('href', path);
    }
  });

  it('hides the model-runtime pages from the sidebar when enableModelHarness is off', () => {
    state.modelHarness = false;
    renderSidebar();
    for (const { label } of NAV_LINKS) {
      expect(screen.queryByRole('link', { name: label })).toBeNull();
    }
  });

  it.each(PAGES)('$path renders the $title page', async ({ path, Page, title }) => {
    render(
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path={path} element={<Page api={STUB_API} />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );
    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
  });
});
