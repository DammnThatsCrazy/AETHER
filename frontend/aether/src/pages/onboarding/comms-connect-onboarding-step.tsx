import { useEffect, useState } from 'react';
import { Button, Card, CardContent, CardHeader, CardTitle, CapabilityStateBadge, resolveCapabilityState, type CapabilityState } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { ConnectorConfigModal } from '@aether-app/pages/connectors/connector-config-modal';

// Communications provider in the backend connector catalog (marketing-email
// lifecycle → canonical comms events feeding Campaign 360 + Profile 360).
const COMMS_CONNECTOR_TYPE = 'klaviyo';

interface ConnectorInfo {
  readonly connector_type: string;
  readonly label: string;
  readonly description: string;
  readonly requires_secret: boolean;
  readonly enabled: boolean;
  readonly secret_configured: boolean;
  readonly sync_status: string;
}

interface Props {
  readonly onSkip?: () => void;
  readonly onContinue?: () => void;
}

type LoadState = 'loading' | 'ready' | 'error';

// Honest connection status for the comms connector. Availability gates win first,
// then the raw sync_status maps onto the shared matrix; nothing not-live reads green.
function commsState(c: ConnectorInfo | null): CapabilityState {
  if (!c) return 'not_configured';
  if (!c.enabled) return 'disabled';
  if (!c.secret_configured) return 'credential_required';
  return resolveCapabilityState(c.sync_status) ?? 'credential_waiting';
}

/**
 * Comms-aware onboarding step. Explains that connecting a communications provider
 * (Klaviyo) lights up Campaign 360 + Profile 360, shows the current connection
 * status via the canonical CapabilityStateBadge, and launches the existing
 * connection wizard. Skip/Continue are pure UI and never call the connector API,
 * so onboarding is never hard-blocked on an external credential.
 */
export function CommsConnectOnboardingStep({ onSkip, onContinue }: Props) {
  const [connector, setConnector] = useState<ConnectorInfo | null>(null);
  const [load, setLoad] = useState<LoadState>('loading');
  const [configuring, setConfiguring] = useState(false);
  const [skipped, setSkipped] = useState(false);

  function refresh() {
    setLoad('loading');
    // Degrade gracefully if the connectors API surface is unavailable (missing,
    // misconfigured, or offline) instead of hard-blocking onboarding — the user
    // can always skip and connect Klaviyo later from Integrations.
    try {
      const result = api.connectors?.get?.(COMMS_CONNECTOR_TYPE);
      if (!result) { setConnector(null); setLoad('error'); return; }
      Promise.resolve(result)
        .then((r) => { setConnector(r as ConnectorInfo); setLoad('ready'); })
        .catch(() => { setConnector(null); setLoad('error'); });
    } catch {
      setConnector(null);
      setLoad('error');
    }
  }

  useEffect(() => { refresh(); }, []);

  const connected = Boolean(connector?.enabled && connector?.secret_configured);

  return (
    <Card data-testid="comms-connect-onboarding-step">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Connect Communications (Klaviyo)</CardTitle>
          {load === 'loading'
            ? <span className="text-xs text-text-muted">Checking connection status…</span>
            : <CapabilityStateBadge state={commsState(connector)} label={connector?.label ?? 'Klaviyo'} reason={`connector sync_status: ${connector?.sync_status ?? 'unknown'}`} />}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-text-muted">
          Connecting a communications provider (Klaviyo) lights up Campaign 360 and Profile 360 with
          delivery, open, click, reply, and suppression intelligence — email lifecycle events become
          canonical comms facts feeding each campaign’s message funnel and every profile’s
          communications timeline.
        </p>
        {load === 'error' && (
          <p className="text-xs text-warning">Connector status is unavailable right now. You can skip this step and connect Klaviyo later from Integrations.</p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => setConfiguring(true)} disabled={load === 'loading' || !connector}>
            {connected ? 'Manage Klaviyo' : 'Connect Klaviyo'}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => { setSkipped(true); onSkip?.(); }}>Skip for now</Button>
          <Button size="sm" variant="secondary" onClick={() => onContinue?.()}>Continue</Button>
          {skipped && <span className="text-xs text-text-muted">Skipped — connect Klaviyo later from Integrations.</span>}
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
