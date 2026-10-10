// =============================================================================
// Aether SDK — FEATURE FLAGS MODULE (React Native) — Thin Native Bridge
// Delegates all feature flag evaluation to NativeModules.AetherFeatureFlags
// =============================================================================

import { NativeModules } from 'react-native';
import type { FeatureFlag } from '@aether/shared/feature-flag-types';

export type { FeatureFlag };

const { AetherFeatureFlags: NativeFlags } = NativeModules;

// ---------------------------------------------------------------------------
// Thin bridge — all logic lives in the native layer
// ---------------------------------------------------------------------------

class RNFeatureFlagModule {
  initialize(apiKey: string, endpoint: string): void {
    NativeFlags?.initialize(apiKey, endpoint);
  }

  async isEnabled(key: string): Promise<boolean> {
    return NativeFlags?.isEnabled(key) ?? false;
  }

  async getFlag(key: string): Promise<FeatureFlag> {
    return NativeFlags?.getFlag(key) ?? { key, enabled: false, source: 'default' };
  }

  async getValue<T>(key: string, defaultValue: T): Promise<T> {
    const result = await NativeFlags?.getValue(key);
    return result !== undefined && result !== null ? result : defaultValue;
  }

  async getAllFlags(): Promise<Record<string, FeatureFlag>> {
    return NativeFlags?.getAllFlags() ?? {};
  }

  setOverride(key: string, value: boolean | unknown): void {
    NativeFlags?.setOverride(key, value);
  }

  clearOverride(key: string): void {
    NativeFlags?.clearOverride(key);
  }

  async refresh(): Promise<void> {
    await NativeFlags?.refresh();
  }

  destroy(): void {
    NativeFlags?.destroy();
  }
}

export const RNFeatureFlags = new RNFeatureFlagModule();
export default RNFeatureFlags;
