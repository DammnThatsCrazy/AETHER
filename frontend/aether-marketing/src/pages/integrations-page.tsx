import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@aether/ui";
import {
  CtaBand,
  Eyebrow,
  PageHero,
} from "@aether-marketing/components/marketing-section";
import type { CtaLink } from "@aether-marketing/components/marketing-section";
import {
  CONNECTORS,
  CONNECTOR_CATEGORIES,
  CONNECTOR_STATUS_LABELS,
  EXPERIENCE_LABELS,
  PRESENT_EXPERIENCES,
} from "@aether-marketing/content/connectors";
import type {
  ConnectorAuth,
  ConnectorRecord,
  ConnectorReadiness,
  ExperienceToken,
} from "@aether-marketing/content/connectors";
import { findSection } from "@aether-marketing/content/sections";
import { buildIntegrationsHandoffUrl } from "@aether-marketing/lib/handoff";
import { AETHER_DOCS_URL } from "@aether-marketing/lib/env";
import { usePageMeta } from "@aether-marketing/lib/meta";

/** Short display form for a real ConnectorCategory literal (marketing voice). */
const ACRONYM_CATEGORY = new Set<string>(["crm"]);

function categoryLabel(category: string): string {
  return category
    .split("_")
    .map((word) =>
      ACRONYM_CATEGORY.has(word)
        ? word.toUpperCase()
        : `${word.charAt(0).toUpperCase()}${word.slice(1)}`,
    )
    .join(" ");
}

/** Short public label per real authentication token (catalog's auth vocabulary). */
const AUTH_LABELS: Readonly<Record<ConnectorAuth, string>> = {
  api_key: "API key",
  webhook_only: "Webhook credential",
  none: "No credential",
};

/** Statuses actually present in the dataset (every registry connector is at
 * credential_waiting in this snapshot) — the facet is built from real tokens,
 * never from an imagined list. */
const PRESENT_STATUSES: readonly ConnectorReadiness[] = [
  ...new Set(CONNECTORS.map((connector) => connector.status)),
].sort();

function chipClass(pressed: boolean): string {
  return pressed
    ? "border-accent bg-surface-raised text-text-primary"
    : "border-border-default bg-surface-raised text-text-secondary hover:border-accent hover:text-text-primary";
}

/** The /integrations route is served from the SECTIONS entry of the same slug;
 * this page is the interactive rendering of that entry. */
