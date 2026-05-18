import { cn } from '@aether/ui';

interface PlaceholderPageProps {
  glyph?: string;
  title: string;
  subtitle?: string;
  eyebrow?: string;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}

export function PlaceholderPage({
  glyph = '◎',
  title,
  subtitle,
  eyebrow,
  actions,
  children,
}: PlaceholderPageProps) {
  return (
    <div className="px-6 py-5 h-full flex flex-col">
      <div className="flex items-start justify-between mb-6">
        <div>
          {eyebrow && <p className="label-eyebrow mb-1.5">{eyebrow}</p>}
          <h1 className="text-xl font-semibold tracking-tight text-text-primary">{title}</h1>
          {subtitle && <p className="text-sm text-text-secondary mt-1">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>

      {children ?? (
        <div className="flex-1 flex flex-col items-center justify-center text-text-muted py-20">
          <span className="font-mono text-4xl mb-4 opacity-30">{glyph}</span>
          <p className="text-sm text-text-muted">{title}</p>
          <p className="text-xs text-text-muted mt-1 opacity-60">Full implementation in progress</p>
        </div>
      )}
    </div>
  );
}
