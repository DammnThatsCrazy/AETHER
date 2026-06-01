import { Card, CardHeader, CardContent, Badge, Button } from '@aether/ui';
import { useRecommendations, usePlaybooks } from '@aether-app/features/intelligence';

function asItems(data: unknown): unknown[] {
  if (data && typeof data === 'object' && 'items' in data) {
    const items = (data as { items?: unknown }).items;
    return Array.isArray(items) ? items : [];
  }
  return [];
}

function text(value: unknown, fallback = '—') {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}

export function DecisionIntelligencePanel() {
  const recommendations = useRecommendations();
  const playbooks = usePlaybooks();
  const recItems = asItems(recommendations.data).slice(0, 3) as Array<Record<string, unknown>>;
  const playbookItems = asItems(playbooks.data).slice(0, 3) as Array<Record<string, unknown>>;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-text-primary font-medium">Decision intelligence feed</h2>
              <p className="text-xs text-text-secondary mt-1">Ranked graph-native recommendations with evidence, confidence, and approval gates.</p>
            </div>
            <Badge variant="info">OODA enabled</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {recItems.length === 0 ? (
              <div className="rounded-lg border border-border-subtle p-4 text-sm text-text-secondary">
                No active recommendations yet. Generate graph intelligence to populate Observe → Orient → Recommend loops.
              </div>
            ) : recItems.map((rec) => {
              const action = rec.recommended_action as Record<string, unknown> | undefined;
              const confidence = rec.confidence as Record<string, unknown> | undefined;
              return (
                <div key={text(rec.recommendation_id)} className="rounded-lg border border-border-subtle p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-text-primary">{text(action?.label, 'Recommended action')}</div>
                      <div className="text-xs text-text-secondary mt-1">{text(rec.expected_outcome)}</div>
                    </div>
                    <Badge variant="success">{Math.round(Number(confidence?.overall ?? 0) * 100)}%</Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-text-muted">
                    <span>Approval: {text(rec.required_approval_level)}</span>
                    <span>Value: {text(rec.expected_value)}</span>
                    <span>Freshness: {text((rec.data_freshness as Record<string, unknown> | undefined)?.status)}</span>
                  </div>
                  <Button className="mt-3" size="sm" variant="secondary">Open decision drawer</Button>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><h2 className="text-text-primary font-medium">Playbooks</h2></CardHeader>
        <CardContent>
          {playbookItems.length === 0 ? <p className="text-sm text-text-secondary">No playbooks configured.</p> : playbookItems.map((pb) => (
            <div key={text(pb.playbook_id)} className="flex items-center justify-between border-b border-border-subtle py-2 last:border-b-0">
              <span className="text-sm text-text-primary">{text(pb.name)}</span>
              <Badge variant={pb.enabled ? 'success' : 'default'}>{pb.enabled ? 'Enabled' : 'Disabled'}</Badge>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
