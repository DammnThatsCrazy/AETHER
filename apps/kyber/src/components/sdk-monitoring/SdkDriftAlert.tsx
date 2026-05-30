import type { DriftIncident, DriftSeverity, DriftType } from '@kyber/types/sdk-health';

interface SdkDriftAlertProps {
  readonly incidents: readonly DriftIncident[];
  readonly className?: string;
}

const SEVERITY_STYLES: Record<DriftSeverity, string> = {
  critical: 'bg-red-950/60 border-red-700 text-red-300',
  warning:  'bg-yellow-950/60 border-yellow-700 text-yellow-300',
  info:     'bg-blue-950/60 border-blue-700 text-blue-300',
};

const DRIFT_TYPE_LABELS: Record<DriftType, string> = {
  schema_drift:    'Schema Drift',
  stale_sdk:       'Stale SDK',
  replay_storm:    'Replay Storm',
  payload_anomaly: 'Payload Anomaly',
};

function DriftBadge({ type }: { type: DriftType }) {
  return (
    <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface-subtle text-text-secondary border border-border-subtle">
      {DRIFT_TYPE_LABELS[type] ?? type}
    </span>
  );
}

export function SdkDriftAlert({ incidents, className }: SdkDriftAlertProps) {
  if (incidents.length === 0) {
    return (
      <div className={`text-xs text-text-muted py-4 text-center ${className ?? ''}`}>
        No drift incidents detected.
      </div>
    );
  }

  return (
    <div className={`space-y-2 ${className ?? ''}`}>
      {incidents.map(incident => (
        <div
          key={incident.incident_id}
          className={`rounded-md border px-3 py-2 text-xs space-y-1 ${SEVERITY_STYLES[incident.severity]}`}
        >
          <div className="flex items-center justify-between gap-2">
            <DriftBadge type={incident.drift_type} />
            <span className="text-[10px] opacity-70">
              {new Date(incident.detected_at).toLocaleString()}
            </span>
          </div>
          <div className="font-mono text-[11px] opacity-90 leading-snug">
            {incident.description}
          </div>
          <div className="text-[10px] opacity-60">
            SDK: {incident.sdk_id.slice(0, 16)}…
          </div>
        </div>
      ))}
    </div>
  );
}
