import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from '@demo/App';

describe('Aether Demo App', () => {
  it('renders the tenant value loop', () => {
    render(<App />);
    expect(screen.getByText('Aether — Demo')).toBeInTheDocument();
    expect(screen.getByText(/Ingestion — SDK and no-SDK paths/)).toBeInTheDocument();
    expect(screen.getByText('Graph & Profile360')).toBeInTheDocument();
    expect(screen.getByText('Recommendation families')).toBeInTheDocument();
    expect(screen.getByText(/Outcomes & ledger/)).toBeInTheDocument();
  });

  it('always shows a persistent synthetic-data label', () => {
    render(<App />);
    const banner = screen.getByTestId('synthetic-data-banner');
    expect(banner).toHaveTextContent('Synthetic demo data — not a production tenant');
    expect(banner).toHaveTextContent('local-mocked');
  });

  it('switches to the operator (Kyber) view', () => {
    render(<App />);
    fireEvent.click(screen.getByText('Operator (Kyber)'));
    expect(screen.getByText('Tenant value health')).toBeInTheDocument();
    expect(screen.getByText('Intelligence quality')).toBeInTheDocument();
  });
});
