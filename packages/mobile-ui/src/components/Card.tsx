/**
 * Elevated surface card — theme-consistent container for grouped content.
 */
import React from 'react';
import { StyleSheet, View, type ViewStyle } from 'react-native';

import { theme } from '../theme';

export interface CardProps {
  children: React.ReactNode;
  style?: ViewStyle;
}

export function Card({ children, style }: CardProps): React.JSX.Element {
  return <View style={[styles.card, style]}>{children}</View>;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.colors.surface,
    borderColor: theme.colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: theme.radii.md,
    padding: theme.spacing.lg,
  },
});
