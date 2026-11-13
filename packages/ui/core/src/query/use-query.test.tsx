// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import { queryCache } from './cache';
import { useQuery } from './use-query';

describe('useQuery across an identity switch', () => {
  it('ignores a pre-switch request that fails after its replacement succeeded', async () => {
    // Codex review on DammnThatsCrazy/AETHER#868: the generation guard kept
    // the stale response out of the cache, but its rejection still set the
    // hook's error next to the new tenant's valid data.
    let rejectOld: (e: Error) => void = () => {};
    let call = 0;
    const fetcher = () => {
      call += 1;
      if (call === 1) return new Promise<string[]>((_, reject) => { rejectOld = reject; });
      return Promise.resolve(['tenant-b']);
    };
    function Reader() {
      const { data, error } = useQuery({ key: 'k:switch', fetcher });
      return <span data-testid="state">{error ?? (data ? data.join() : 'none')}</span>;
    }
    render(<Reader />);
    await waitFor(() => expect(call).toBe(1));
    act(() => { queryCache.clear(); });
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('tenant-b'));
    await act(async () => { rejectOld(new Error('tenant-a request failed')); await Promise.resolve(); });
    expect(screen.getByTestId('state').textContent).toBe('tenant-b');
  });
});
