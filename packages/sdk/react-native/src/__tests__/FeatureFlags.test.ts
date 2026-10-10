import { describe, it, expect, vi, beforeEach } from 'vitest';

// vi.mock() is hoisted to the top of the file, so any state it captures
// must be declared via vi.hoisted() to survive the hoisting reorder.
const { nativeFlags } = vi.hoisted(() => ({
  nativeFlags: {
    initialize: vi.fn(),
    isEnabled: vi.fn(async (key: string) => key === 'on'),
    getFlag: vi.fn(async (key: string) => ({ key, enabled: true, source: 'remote' as const })),
    getValue: vi.fn(async (_k: string) => 'native-value'),
    getAllFlags: vi.fn(async () => ({})),
    setOverride: vi.fn(),
    clearOverride: vi.fn(),
    refresh: vi.fn(async () => undefined),
    destroy: vi.fn(),
  },
}));

vi.mock('react-native', () => ({
  NativeModules: { AetherFeatureFlags: nativeFlags },
  NativeEventEmitter: class {},
  Platform: { OS: 'ios' },
}));

// Import after mock so the module binds to the mocked NativeModules.
import { RNFeatureFlags } from '../modules/FeatureFlags';

describe('RNFeatureFlags (RN thin bridge)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('initialize delegates to native module with api key + endpoint', () => {
    RNFeatureFlags.initialize('ak_test_123', 'https://api.example.com');
    expect(nativeFlags.initialize).toHaveBeenCalledWith('ak_test_123', 'https://api.example.com');
  });

  it('isEnabled returns the native result', async () => {
    await expect(RNFeatureFlags.isEnabled('on')).resolves.toBe(true);
    await expect(RNFeatureFlags.isEnabled('off')).resolves.toBe(false);
  });

  it('getFlag passes through the native payload', async () => {
    const flag = await RNFeatureFlags.getFlag('ff_pricing');
    expect(flag).toEqual({ key: 'ff_pricing', enabled: true, source: 'remote' });
  });

  it('getValue falls back to default when native returns null/undefined', async () => {
    nativeFlags.getValue.mockResolvedValueOnce(null as unknown as string);
    await expect(RNFeatureFlags.getValue('missing', 'fallback')).resolves.toBe('fallback');

    nativeFlags.getValue.mockResolvedValueOnce(undefined as unknown as string);
    await expect(RNFeatureFlags.getValue('missing', 42)).resolves.toBe(42);
  });

  it('getValue returns native value when present', async () => {
    nativeFlags.getValue.mockResolvedValueOnce('present');
    await expect(RNFeatureFlags.getValue('k', 'fallback')).resolves.toBe('present');
  });

  it('setOverride / clearOverride / refresh / destroy delegate to native', async () => {
    RNFeatureFlags.setOverride('ff', true);
    RNFeatureFlags.clearOverride('ff');
    await RNFeatureFlags.refresh();
    RNFeatureFlags.destroy();

    expect(nativeFlags.setOverride).toHaveBeenCalledWith('ff', true);
    expect(nativeFlags.clearOverride).toHaveBeenCalledWith('ff');
    expect(nativeFlags.refresh).toHaveBeenCalledOnce();
    expect(nativeFlags.destroy).toHaveBeenCalledOnce();
  });
});
