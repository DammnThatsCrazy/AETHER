import { useEffect, useRef } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  ProviderMark,
  StatusIndicator,
  formatDateTime,
  useTimeContext,
} from "@aether/ui";
import { useTenantIntegrations } from "@aether-app/features/integrations";
import type { TenantIntegrationItem } from "@aether-app/features/integrations";
import { isWorkspaceDestination } from "@aether-app/features/workspace/last-workspace";
import {
  catalogBaselineCaption,
  groupByExperienceCategory,
  tenantConnectionStatus,
  tenantConnectionStateToken,
} from "@aether-app/features/settings";
import { parseSettingsHandoff } from "@aether-app/features/settings/settings-handoff";

/** Route target for the reused connector manager (the Connect/Manage surface). */
const CONNECT_MANAGER_ROUTE = "/settings/integrations/connectors";
/** Advertising-family rows route into the dedicated ad connect flow instead. */
const AD_SOURCES_ROUTE = "/campaign-intelligence/sources";
/** Default return target after a Settings-initiated ad connect completes. */
const DEFAULT_AD_RETURN = "/settings/integrations";

/**
 * The return target an advertising connect should navigate to on completion.
 * When the tenant reached this Settings section carrying a ``?return=`` param
 * (the Campaign Sources empty state deep-links back here), that target is
 * forwarded through the ad connect deep link so the round trip completes where
 * the tenant started. A raw query param is untrusted, so only a clean internal
 * workspace path is forwarded; otherwise the connect returns here.
 */
function resolveAdReturnTarget(search: string): string {
  const raw = new URLSearchParams(search).get("return");
  return raw !== null && isWorkspaceDestination(raw) ? raw : DEFAULT_AD_RETURN;
}

function IntegrationRow({ item }: { readonly item: TenantIntegrationItem }) {
  const location = useLocation();
  const timeCtx = useTimeContext();
  const status = tenantConnectionStatus(item);
  const stateToken = tenantConnectionStateToken(item);
  const baseline = catalogBaselineCaption(item.readiness?.state);
  const isAdvertising = item.experience_category === "advertising_campaigns";
  const adReturnTarget = resolveAdReturnTarget(location.search);

  return (
    <div
      data-provider-family={item.family}
      className={[
        "flex items-center justify-between rounded border border-border-default px-3 py-2 gap-2",
        "data-[handoff-focus=true]:ring-2 data-[handoff-focus=true]:ring-border-focus data-[handoff-focus=true]:border-border-focus",
      ].join(" ")}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <ProviderMark provider={item.family} decorative size={20} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-text-primary truncate">
              {item.display_name}
            </span>
            {!item.enabled && item.connected === false && (
              <Badge variant="default" size="sm">
                available
              </Badge>
            )}
          </div>
          <div className="text-xs text-text-muted truncate">
            {item.last_synced_at
              ? `Last synced ${formatDateTime(item.last_synced_at, timeCtx)}`
              : "Never synced"}
            {baseline ? (
              <span className="text-text-muted/70"> · {baseline}</span>
            ) : null}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2 ml-2 shrink-0">
        <div className="text-right">
          <div className="flex items-center justify-end gap-1.5">
            <StatusIndicator status={status.indicator} />
            <span
              className="text-xs font-mono text-text-secondary"
              data-connection-state={stateToken}
            >
              {status.label}
            </span>
          </div>
          {status.detail && (
            <div className="text-[10px] text-text-muted">{status.detail}</div>
          )}
        </div>
        {isAdvertising ? (
          <Button asChild size="sm" variant="secondary">
            <Link
              to={`${AD_SOURCES_ROUTE}?connect=${encodeURIComponent(item.family)}&return=${encodeURIComponent(adReturnTarget)}`}
            >
              {stateToken === "not_connected" ? "Connect" : "Manage"}
            </Link>
          </Button>
        ) : (
          <Button asChild size="sm" variant="secondary">
            <Link to={CONNECT_MANAGER_ROUTE}>Manage</Link>
          </Button>
        )}
      </div>
    </div>
  );
}

/**
 * Settings → Integrations (WS-1). Lists the tenant's configured integrations
 * from the R1 read model (/v1/tenant-integrations), grouped by experience
 * category. Statuses are connection-record facts only — "Ready" is never
 * inferred and catalog readiness is surfaced as a muted baseline caption, never
 * as the tenant's state. Renders honest loading / unavailable / empty states
 * when the catalog is empty or unreachable (connectors are flag-gated OFF by
 * default).
 */
/**
 * Find the rendered row for a provider family inside the lifecycle catalog, if
 * the tenant's records actually contain that provider. Returns null when the
 * family is absent so a handoff never highlights a row that is not there.
 */
