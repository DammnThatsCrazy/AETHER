import { useEffect, useState } from 'react';
import { Button, Card, CardContent, CardHeader, CardTitle, CapabilityStateBadge, resolveCapabilityState, type CapabilityState } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { ConnectorConfigModal } from '@aether-app/pages/connectors/connector-config-modal';

interface ConnectorInfo {
  readonly connector_type: string;
  readonly label: string;
  readonly description: string;
  readonly requires_secret: boolean;
  readonly enabled: boolean;
  readonly secret_configured: boolean;
  readonly sync_status: string;
  readonly manifest_data_outputs?: readonly string[];
}

interface Props {
  readonly onSkip?: () => void;
  readonly onContinue?: () => void;
}

type LoadState = 'loading' | 'ready' | 'error';

// Registered communications providers: any connector whose manifest declares
// comms.* data outputs (ADR-C11). No provider name is hardcoded — the cohort is
// the backend catalog (Klaviyo + SendGrid + Customer.io + Mailchimp + Postmark).
function isCommsConnector(c: ConnectorInfo | null): boolean {
  return Boolean(c?.manifest_data_outputs?.some((o) => o.startsWith('comms.')));
}

// Honest connection status for the comms connector. Availability gates win first,
// then the raw sync_status maps onto the shared matrix; nothing not-live reads green.
function commsState(c: ConnectorInfo | null): CapabilityState {
  if (!c) return 'not_configured';
  if (!c.enabled) return 'disabled';
  if (!c.secret_configured) return 'credential_required';
  return resolveCapabilityState(c.sync_status) ?? 'credential_waiting';
}

// Default to the configured comms connector when exactly one is connected;
// otherwise the first registered comms connector is the sensible onboarding
// default so the wizard opens without a provider-name hardcode.
function defaultCommsType(connectors: ConnectorInfo[]): string {
  const connected = connectors.filter((c) => c.enabled && c.secret_configured);
  if (connected.length === 1) return connected[0]?.connector_type ?? '';
  return connectors[0]?.connector_type ?? '';
}

/**
 * Comms-aware onboarding step. Explains that connecting a communications provider
 * lights up Campaign 360 + Profile 360, shows the current connection status via
 * the canonical CapabilityStateBadge, and launches the existing connection wizard
 * for any registered comms connector. Skip/Continue are pure UI and never call
 * the connector API, so onboarding is never hard-blocked on an external credential.
 */
export function CommsConnectOnboardingStep({ onSkip, onContinue }: Props) {
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [selectedType, setSelectedType] = useState('');
  const [load, setLoad] = useState<LoadState>('loading');
  const [configuring, setConfiguring] = useState(false);
  const [skipped, setSkipped] = useState(false);

  function refresh() {
    setLoad('loading');
    // Degrade gracefully if the connectors API surface is unavailable (missing,
    // misconfigured, or offline) instead of hard-blocking onboarding — the user
    // can always skip and connect a communications provider later from Integrations.
    try {
      const result = api.connectors?.list?.();
      if (!result) { setConnectors([]); setLoad('error'); return; }
      Promise.resolve(result)
        .then((r) => {
          const items = Array.isArray(r) ? r : ((r as { items?: ConnectorInfo[] })?.items ?? []);
          const comms = items.filter(isCommsConnector);
          setConnectors(comms);
          setSelectedType((prev) => prev && comms.some((c) => c.connector_type === prev)
            ? prev
            : defaultCommsType(comms));
          setLoad('ready');
        })
        .catch(() => { setConnectors([]); setLoad('error'); });
    } catch {
      setConnectors([]);
      setLoad('error');
    }
  }

  useEffect(() => { refresh(); }, []);

  const connector = connectors.find((c) => c.connector_type === selectedType) ?? connectors[0] ?? null;
  const connected = Boolean(connector?.enabled && connector?.secret_configured);
  const label = connector?.label ?? 'communications provider';

  return (
    <Card data-testid="comms-connect-onboarding-step">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <CardTitle>Connect Communications</CardTitle>
            {connectors.length > 1 && (
              <select
                aria-label="Communications provider"
                value={connector?.connector_type ?? ''}
                onChange={(e) => setSelectedType(e.target.value)}
                className="text-xs bg-surface-secondary border border-border rounded px-2 py-1"
              >
                {connectors.map((c) => (
                  <option key={c.connector_type} value={c.connector_type}>{c.label}</option>
                ))}
              </select>
            )}
          </div>
          {load === 'loading'
            ? <span className="text-xs text-text-muted">Checking connection status…</span>
            : <CapabilityStateBadge state={commsState(connector)} label={connector?.label ?? '—'} reason={`connector sync_status: ${connector?.sync_status ?? 'unknown'}`} />}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-text-muted">
          Connecting a communications provider lights up Campaign 360 and Profile 360 with
          delivery, open, click, reply, and suppression intelligence — email lifecycle events become
          canonical comms facts feeding each campaign’s message funnel and every profile’s
          communications timeline.
        </p>
        {load === 'error' && (
          <p className="text-xs text-warning">Connector status is unavailable right now. You can skip this step and connect a communications provider later from Integrations.</p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => setConfiguring(true)} disabled={load === 'loading' || !connector}>
            {connected ? `Manage ${label}` : `Connect ${label}`}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => { setSkipped(true); onSkip?.(); }}>Skip for now</Button>
          <Button size="sm" variant="secondary" onClick={() => onContinue?.()}>Continue</Button>
          {skipped && <span className="text-xs text-text-muted">Skipped — connect a communications provider later from Integrations.</span>}
        </div>
      </CardContent>
      {configuring && connector && (
        <ConnectorConfigModal
          connector={connector}
          onClose={() => setConfiguring(false)}
          onSaved={() => { setConfiguring(false); refresh(); }}
        />
      )}
    </Card>
  );
}
