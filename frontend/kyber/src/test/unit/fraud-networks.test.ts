import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockApi = {
  fraudNetworks: {
    list: vi.fn(),
    get: vi.fn(),
    build: vi.fn(),
    graph: vi.fn(),
    members: vi.fn(),
    evidence: vi.fn(),
    refresh: vi.fn(),
    suppress: vi.fn(),
    escalate: vi.fn(),
    openInvestigation: vi.fn(),
    annotate: vi.fn(),
    timeline: vi.fn(),
  },
  flowTrace: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    paths: vi.fn(),
    sources: vi.fn(),
    sinks: vi.fn(),
    cycles: vi.fn(),
    timeline: vi.fn(),
    attach: vi.fn(),
  },
};

vi.mock('@kyber/lib/api/endpoints', () => ({ api: mockApi }));

const mockUseQuery = vi.fn();
const mockUseMutation = vi.fn();
vi.mock('@aether/ui', () => ({
  useQuery: mockUseQuery,
  useMutation: mockUseMutation,
}));

describe('useFraudNetworks hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseQuery.mockReturnValue({ data: null, isLoading: false });
    mockUseMutation.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  });

  it('calls useQuery with fraud-networks key', async () => {
    const { useFraudNetworks } = await import('@kyber/features/fraud/use-fraud');
    useFraudNetworks();
    expect(mockUseQuery).toHaveBeenCalledWith(
      expect.objectContaining({ key: expect.stringContaining('fraud-networks') }),
    );
  });

  it('passes status filter param to API', async () => {
    const { useFraudNetworks } = await import('@kyber/features/fraud/use-fraud');
    useFraudNetworks({ status: 'active' });
    const call = mockUseQuery.mock.calls[0][0];
    call.fetcher();
    expect(mockApi.fraudNetworks.list).toHaveBeenCalledWith({ status: 'active' });
  });
});

describe('useFraudNetworkDetail hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseQuery.mockReturnValue({ data: null, isLoading: false });
  });

  it('calls useQuery with correct network id key', async () => {
    const { useFraudNetworkDetail } = await import('@kyber/features/fraud/use-fraud');
    useFraudNetworkDetail('net-123');
    expect(mockUseQuery).toHaveBeenCalledWith(
      expect.objectContaining({ key: expect.stringContaining('net-123') }),
    );
  });

  it('is disabled when networkId is empty', async () => {
    const { useFraudNetworkDetail } = await import('@kyber/features/fraud/use-fraud');
    useFraudNetworkDetail('');
    const call = mockUseQuery.mock.calls[0][0];
    expect(call.enabled).toBe(false);
  });
});

describe('useFraudNetworkGraph hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseQuery.mockReturnValue({ data: { nodes: [], edges: [] }, isLoading: false });
  });

  it('fetches graph for the given network id', async () => {
    const { useFraudNetworkGraph } = await import('@kyber/features/fraud/use-fraud');
    useFraudNetworkGraph('net-456');
    const call = mockUseQuery.mock.calls[0][0];
    call.fetcher();
    expect(mockApi.fraudNetworks.graph).toHaveBeenCalledWith('net-456');
  });
});

describe('useBuildFraudNetwork hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const mockMutate = vi.fn().mockResolvedValue({ id: 'net-new' });
    mockUseMutation.mockReturnValue({ mutateAsync: mockMutate, isPending: false });
  });

  it('calls useMutation with a build mutationFn', async () => {
    const { useBuildFraudNetwork } = await import('@kyber/features/fraud/use-fraud');
    useBuildFraudNetwork();
    expect(mockUseMutation).toHaveBeenCalledWith(
      expect.objectContaining({ mutationFn: expect.any(Function) }),
    );
  });

  it('mutationFn calls api.fraudNetworks.build with correct payload', async () => {
    const { useBuildFraudNetwork } = await import('@kyber/features/fraud/use-fraud');
    useBuildFraudNetwork();
    const call = mockUseMutation.mock.calls[0][0];
    await call.mutationFn({
      anchor_entity_ids: ['e1', 'e2'],
      network_type: 'circular_transfer',
      label: 'Test',
    });
    expect(mockApi.fraudNetworks.build).toHaveBeenCalledWith({
      anchor_entity_ids: ['e1', 'e2'],
      network_type: 'circular_transfer',
      label: 'Test',
    });
  });
});

describe('useCreateFlowTrace hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const mockMutate = vi.fn().mockResolvedValue({ id: 'trace-new' });
    mockUseMutation.mockReturnValue({ mutateAsync: mockMutate, isPending: false });
  });

  it('calls useMutation for trace creation', async () => {
    const { useCreateFlowTrace } = await import('@kyber/features/fraud/use-fraud');
    useCreateFlowTrace();
    expect(mockUseMutation).toHaveBeenCalledWith(
      expect.objectContaining({ mutationFn: expect.any(Function) }),
    );
  });

  it('mutationFn calls api.flowTrace.create with correct payload', async () => {
    const { useCreateFlowTrace } = await import('@kyber/features/fraud/use-fraud');
    useCreateFlowTrace();
    const call = mockUseMutation.mock.calls[0][0];
    await call.mutationFn({
      anchor_entity_id: 'anchor1',
      direction: 'downstream',
      max_hops: 4,
    });
    expect(mockApi.flowTrace.create).toHaveBeenCalledWith({
      anchor_entity_id: 'anchor1',
      direction: 'downstream',
      max_hops: 4,
    });
  });
});

describe('useFlowTracePaths hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseQuery.mockReturnValue({ data: { paths: [] }, isLoading: false });
  });

  it('fetches paths for a given trace id', async () => {
    const { useFlowTracePaths } = await import('@kyber/features/fraud/use-fraud');
    useFlowTracePaths('trace-789');
    const call = mockUseQuery.mock.calls[0][0];
    call.fetcher();
    expect(mockApi.flowTrace.paths).toHaveBeenCalledWith('trace-789');
  });

  it('is disabled when traceId is empty', async () => {
    const { useFlowTracePaths } = await import('@kyber/features/fraud/use-fraud');
    useFlowTracePaths('');
    const call = mockUseQuery.mock.calls[0][0];
    expect(call.enabled).toBe(false);
  });
});
