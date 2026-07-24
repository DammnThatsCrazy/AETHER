// =============================================================================
// Aether SDK — Tracked press interaction (non-JSX core)
//
// The pure emit/handler logic lives here so it can be unit-tested without a
// React Native renderer; AetherPressable (JSX) composes it.
//
// Privacy: interaction emission carries the developer-assigned stable
// controlId only — no label/text capture by default. Anything else must be
// passed explicitly via `properties`.
// =============================================================================

import { useCallback } from 'react';
import Aether from '../bridge';

/**
 * Emit one canonical `ui_interaction_observed` event for a pressed control,
 * using the same payload shape as the native SDKs (controlId / controlType /
 * action). `aetherId` is the stable, developer-assigned control identity — it
 * must not be derived from rendered text.
 */

/**
 * Canonical `ui_interaction_observed` payload shape shared with the native
 * SDKs. Metadata-only by design — never carries rendered control text.
 */
export interface TrackedInteractionPayload {
  /** Stable, developer-assigned control identity (never derived from text). */
  controlId: string;
  /** Coarse control kind, e.g. 'pressable'. */
  controlType: string;
  /** Interaction verb, e.g. 'press'. */
  action: string;
  [key: string]: unknown;
}

export function emitTrackedPress(
  aetherId: string,
  properties?: Record<string, unknown>,
): void {
  Aether.observe('ui_interaction_observed', {
    controlId: aetherId,
    controlType: 'pressable',
    action: 'press',
    ...properties,
  });
}

/**
 * Build a press handler that first emits the interaction, then delegates to
 * the wrapped `onPress`. Pure (no hooks) so it is directly testable.
 */
export function createTrackedPressHandler<E>(
  aetherId: string,
  onPress?: ((event: E) => void) | null,
  properties?: Record<string, unknown>,
): (event: E) => void {
  return (event: E) => {
    emitTrackedPress(aetherId, properties);
    onPress?.(event);
  };
}

/**
 * Hook variant: memoized tracked press handler for custom touchables.
 *
 *     const onPress = useTrackedPress('checkout.confirm', handleConfirm);
 *     <TouchableOpacity onPress={onPress} … />
 */
export function useTrackedPress<E>(
  aetherId: string,
  onPress?: ((event: E) => void) | null,
  properties?: Record<string, unknown>,
): (event: E) => void {
  /* v8 ignore next 4 — thin useCallback wrapper over createTrackedPressHandler */
  return useCallback(
    createTrackedPressHandler(aetherId, onPress, properties),
    [aetherId, onPress, properties],
  );
}
