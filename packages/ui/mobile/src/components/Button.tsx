/**
 * Theme-consistent pressable button. Variants map to the token palette.
 */
import React from 'react';
import { StyleSheet, Text, TouchableOpacity, type ViewStyle } from 'react-native';

import { theme } from '../theme';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost';

export interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  accessibilityHint?: string;
  style?: ViewStyle;
}

const variantPalette: Record<ButtonVariant, { background: string; foreground: string }> = {
  primary: { background: theme.colors.accent, foreground: theme.colors.onAccent },
  secondary: { background: theme.colors.surface, foreground: theme.colors.text },
  ghost: { background: 'transparent', foreground: theme.colors.accentHover },
};

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled = false,
  accessibilityHint,
  style,
}: ButtonProps): React.JSX.Element {
  const palette = variantPalette[variant];
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      style={[styles.base, { backgroundColor: palette.background }, disabled && styles.disabled, style]}
    >
      <Text style={[styles.label, { color: palette.foreground }]}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: {
    borderRadius: theme.radii.md,
    paddingVertical: theme.spacing.md,
    paddingHorizontal: theme.spacing.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: {
    fontSize: theme.type.label.fontSize,
    fontWeight: '600',
    lineHeight: theme.type.label.lineHeight,
  },
  disabled: { opacity: 0.5 },
});
