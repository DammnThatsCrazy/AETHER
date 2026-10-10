import { Icon, type IconName } from './icon';

interface GlyphIconProps {
  readonly glyph: string;
  readonly className?: string;
  readonly title?: string;
}

const legacyGlyphs: Readonly<Record<string, { readonly icon: IconName; readonly label: string }>> = {
  '[!]': { icon: 'triangle-alert', label: 'Warning' },
  '⚠': { icon: 'triangle-alert', label: 'Warning' },
  '[x]': { icon: 'circle-x', label: 'Close' },
  '[cp]': { icon: 'copy', label: 'Copy' },
  '[on]': { icon: 'circle-power', label: 'Activation' },
  '[+]': { icon: 'circle-plus', label: 'Add' },
  '[-]': { icon: 'circle-minus', label: 'Collapse' },
  '[>]': { icon: 'arrow-right', label: 'Continue' },
  '→': { icon: 'arrow-right', label: 'Continue' },
  '[~]': { icon: 'settings-2', label: 'Settings' },
  '[S]': { icon: 'save', label: 'Save' },
  '[·]': { icon: 'info', label: 'Information' },
  '•': { icon: 'info', label: 'Information' },
  'ℹ': { icon: 'info', label: 'Information' },
  '◫': { icon: 'panels-top-left', label: 'Workspace' },
  'terminal': { icon: 'terminal-square', label: 'Terminal' },
  'default': { icon: 'circle-help', label: 'Unknown' },
  '[sun]': { icon: 'lightbulb', label: 'Light theme' },
  '[moon]': { icon: 'circle-off', label: 'Dark theme' },
  '[<-]': { icon: 'arrow-left-right', label: 'Sign out' },
};

/**
 * @deprecated Use `Icon` or `NavigationIcon` with a canonical semantic name.
 * This compatibility adapter intentionally never renders the supplied glyph as
 * text: unknown legacy inputs become the neutral unknown SVG instead.
 */
export function GlyphIcon({ glyph, className, title }: GlyphIconProps) {
  const resolved = legacyGlyphs[glyph] ?? { icon: 'unknown', label: 'Unknown action' };
  return <Icon name={resolved.icon} size="sm" label={title ?? resolved.label} className={className} />;
}