function findIntegrationRow(family: string): HTMLElement | null {
  const catalog = document.querySelector("[data-lifecycle-catalog]");
  const root = catalog ?? document;
  for (const el of Array.from(
    root.querySelectorAll("[data-provider-family]"),
  )) {
    if (el.getAttribute("data-provider-family") === family) {
      return el as HTMLElement;
    }
  }
  return null;
}

export function IntegrationsSection() {
  const tenant = useTenantIntegrations();
  const location = useLocation();
  const items = tenant.data?.items ?? null;

  // Marketing→app handoff (frontend/aether-marketing/src/lib/handoff.ts):
  // /settings/integrations?family=…&experience=…&intent=connect|manage.
  const handoff = parseSettingsHandoff(location.search);
  const scrolledFamily = useRef<string | null>(null);

  // One-shot transient highlight: when the URL names a provider family that is
  // actually rendered, focus that row (scroll it into view once) and give it a
  // visible ring for ~2.5s. Never auto-navigates and never fabricates state.
  useEffect(() => {
    if (handoff.family === null) return;
    const row = findIntegrationRow(handoff.family);
    if (!row) return;
    row.setAttribute("data-handoff-focus", "true");
    if (scrolledFamily.current !== handoff.family) {
      scrolledFamily.current = handoff.family;
      row.scrollIntoView({ block: "center", behavior: "smooth" });
    }
    const timer = window.setTimeout(() => {
      row.removeAttribute("data-handoff-focus");
    }, 2500);
    return () => window.clearTimeout(timer);
  }, [handoff.family, items]);

  if (tenant.isLoading && !items) {
    return (
      <div className="space-y-3">
        <span className="text-sm font-mono text-text-muted">Integrations</span>
        <LoadingState lines={5} />
      </div>
    );
  }

  if (tenant.error && !items) {
    return (
      <>
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm font-mono text-text-muted">
            Integrations
          </span>
        </div>
        <ErrorState
          title="Integrations unavailable"
          message="We couldn't load this workspace's integrations. The integrations service may not be enabled here — SDK ingestion is always available. Try again in a moment."
          onRetry={tenant.refetch}
        />
      </>
    );
  }

  if (!items || items.length === 0) {
    return (
      <div className="space-y-4">
        <span className="text-sm font-mono text-text-muted">Integrations</span>
        <EmptyState
          title="No integrations connected"
          description="Connect a platform to bring data into Aether without the SDK. SDK ingestion remains available and is not required."
          action={
            <Button asChild variant="primary" size="sm">
              <Link to={CONNECT_MANAGER_ROUTE}>Connect an integration</Link>
            </Button>
          }
        />
      </div>
    );
  }

  const groups = groupByExperienceCategory(items);

  // The handoff names one rendered provider (already sanitized by the parser).
  const handoffItem =
    handoff.family !== null
      ? (items.find((item) => item.family === handoff.family) ?? null)
      : null;
  // "came to connect": only when the intended action is connect AND the named
  // provider is not already engaged (a not_connected record). Never auto-acts.
  const showConnectCallout =
    handoff.intent === "connect" &&
    handoffItem !== null &&
    tenantConnectionStateToken(handoffItem) === "not_connected";

  return (
    <div className="space-y-5" data-lifecycle-catalog>
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm font-mono text-text-muted">
            Integrations
          </span>
          <p className="text-xs text-text-secondary mt-0.5">
            Connection status reflects this workspace&apos;s records. Live data
            readiness is never inferred — a connected integration is not assumed
            to be flowing data until a sync completes.
          </p>
        </div>
        <Button asChild variant="primary" size="sm">
          <Link to={CONNECT_MANAGER_ROUTE}>Connect</Link>
        </Button>
      </div>

      {groups.map((group) => {
        const isHandoffGroup =
          handoffItem !== null &&
          group.items.some((item) => item.family === handoffItem.family);
        return (
          <div key={group.key || "__other__"}>
            {showConnectCallout && isHandoffGroup && handoffItem && (
              <p
                data-handoff-callout
                className="mb-2 rounded border border-accent/30 bg-surface-raised px-3 py-2 text-xs text-text-secondary"
              >
                You came to connect {handoffItem.display_name} — continue below
              </p>
            )}
            <section aria-label={group.label}>
              <h2 className="text-xs font-mono uppercase tracking-wide text-text-muted mb-2">
                {group.label}
              </h2>
              <div className="grid gap-2 md:grid-cols-2">
                {group.items.map((item) => (
                  <IntegrationRow key={item.id} item={item} />
                ))}
              </div>
            </section>
          </div>
        );
      })}

      <p className="text-[10px] text-text-muted font-mono pt-1">
        {items.length} configured integration{items.length === 1 ? "" : "s"} ·{" "}
        <Link
          to={CONNECT_MANAGER_ROUTE}
          className="text-accent hover:text-accent-hover"
        >
          Manage connectors
        </Link>
      </p>
    </div>
  );
}
