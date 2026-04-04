import { cn } from '@shiki/lib/utils';

interface GlyphIconProps {
  readonly glyph: string;
  readonly className?: string;
  readonly title?: string;
}

export function GlyphIcon({ glyph, className, title }: GlyphIconProps) {
  return (
    <span className={cn('shiki-glyph', className)} title={title} aria-label={title}>
      {glyph}
    </span>
  );
}
