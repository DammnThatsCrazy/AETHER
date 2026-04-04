import { cn } from '@shiki/lib/utils';

interface AsciiStatusGlyphProps {
  readonly status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  readonly className?: string | undefined;
}

const GLYPHS: Record<string, { glyph: string; color: string }> = {
  healthy: { glyph: '\u2588', color: 'text-success' },
  degraded: { glyph: '\u2593', color: 'text-warning' },
  unhealthy: { glyph: '\u2591', color: 'text-danger' },
  unknown: { glyph: '\u2592', color: 'text-text-muted' },
};

export function AsciiStatusGlyph({ status, className }: AsciiStatusGlyphProps) {
  const entry = GLYPHS[status];
  const glyph = entry?.glyph ?? '?';
  const color = entry?.color ?? 'text-text-muted';
  return <span className={cn('font-mono text-sm', color, className)}>{glyph}</span>;
}
