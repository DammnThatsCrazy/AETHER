import { Card, CardHeader, CardTitle, CardContent, GlyphIcon } from '@shiki/components/system';
import { cn } from '@shiki/lib/utils';

interface ExplanationTraceProps {
  readonly rationale: string;
  readonly evidence: readonly string[];
  readonly confidence: number;
  readonly className?: string;
}

export function ExplanationTrace({ rationale, evidence, confidence, className }: ExplanationTraceProps) {
  return (
    <Card className={cn('border-l-2 border-l-accent', className)}>
      <CardHeader>
        <CardTitle>
          <GlyphIcon glyph={'\u2139'} className="mr-1" />
          Explanation Trace
        </CardTitle>
        <span className="text-xs text-text-secondary">
          Confidence: <span className={cn('font-medium', confidence >= 0.7 ? 'text-success' : confidence >= 0.4 ? 'text-warning' : 'text-danger')}>{Math.round(confidence * 100)}%</span>
        </span>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          <div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Rationale</div>
            <div className="text-xs text-text-primary">{rationale}</div>
          </div>
          {evidence.length > 0 && (
            <div>
              <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Evidence</div>
              <ul className="space-y-1">
                {evidence.map((e, i) => (
                  <li key={i} className="text-xs text-text-secondary flex items-start gap-2">
                    <GlyphIcon glyph={'\u2192'} className="text-accent mt-0.5 flex-shrink-0" />
                    {e}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
