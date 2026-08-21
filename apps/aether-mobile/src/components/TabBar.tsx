/**
 * Bottom tab bar for the five Aether Mobile root tabs (M3b).
 *
 * App-local composition: `@aether/mobile-ui` ships no tab bar, so this reuses the
 * theme tokens directly. Tabs are typed against the route map (`AppTab`) so a tab
 * can never reference a screen that isn't registered.
 */
import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { theme } from '@aether/mobile-ui';

import type { AppTab } from '../routes';

const TABS: Array<{ key: AppTab; label: string }> = [
  { key: 'Today', label: 'Today' },
  { key: 'Copilot', label: 'Copilot' },
  { key: 'Explore', label: 'Explore' },
  { key: 'Alerts', label: 'Alerts' },
  { key: 'Account', label: 'Account' },
];

export interface TabBarProps {
  active: AppTab;
  onSelect: (tab: AppTab) => void;
}

export function TabBar({ active, onSelect }: TabBarProps): React.JSX.Element {
  return (
    <View style={styles.bar}>
      {TABS.map((tab) => {
        const isActive = tab.key === active;
        return (
          <TouchableOpacity
            key={tab.key}
            onPress={() => onSelect(tab.key)}
            accessibilityRole="tab"
            accessibilityState={{ selected: isActive }}
            accessibilityLabel={tab.label}
            style={styles.tab}
          >
            <Text style={[styles.label, isActive ? styles.labelActive : styles.labelInactive]}>{tab.label}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
    backgroundColor: theme.colors.background,
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: theme.spacing.md,
  },
  label: {
    fontSize: theme.type.caption.fontSize,
    fontWeight: '600',
  },
  labelActive: { color: theme.colors.accentHover },
  labelInactive: { color: theme.colors.muted },
});
