// =============================================================================
// Aether SDK — AetherPressable
//
// Drop-in replacement for React Native's Pressable that emits one canonical
// `interaction_observed` event per press with a stable, developer-assigned
// control identity (`aetherId`). No text/label capture by default.
// =============================================================================

import React from 'react';
import { Pressable } from 'react-native';
import type { PressableProps, GestureResponderEvent } from 'react-native';
import { useTrackedPress } from './tracked-press';

export interface AetherPressableProps extends PressableProps {
  /**
   * Stable control identity (e.g. "checkout.confirm"). Required — interaction
   * analytics keyed on a stable id survive copy changes and translations,
   * which is why the rendered text is never captured instead.
   */
  aetherId: string;
  /** Optional extra event properties (explicit opt-in, never captured). */
  aetherProperties?: Record<string, unknown>;
}

export function AetherPressable({
  aetherId,
  aetherProperties,
  onPress,
  ...pressableProps
}: AetherPressableProps): React.JSX.Element {
  const trackedPress = useTrackedPress<GestureResponderEvent>(
    aetherId,
    onPress,
    aetherProperties,
  );
  return <Pressable {...pressableProps} onPress={trackedPress} />;
}
