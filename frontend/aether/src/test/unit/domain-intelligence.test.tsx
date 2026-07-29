import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  DomainQueryState,
  EvidenceBoundary,
  queryCount,
} from '@aether-app/components/domain-intelligence';

describe('domain intelligence truth helpers', () => {
  it('keeps a failed secondary read distinct from a genuine empty result', () => {
    const retry = vi.fn();
    render(
      <>
        {DomainQueryState({
          isLoading: false,
          hasData: false,
          error: 'valuation source unavailable',
          domainLabel: 'Stablecoin valuations',
          onRetry: retry,
        })}
      </>,
    );

    expect(screen.getByText('valuation source unavailable')).toBeInTheDocument();
    expect(queryCount(undefined, false, 'read failed', 0)).toBe('Unavailable');
    expect(queryCount({ items: [] }, false, null, 0)).toBe(0);
  });

  it('renders an evidence disclosure next to domain data', () => {
    render(<EvidenceBoundary>Source-reported units; no conversion.</EvidenceBoundary>);
    expect(screen.getByText('Source-reported units; no conversion.')).toBeInTheDocument();
  });
});
