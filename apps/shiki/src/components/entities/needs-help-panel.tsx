import type { NeedsHelpCard } from '@shiki/types';
import { Card, CardHeader, CardTitle, CardContent, SeverityBadge, Badge } from '@shiki/components/system';
import { formatRelativeTime } from '@shiki/lib/utils';

interface NeedsHelpPanelProps {
  readonly card: NeedsHelpCard;
}

export function NeedsHelpPanel({ card }: NeedsHelpPanelProps) {
  return (
    <Card className="border-red-400/40 bg-red-400/5">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-red-400 flex items-center gap-2">
            <span className="text-lg">NEEDS HELP</span>
            <SeverityBadge severity={card.severity} />
          </CardTitle>
          <span className="text-xs text-neutral-500">
            Flagged {formatRelativeTime(card.flaggedAt)}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Reason */}
        <div>
          <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Reason</div>
          <p className="text-sm text-neutral-200">{card.reason}</p>
        </div>

        {/* Evidence */}
        <div>
          <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Evidence</div>
          <ul className="list-disc list-inside space-y-1">
            {card.evidence.map((item, i) => (
              <li key={i} className="text-sm text-neutral-300">{item}</li>
            ))}
          </ul>
        </div>

        {/* Confidence */}
        <div className="flex items-center gap-4">
          <div>
            <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Confidence</div>
            <span className="text-sm font-mono font-bold text-neutral-200">
              {(card.confidence * 100).toFixed(0)}%
            </span>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Reversible</div>
            <Badge variant={card.reversible ? 'default' : 'danger'}>
              {card.reversible ? 'Yes' : 'No'}
            </Badge>
          </div>
          {card.owner && (
            <div>
              <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Owner</div>
              <span className="text-sm text-neutral-200">{card.owner}</span>
            </div>
          )}
        </div>

        {/* Recommended Action */}
        <div>
          <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Recommended Action</div>
          <p className="text-sm text-amber-300">{card.recommendedAction}</p>
        </div>

        {/* Trace Link */}
        <div>
          <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Trace</div>
          <a
            href={card.traceLink}
            className="text-sm text-blue-400 hover:text-blue-300 underline font-mono"
          >
            {card.traceLink}
          </a>
        </div>
      </CardContent>
    </Card>
  );
}
