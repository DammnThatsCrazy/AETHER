import { describe, expect, it } from 'vitest';

import { theme, useTheme, type Theme } from '../theme';

describe('theme tokens', () => {
  it('matches the app-shell dark aesthetic', () => {
    expect(theme.colors.background).toBe('#0b0d12');
    expect(theme.colors.text).toBe('#f5f7fa');
    expect(theme.colors.muted).toBe('#8b93a7');
  });

  it('carries the desktop brand accent', () => {
    expect(theme.colors.accent).toBe('#3a6896');
    expect(theme.colors.accentHover).toBe('#5a85a8');
  });

  it('defines spacing, radius, and type-scale tokens', () => {
    expect(theme.spacing.xs).toBeGreaterThan(0);
    expect(theme.spacing.xxl).toBeGreaterThan(theme.spacing.xs);
    expect(theme.radii.sm).toBeGreaterThan(0);
    expect(theme.type.title.fontSize).toBeGreaterThan(theme.type.body.fontSize);
    expect(theme.type.title.color).toBe(theme.colors.text);
    expect(theme.type.subtitle.color).toBe(theme.colors.muted);
  });

  it('useTheme returns the static token set', () => {
    expect(useTheme()).toBe(theme);
    const tokens: Theme = useTheme();
    expect(tokens.colors.background).toBe('#0b0d12');
  });
});
