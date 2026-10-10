import type { ComponentType } from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { DeploymentReadinessPage } from '@kyber/pages/deployment-readiness';
import {
  BuyerPersonasPage,
  GTMMaterialsPage,
  PricingArchitecturePage,
  ROICalculatorsPage,
  SalesReadinessPage,
} from '@kyber/pages/gtm';
import { SolutionPackagesPage } from '@kyber/pages/packages';
import { RevenueOperationsPage } from '@kyber/pages/revenue-operations';

const apiMock = vi.hoisted(() => ({
  catalog: vi.fn(),
  packageDetail: vi.fn(),
}));

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    auditExportHealth: apiMock.catalog,
    buyerPersonas: apiMock.catalog,
    deploymentReadiness: apiMock.catalog,
    gtmMaterials: apiMock.catalog,
    pricingModels: apiMock.catalog,
    revopsContracts: apiMock.catalog,
    revopsExpansionBillingOpportunities: apiMock.catalog,
    revopsInvoicePreviews: apiMock.catalog,
    revopsOverview: apiMock.catalog,
    revopsRevenueLeakage: apiMock.catalog,
    revopsUsage: apiMock.catalog,
    revopsValueCreated: apiMock.catalog,
    roiCalculators: apiMock.catalog,
    salesReadiness: apiMock.catalog,
    solutionPackage: apiMock.packageDetail,
    solutionPackages: apiMock.catalog,
  } } },
}));

interface CatalogCase {
  readonly route: string;
  readonly routePattern?: string;
  readonly Page: ComponentType;
  readonly emptyText: string;
  readonly errorText: string;
  readonly detail?: boolean;
}

const cases: readonly CatalogCase[] = [
  { route: '/pricing-architecture', Page: PricingArchitecturePage, emptyText: 'No pricing models configured', errorText: 'Unable to load Pricing Architecture' },
  { route: '/gtm-materials', Page: GTMMaterialsPage, emptyText: 'No GTM materials configured', errorText: 'Unable to load GTM Materials' },
  { route: '/buyer-personas', Page: BuyerPersonasPage, emptyText: 'No buyer personas configured', errorText: 'Unable to load Buyer Personas' },
  { route: '/roi-calculators', Page: ROICalculatorsPage, emptyText: 'No ROI calculators configured', errorText: 'Unable to load ROI Calculators' },
  { route: '/sales-readiness', Page: SalesReadinessPage, emptyText: 'No sales readiness records', errorText: 'Unable to load Sales Readiness' },
  { route: '/packages', Page: SolutionPackagesPage, emptyText: 'No solution packages configured', errorText: 'Unable to load packages' },
  { route: '/packages/package-local', routePattern: '/packages/:packageId', Page: SolutionPackagesPage, emptyText: 'Package not found', errorText: 'Unable to load packages', detail: true },
  { route: '/deployment-readiness', Page: DeploymentReadinessPage, emptyText: 'No deployment readiness records', errorText: 'Unable to load readiness' },
  { route: '/revops', Page: RevenueOperationsPage, emptyText: 'No contract profiles yet', errorText: 'Unable to load RevOps' },
];

function renderRoute({ Page, route, routePattern = route }: CatalogCase) {
  render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]}>
          <Routes><Route path={routePattern} element={<Page />} /></Routes>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe('Kyber catalog route states', () => {
  beforeEach(() => {
    apiMock.catalog.mockReset();
    apiMock.packageDetail.mockReset();
  });

  it.each(cases)('$route renders successful empty', async (testCase) => {
    apiMock.catalog.mockResolvedValue({ items: [] });
    apiMock.packageDetail.mockResolvedValue(null);
    renderRoute(testCase);
    expect(await screen.findByText(testCase.emptyText)).toBeInTheDocument();
    expect(screen.queryByText(testCase.errorText)).not.toBeInTheDocument();
  });

  it.each(cases)('$route renders unavailable', async (testCase) => {
    const failure = new Error('catalog backend offline');
    apiMock.catalog.mockRejectedValue(failure);
    apiMock.packageDetail.mockRejectedValue(failure);
    renderRoute(testCase);
    expect(await screen.findByText(testCase.errorText)).toBeInTheDocument();
    expect(screen.queryByText(testCase.emptyText)).not.toBeInTheDocument();
  });
});
