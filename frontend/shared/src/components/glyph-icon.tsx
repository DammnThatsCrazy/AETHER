import { cn } from '../utils/cn';

interface GlyphIconProps {
  readonly glyph: string;
  readonly className?: string;
  readonly title?: string;
}

export function GlyphIcon({ glyph, className, title }: GlyphIconProps) {
  return (
    <span className={cn('font-mono text-xs leading-none', className)} title={title} aria-label={title}>
      {glyph}
    </span>
  );
}