export function IntegrationsPage() {
  const section = findSection("/integrations");

  usePageMeta(
    section !== undefined
      ? {
          title: `${section.title} — Aether by Olympus Labs`,
          description: section.description,
        }
      : { title: "Aether by Olympus Labs" },
  );

  const [query, setQuery] = useState("");
  const [categories, setCategories] = useState<readonly string[]>([]);
  const [experiences, setExperiences] = useState<readonly ExperienceToken[]>(
    [],
  );
  const [statuses, setStatuses] = useState<readonly ConnectorReadiness[]>([]);

  const term = query.trim().toLowerCase();

  const filtered = useMemo(
    () =>
      CONNECTORS.filter((connector) => {
        if (categories.length > 0 && !categories.includes(connector.category)) {
          return false;
        }
        if (
          experiences.length > 0 &&
          !experiences.includes(connector.experience)
        ) {
          return false;
        }
        if (statuses.length > 0 && !statuses.includes(connector.status)) {
          return false;
        }
        if (term !== "") {
          const haystack =
            `${connector.name} ${connector.description} ${connector.category} ${categoryLabel(
              connector.category,
            )} ${EXPERIENCE_LABELS[connector.experience]}`.toLowerCase();
          if (!haystack.includes(term)) {
            return false;
          }
        }
        return true;
      }),
    [categories, experiences, statuses, term],
  );

  const filtersActive =
    term !== "" ||
    categories.length > 0 ||
    experiences.length > 0 ||
    statuses.length > 0;

  function toggleCategory(category: string): void {
    setCategories((current) =>
      current.includes(category)
        ? current.filter((value) => value !== category)
        : [...current, category],
    );
  }

  function toggleExperience(experience: ExperienceToken): void {
    setExperiences((current) =>
      current.includes(experience)
        ? current.filter((value) => value !== experience)
        : [...current, experience],
    );
  }

  function toggleStatus(status: ConnectorReadiness): void {
    setStatuses((current) =>
      current.includes(status)
        ? current.filter((value) => value !== status)
        : [...current, status],
    );
  }

  function clearFilters(): void {
    setQuery("");
    setCategories([]);
    setExperiences([]);
    setStatuses([]);
  }

  if (section === undefined) {
    return (
      <div className="mkt-container py-24">
        <h1 className="mkt-display">Page not found</h1>
        <p className="mkt-lead mt-4 max-w-xl">
          This section does not exist yet.
        </p>
        <p className="mt-8">
          <Button asChild variant="primary">
            <Link to="/">Back to the Aether home page</Link>
          </Button>
        </p>
      </div>
    );
  }

  const primaryCta: CtaLink =
    section.cta !== undefined
      ? {
          label: section.cta.label,
          to: section.cta.to,
          external: section.cta.external ?? false,
        }
      : {
          label: "Read the integration documentation",
          to: AETHER_DOCS_URL,
          external: true,
        };

  return (
    <>
      <PageHero
        eyebrow={section.eyebrow}
        title={section.title}
        lead={section.lead}
      />

      {/* Interactive directory */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <Eyebrow>Connector registry</Eyebrow>
              <h2 className="mkt-h2 mt-4">Connector directory</h2>
            </div>
            <p>
              <Button asChild variant="secondary" size="md">
                <a href={AETHER_DOCS_URL} target="_blank" rel="noreferrer">
                  Browse connector documentation
                </a>
              </Button>
            </p>
          </div>

          <div className="mt-6 max-w-3xl space-y-4">
            <p className="mkt-body text-text-secondary">
              These entries come from Aether’s derived one-customer catalog —
              the same vocabulary the product’s Settings → Integrations surface
              is built on — and are listed at the availability state the runtime
              records for each. Nothing here is pre-announced or invented, and
              no entry is shown as live before the runtime can demonstrate it.
            </p>
            <p className="mkt-body text-text-secondary">
              The directory covers the connectable catalog families Aether
              advertises publicly: the inbound connector registry (commerce,
              CRM, communications, analytics, support, and work connectors that
              read provider activity in) and the advertising measurement
              platforms (campaign spend pulled into measurement). Every entry is
              read-inbound — Aether reads provider activity in, and none pushes
              data outbound today.
            </p>
            <p className="mkt-body text-text-secondary">
              Today every listed family is credential-gated and shown as
              “Credentials required”: the connector code and wiring are in
              place, but none has been validated against live provider traffic.
              A partial or credential-gated connector is never shown as live.
              Connecting an entry opens the Aether app, where you sign in and
              the product walks the real connect flow for that provider.
            </p>
          </div>

          <div className="mt-10">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
              <div className="w-full max-w-md">
                <label
                  htmlFor="connector-search"
                  className="text-sm font-medium text-text-primary"
                >
                  Search connectors
                </label>
                <input
                  id="connector-search"
                  type="search"
                  aria-label="Search connectors"
                  placeholder="Search by provider, experience, or category"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="mt-2 w-full rounded-md border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                />
              </div>
              {filtersActive && (
                <button
                  type="button"
                  onClick={clearFilters}
                  className="inline-flex items-center gap-2 rounded-md border border-border-default bg-surface-raised px-3 py-2 text-sm font-medium text-text-secondary mkt-motion-color hover:border-accent hover:text-text-primary"
                >
                  Clear filters
                </button>
              )}
            </div>

            <div className="mt-8 flex flex-col gap-6">
              <FacetGroup label="Filter by experience">
                {PRESENT_EXPERIENCES.map((experience) => {
                  const pressed = experiences.includes(experience);
                  return (
                    <li key={experience}>
                      <button
                        type="button"
                        aria-pressed={pressed}
                        onClick={() => toggleExperience(experience)}
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs mkt-motion-color-standard ${chipClass(
                          pressed,
                        )}`}
                      >
                        {EXPERIENCE_LABELS[experience]}
                      </button>
                    </li>
                  );
                })}
              </FacetGroup>
              <FacetGroup label="Filter by category">
                {CONNECTOR_CATEGORIES.map((category) => {
                  const pressed = categories.includes(category);
                  return (
                    <li key={category}>
                      <button
                        type="button"
                        aria-pressed={pressed}
                        onClick={() => toggleCategory(category)}
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-xs mkt-motion-color-standard ${chipClass(
                          pressed,
                        )}`}
                      >
                        {categoryLabel(category)}
                      </button>
                    </li>
                  );
                })}
              </FacetGroup>
              <FacetGroup label="Filter by status">
                {PRESENT_STATUSES.map((status) => {
                  const pressed = statuses.includes(status);
                  return (
                    <li key={status}>
                      <button
                        type="button"
                        aria-pressed={pressed}
                        onClick={() => toggleStatus(status)}
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-xs mkt-motion-color-standard ${chipClass(
                          pressed,
                        )}`}
                      >
                        {CONNECTOR_STATUS_LABELS[status]}
                      </button>
                    </li>
                  );
                })}
              </FacetGroup>
            </div>

            <p role="status" className="mkt-body mt-8 text-text-secondary">
              Showing {filtered.length} of {CONNECTORS.length} connectors
            </p>

            {filtered.length === 0 ? (
              <div className="mt-4 rounded-md border border-border-default bg-surface-base p-6">
                <p className="mkt-body font-medium text-text-primary">
                  No connector matches the current search and filters.
                </p>
                <p className="mkt-body mt-2 text-text-secondary">
                  Try a different search term, or clear the filters to see the
                  full registry.
                </p>
                <p className="mt-4">
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="inline-flex items-center gap-2 rounded-md border border-border-default bg-surface-raised px-3 py-2 text-sm font-medium text-text-secondary mkt-motion-color hover:border-accent hover:text-text-primary"
                  >
                    Clear filters
                  </button>
                </p>
              </div>
            ) : (
              <ul className="mt-4 flex flex-col gap-4">
                {filtered.map((connector) => (
                  <ConnectorRow key={connector.id} connector={connector} />
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      {/* The /integrations editorial paragraphs, rendered as SectionPage renders them. */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          {section.paragraphs !== undefined && (
            <div className="mkt-measure space-y-5">
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph} className="mkt-body text-text-secondary">
                  {paragraph}
                </p>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* CTA band matching the /integrations entry CTA (external docs primary,
          sign-up secondary). Copy mirrors section-page's docs CTA band. */}
      <CtaBand
        title="Go deeper in the documentation"
        body="Aether’s documentation site carries the technical depth behind the platform — the event model, identity resolution, consent, connectors, and validation."
        primary={primaryCta}
        secondary={{ label: "Start building", to: "/signup" }}
      />
    </>
  );
}

/** One searchable/filterable row for a connectable catalog family. */
function ConnectorRow({ connector }: { readonly connector: ConnectorRecord }) {
  const connectHref = buildIntegrationsHandoffUrl({
    family: connector.id,
    experience: connector.experience,
  });
  return (
    <li className="rounded-md border border-border-default bg-surface-base p-6">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 max-w-3xl">
          <h3 className="text-base font-semibold tracking-tight text-text-primary">
            {connector.name}
          </h3>
          <p className="mt-1.5 text-sm leading-relaxed text-text-secondary">
            {connector.description}
          </p>
        </div>
        <p
          className="mkt-chip"
          title={`Runtime readiness token: ${connector.status}`}
        >
          {CONNECTOR_STATUS_LABELS[connector.status]}
        </p>
      </div>
      <ul className="mt-4 flex flex-wrap items-center gap-2">
        <li>
          <span
            className="mkt-chip"
            title={`Customer experience token: ${connector.experience}`}
          >
            {EXPERIENCE_LABELS[connector.experience]}
          </span>
        </li>
        <li>
          <span className="mkt-chip">{categoryLabel(connector.category)}</span>
        </li>
        <li>
          <span className="mkt-chip">{AUTH_LABELS[connector.auth]}</span>
        </li>
        {connector.pull && (
          <li>
            <span className="mkt-chip">Pull</span>
          </li>
        )}
        {connector.webhook && (
          <li>
            <span className="mkt-chip">Webhook</span>
          </li>
        )}
        <li>
          <span className="mkt-chip">Inbound</span>
        </li>
      </ul>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-border-default pt-4">
        <p className="text-sm text-text-secondary">
          Open the Aether app to sign in and run the real connect flow for this
          provider.
        </p>
        <a
          href={connectHref}
          aria-label={`Connect ${connector.name}`}
          className="inline-flex items-center gap-2 rounded-md border border-border-default bg-surface-raised px-3 py-2 text-sm font-medium text-text-primary mkt-motion-color hover:border-accent hover:text-text-primary"
        >
          Connect
        </a>
      </div>
    </li>
  );
}

/** One labeled group of facet toggle buttons. */
function FacetGroup({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}) {
  return (
    <div role="group" aria-label={label}>
      <p className="mkt-eyebrow">{label}</p>
      <ul className="mt-3 flex flex-wrap gap-2">{children}</ul>
    </div>
  );
}
