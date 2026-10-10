import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import { resolveStatusConfig } from './config';

type HealthState = 'operational' | 'degraded' | 'outage' | 'unknown';

interface HealthSnapshot {
  readonly state: HealthState;
  readonly detail: string;
  readonly checkedAt: string | null;
  readonly components: readonly HealthComponent[];
}

interface HealthComponent {
  readonly key: string;
  readonly label: string;
  readonly state: HealthState;
  readonly detail: string;
}

interface HealthPayload {
  readonly status?: unknown;
  readonly components?: unknown;
}

const statusConfig = resolveStatusConfig({
  VITE_STATUS_API_URL: import.meta.env.VITE_STATUS_API_URL,
  VITE_STATUS_DOCS_URL: import.meta.env.VITE_STATUS_DOCS_URL,
  VITE_STATUS_AETHER_MARKETING_URL: import.meta.env.VITE_STATUS_AETHER_MARKETING_URL,
});

const COMPONENT_LABELS: Readonly<Record<string, string>> = {
  ingestion: 'Ingestion & processing',
  identity: 'Identity & graph',
  analytics: 'Analytics & perspective',
  ml_serving: 'Model serving',
  agent: 'Agent intelligence',
  campaign: 'Campaign intelligence',
  consent: 'Consent & tenant governance',
  notification: 'Delivery & workflow',
  admin: 'Tenant administration',
  rewards: 'Rewards',
  commerce: 'Commerce',
  provider_credentials: 'Providers & connectors',
};

function stateFromBackend(value: unknown): HealthState {
  if (value === 'ok' || value === 'healthy') return 'operational';
  if (value === 'degraded') return 'degraded';
  if (value === 'down') return 'outage';
  return 'unknown';
}

function componentDetail(value: unknown): string {
  if (!value || typeof value !== 'object') return 'The monitored service did not provide component detail.';
  const record = value as { readonly signals?: unknown };
  if (!record.signals || typeof record.signals !== 'object') {
    return 'The monitored service did not provide component detail.';
  }
  for (const signal of Object.values(record.signals)) {
    if (signal && typeof signal === 'object') {
      const detail = (signal as { readonly detail?: unknown }).detail;
      if (typeof detail === 'string' && detail.trim()) return detail;
    }
  }
  return 'The monitored service reported a component state without additional detail.';
}

function componentsFromPayload(payload: HealthPayload): readonly HealthComponent[] {
  if (!payload.components || typeof payload.components !== 'object') return [];
  return Object.entries(payload.components as Record<string, unknown>)
    .map(([key, value]) => {
      const status = value && typeof value === 'object'
        ? (value as { readonly status?: unknown }).status
        : undefined;
      return {
        key,
        label: COMPONENT_LABELS[key] ?? key.replace(/_/g, ' '),
        state: stateFromBackend(status),
        detail: componentDetail(value),
      };
    })
    .sort((left, right) => left.label.localeCompare(right.label));
}

async function classify(response: Response): Promise<HealthSnapshot> {
  const checkedAt = new Date().toISOString();
  if (!response.ok) {
    return {
      state: 'degraded',
      detail: 'The monitored API health endpoint returned a non-success response.',
      checkedAt,
      components: [],
    };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return {
      state: 'unknown',
      detail: 'The monitored endpoint responded, but its health payload could not be verified.',
      checkedAt,
      components: [],
    };
  }
  if (!body || typeof body !== 'object') {
    return {
      state: 'unknown',
      detail: 'The monitored endpoint returned no structured health payload.',
      checkedAt,
      components: [],
    };
  }

  const payload = body as HealthPayload;
  const components = componentsFromPayload(payload);
  const state = stateFromBackend(payload.status);
  return {
    state,
    detail:
      state === 'operational'
        ? 'The monitored API and its reported component surfaces are operational.'
        : state === 'degraded'
          ? 'The monitored API is reachable, but one or more reported component surfaces are degraded.'
          : 'The monitored API returned a health state that is not verified by this status surface.',
    checkedAt,
    components,
  };
}

async function checkHealth(signal: AbortSignal): Promise<HealthSnapshot> {
  if (!statusConfig.statusApiUrl) {
    return {
      state: 'unknown',
      detail: 'The live monitoring source has not been connected to this status surface.',
      checkedAt: null,
      components: [],
    };
  }
  try {
    const response = await fetch(statusConfig.statusApiUrl, {
      signal,
      headers: { Accept: 'application/json' },
    });
    return classify(response);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    return {
        state: 'outage',
        detail: 'The monitored health endpoint could not be reached from the status surface.',
        checkedAt: new Date().toISOString(),
        components: [],
    };
  }
}

function App() {
  const [snapshot, setSnapshot] = useState<HealthSnapshot>({
    state: 'unknown',
    detail: 'Checking the monitored service.',
    checkedAt: null,
    components: [],
  });

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    void checkHealth(controller.signal)
      .then(setSnapshot)
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          setSnapshot({
            state: 'unknown',
            detail: 'The monitoring check did not complete.',
            checkedAt: new Date().toISOString(),
            components: [],
          });
        }
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  const stateLabel =
    snapshot.state === 'operational'
      ? 'Operational'
      : snapshot.state === 'degraded'
        ? 'Degraded performance'
        : snapshot.state === 'outage'
          ? 'Investigating an incident'
          : 'Status not yet verified';

  return (
    <main className="status-shell">
      <div className="status-card">
        <p className="eyebrow">Olympus Labs · Aether</p>
        <h1>Service status</h1>
        <p className={'state state-' + snapshot.state} role="status">
          <span className="state-dot" aria-hidden="true" />
          {stateLabel}
        </p>
        <p className="detail">{snapshot.detail}</p>
        <section className="component" aria-labelledby="component-title">
          <div>
            <h2 id="component-title">Aether API</h2>
            <p>Tenant-facing application and API health.</p>
          </div>
          <span className={'badge badge-' + snapshot.state}>{stateLabel}</span>
        </section>
        {snapshot.components.length > 0 && (
          <section className="component-list" aria-labelledby="component-list-title">
            <h2 id="component-list-title">Reported service surfaces</h2>
            {snapshot.components.map((component) => {
              const componentLabel =
                component.state === 'operational'
                  ? 'Operational'
                  : component.state === 'degraded'
                    ? 'Degraded performance'
                    : component.state === 'outage'
                      ? 'Unavailable'
                      : 'Not verified';
              return (
                <div className="component-row" key={component.key}>
                  <div className="component-copy">
                    <h3>{component.label}</h3>
                    <p>{component.detail}</p>
                  </div>
                  <span className={'badge badge-' + component.state}>{componentLabel}</span>
                </div>
              );
            })}
          </section>
        )}
        <p className="fine-print">
          This page reports only what the configured monitor can verify. Provider readiness, planned
          features, and tenant-specific connectivity are separate states.
        </p>
        <nav className="links" aria-label="Status resources">
          <a href={`${statusConfig.docsUrl}/operations/status`}>Status documentation</a>
          <a href={`${statusConfig.aetherMarketingUrl}/contact`}>Contact Aether</a>
        </nav>
        {snapshot.checkedAt && (
          <p className="checked">Last checked {new Date(snapshot.checkedAt).toLocaleString()}</p>
        )}
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
