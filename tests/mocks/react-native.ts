// Minimal react-native stub for node/vitest environment.
// Only the APIs used by @aether/react-native bridge are mocked.
export const NativeModules: Record<string, any> = {
  AetherNative: null,
  AetherEcommerce: {
    initialize: () => {},
    productViewed: () => {},
    productListViewed: () => {},
    addToCart: () => {},
    removeFromCart: () => {},
    cartViewed: () => {},
    checkoutStarted: () => {},
    checkoutStepCompleted: () => {},
    orderCompleted: () => {},
    orderRefunded: () => {},
    couponApplied: () => {},
    destroy: () => {},
  },
  AetherFeatureFlags: {
    initialize: () => {},
    isEnabled: async () => false,
    getFlag: async () => ({ key: 'mock', enabled: false, source: 'default' }),
    getValue: async (_k: string, d: any) => d,
    destroy: () => {},
  },
  AetherFeedback: {
    initialize: () => {},
    registerSurvey: () => {},
    shouldShowSurvey: async () => false,
    recordSurveyShown: async () => {},
    recordSurveyResponse: async () => {},
    destroy: () => {},
  },
};

export class NativeEventEmitter {
  constructor(_nativeModule?: any) {}
  addListener(_event: string, _cb: (...args: any[]) => void) {
    return { remove: () => {} };
  }
  removeAllListeners(_event?: string) {}
  emit(_event: string, ..._args: any[]) {}
}

export const Platform = {
  OS: 'ios' as const,
  Version: '17.0',
  select: <T>(obj: Record<string, T> & { default?: T }): T | undefined => {
    // @ts-ignore
    return obj.ios ?? obj.default ?? obj.android ?? Object.values(obj)[0];
  },
};

export const Dimensions = {
  get: (_dim: string) => ({ width: 390, height: 844, scale: 2, fontScale: 1 }),
  addEventListener: () => ({ remove: () => {} }),
};

export const Pressable: any = () => null;

export const AppState = {
  currentState: 'active',
  addEventListener: () => ({ remove: () => {} }),
};

export default {
  NativeModules,
  NativeEventEmitter,
  Platform,
  Dimensions,
  Pressable,
  AppState,
};
