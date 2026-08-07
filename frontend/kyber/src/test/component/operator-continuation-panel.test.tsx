/**
 * Operator continuation surfaces — M5d panel + create affordance.
 *
 * Both surfaces must render NOTHING while `enableKyberContinuations` is off (D8) —
 * no dead surface and no HTTP traffic can originate from them. While the flag is on
 * the panel renders the recent operator continuation feed (the mocked hook state,
 * not the network) and the create button calls the create hook with the command
 * context it was given.
 *
 * Only the `@aether/ui` hooks are stubbed; the real Button / Card / Badge /
 * EmptyState components render, so the assertions are against real markup.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ContinuationCreateButton,
  OperatorContinuationPanel,
} from '@kyber/features/continuation';

const mocks = vi.hoisted(() => ({
  isFeatureEnabled: vi.fn(),
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  mutate: vi.fn(),
}));

vi.mock('@kyber/lib/featureFlags', () => ({
  featureFlags: {},
  isFeatureEnabled: mocks.isFeatureEnabled,
}));

vi.mock('@aether/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aether/ui')>();
  return {
    ...actual,
    useQuery: mocks.useQuery,
    useMutation: mocks.useMutation,
  };
});

function setFlag(value: boolean): void {
  mocks.isFeatureEnabled.mockReturnValue(value);
}

function stubHooks(): void {
  mocks.useQuery.mockReturnValue({
    data: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
  mocks.useMutation.mockReturnValue({
    mutate: mocks.mutate,
    isLoading: false,
    error: null,
    data: null,
    reset: vi.fn(),
  });
}

const RECENT = [
  {
    id: 'cont_op_1',
    principal_id: 'op_1',
    source_client: 'kyber-desktop',
    surface: 'investigations',
    summary: { title: 'whale outflow', subtitle: 'circular transfer ring' },
    state_revision: 3,
    updated_at: '2026-08-07T00:00:00Z',
  },
];

describe('OperatorContinuationPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setFlag(false);
    stubHooks();
  });

  it('renders nothing while the flag is off', () => {
    const { container } = render(<OperatorContinuationPanel />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the recent operator continuation feed while the flag is on', () => {
    setFlag(true);
    mocks.useQuery.mockReturnValue({
      data: { continuations: RECENT },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    render(<OperatorContinuationPanel />);
    expect(screen.getByText('whale outflow')).toBeTruthy();
    expect(screen.getByText('investigations')).toBeTruthy();
    expect(screen.getByText(/Hand off to phone/)).toBeTruthy();
  });

  it('renders an empty state when the feed has no continuations', () => {
    setFlag(true);
    mocks.useQuery.mockReturnValue({
      data: { continuations: [] },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    render(<OperatorContinuationPanel />);
    expect(screen.getByText('No operator continuations yet')).toBeTruthy();
  });
});

describe('ContinuationCreateButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setFlag(false);
    stubHooks();
  });

  it('renders nothing while the flag is off', () => {
    const { container } = render(<ContinuationCreateButton reason="why" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when the capability gate is denied', () => {
    setFlag(true);
    const { container } = render(
      <ContinuationCreateButton canCreate={false} reason="why" />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('calls the create hook with the command context while the flag is on', async () => {
    setFlag(true);
    mocks.mutate.mockResolvedValue({ skipped: false });
    render(
      <ContinuationCreateButton
        canCreate={true}
        reason="Operator-initiated continuation"
        sourceCommandId="cmd-99"
      />,
    );
    const button = screen.getByRole('button', { name: /create continuation/i });
    fireEvent.click(button);
    expect(mocks.mutate).toHaveBeenCalledWith({
      source_command_id: 'cmd-99',
      objective: 'Operator-initiated continuation',
    });
    // Flush the async create → notice update (also proves the success path on screen).
    await waitFor(() => expect(screen.getByText('Continuation created.')).toBeTruthy());
  });
});
