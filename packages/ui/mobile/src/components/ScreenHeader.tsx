/**
 * Typed screen header — title, optional subtitle, back affordance, and an optional
 * accessory slot. Theme-consistent (see `../theme.ts`).
 */
import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View, type ViewStyle } from 'react-native';

import { theme } from '../theme';

export interface ScreenHeaderProps {
  title: string;
  subtitle?: string;
  onBack?: () => void;
  /** Right-side header accessory (actions / badges). */
  accessory?: React.ReactNode;
  style?: ViewStyle;
}

export function ScreenHeader({ title, subtitle, onBack, accessory, style }: ScreenHeaderProps): React.JSX.Element {
  return (
    <View style={[styles.container, style]}>
      {onBack ? (
        <TouchableOpacity
          onPress={onBack}
          accessibilityRole="button"
          accessibilityLabel={`Back from ${title}`}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          style={styles.backButton}
        >
          <Text style={styles.backLabel}>‹ Back</Text>
        </TouchableOpacity>
      ) : null}
      <View style={styles.titleBlock}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {accessory ? <View style={styles.accessory}>{accessory}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: theme.spacing.md,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.colors.border,
  },
  backButton: { paddingRight: theme.spacing.sm },
  backLabel: {
    color: theme.colors.accentHover,
    fontSize: theme.type.label.fontSize,
    fontWeight: '600',
    lineHeight: theme.type.label.lineHeight,
  },
  titleBlock: { flex: 1 },
  title: {
    color: theme.colors.text,
    fontSize: theme.type.title.fontSize,
    fontWeight: '700',
    lineHeight: theme.type.title.lineHeight,
  },
  subtitle: {
    color: theme.colors.muted,
    fontSize: theme.type.subtitle.fontSize,
    marginTop: theme.spacing.xs,
  },
  accessory: { marginLeft: theme.spacing.sm },
});
