/**
 * Route-state coverage for the Risk 360 / Fraud 360 operator workbenches
 * (`/fraud-networks/risk-360`, `/fraud-networks/fraud-360`).
 *
 * Both pages are read-only projection surfaces over the flag-gated
 * `/v1/risk360` / `/v1/fraud360` planes (default OFF). When the plane is not
 * enabled / provider unregistered / subject kind unserved the projection hook
 * resolves to `null` and each page must render its graceful "plane not enabled
 * / no projection" EmptyState — never an error crash. These cases drive the
 * subject picker to a target and assert that empty state with the projection
 * hooks mocked to an unserved plane.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { Risk360Page } from '@kyber/pages/fraud/risk-360-page';
import { Fraud360Page } from '@kyber/pages/fraud/fraud-360-page';

vi.mock('@kyber/features/risk360', () => ({
  RISK360_SUBJECT_KINDS: ['entity', 'relationship', 'cluster', 'population'],
  useRisk360Sections: () => ({
    result: null,
    data: null,
    sections: [],
    claims: [],
    dependencies: [],
    isLoading: false,
    error: null,
    refresh: () => {},
  }),
  useRisk360Health: () => ({ data: null, isLoading: false, error: null }),
}));

vi.mock('@kyber/features/fraud360', () => ({
  FRAUD360_SUBJECT_KINDS: ['entity', 'relationship', 'agent'],
  useFraud360Sections: () => ({
    result: null,
    data: null,
    sections: [],
    claims: [],
    dependencies: [],
    isLoading: false,
    error: null,
    refresh: () => {},
  }),
  useFraud360Health: () => ({ data: null, isLoading: false, error: null }),
}));

function driveToSubject(planeName: string, subjectId: string): void {
  fireEvent.change(screen.getByPlaceholderText('e.g. entity_uuid'), {
    target: { value: subjectId },
  });
  fireEvent.click(screen.getByRole('button', { name: `Run ${planeName} projection` }));
}

describe('Kyber risk/fraud 360 projection routes (empty plane)', () => {
  it('/fraud-networks/risk-360 renders the plane-not-enabled empty state', async () => {
    render(
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={['/fraud-networks/risk-360']}>
            <Routes>
              <Route path="/fraud-networks/risk-360" element={<Risk360Page />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );

    driveToSubject('Risk 360', 'ent_123');

    expect(
      await screen.findByText('Risk 360 plane not enabled / no projection'),
    ).toBeInTheDocument();
  });

  it('/fraud-networks/fraud-360 renders the plane-not-enabled empty state', async () => {
    render(
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={['/fraud-networks/fraud-360']}>
            <Routes>
              <Route path="/fraud-networks/fraud-360" element={<Fraud360Page />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );

    driveToSubject('Fraud 360', 'ent_123');

    expect(
      await screen.findByText('Fraud 360 plane not enabled / no projection'),
    ).toBeInTheDocument();
  });
});
