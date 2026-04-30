import { cn } from '@kyber/lib/utils';

interface GlyphIconProps {
  readonly glyph: string;
  readonly className?: string;
  readonly title?: string;
}

export function GlyphIcon({ glyph, className, title }: GlyphIconProps) {
  return (
    <span className={cn('kyber-glyph', className)} title={title} aria-label={title}>
      {glyph}
    </span>
  );
}
