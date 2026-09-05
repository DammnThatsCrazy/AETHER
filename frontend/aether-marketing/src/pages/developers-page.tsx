import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, cn } from '@aether/ui';
import {
  CtaBand,
  Eyebrow,
  PageHero,
} from '@aether-marketing/components/marketing-section';
import { DEFAULT_PATH_ID, DEVELOPER_PATHS, findDeveloperPath } from '@aether-marketing/content/developer-paths';
import { findSection } from '@aether-marketing/content/sections';
import { AETHER_DOCS_URL } from '@aether-marketing/lib/env';
import { usePageMeta } from '@aether-marketing/lib/meta';

/**
 * Aether /developers marketing page.
 *
 * The signature interaction is a truthful developer-path selector: a keyboard-
 * accessible radio group of four integration questions (send events, resolve
 * identity, govern consent, connect integrations) that swaps the adjacent panel
 * between the paths. Each path states what that step involves today and points
 * at the documentation site as the canonical reference; nothing here replaces
 * the docs or invents an SDK artifact, CLI, or API that does not exist.
 */
export function DevelopersPage() {
  const section = findSection('/developers');
  const [activeId, setActiveId] = useState<string>(DEFAULT_PATH_ID);

  usePageMeta(
    section !== undefined
      ? { title: `${section.title} — Aether by Olympus Labs`, description: section.description }
      : { title: 'Aether by Olympus Labs' },
  );

  if (section === undefined) {
    return (
      <div className="mkt-container py-24">
        <h1 className="mkt-display">Page not found</h1>
        <p className="mkt-lead mt-4 max-w-xl">This section does not exist yet.</p>
        <p className="mt-8">
          <Button asChild variant="primary">
            <Link to="/">Back to the Aether home page</Link>
          </Button>
        </p>
      </div>
    );
  }

  const { cta } = section;
  // The active path is always one of DEVELOPER_PATHS (the radios are driven by
  // that list and only ever set activeId to a real id), so the fallback is
  // unreachable; it keeps the panel total even if a future editor reorders ids.
  const activePath = findDeveloperPath(activeId) ?? DEVELOPER_PATHS[0];

  return (
    <>
      <PageHero eyebrow={section.eyebrow} title={section.title} lead={section.lead} />

      {/* Developer-path selector */}
      <section aria-labelledby="developer-paths-heading" className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          <div className="grid gap-10 lg:grid-cols-12">
            <div className="lg:col-span-5">
              <Eyebrow>Choose a path</Eyebrow>
              <h2 id="developer-paths-heading" className="mkt-h2 mt-3">
                Start from the question you are answering
              </h2>
              <p className="mkt-body mt-4 text-text-secondary">
                Select the integration question a practitioner asks first. The path shows what that
                step involves today; the documentation site is the canonical reference for schemas,
                SDKs, the event model, identity resolution, consent, connectors, and validation.
              </p>
              <fieldset className="mt-8">
                <legend className="sr-only">Developer path</legend>
                <div className="space-y-3">
                  {DEVELOPER_PATHS.map((path) => {
                    const active = path.id === activeId;
                    return (
                      <label
                        key={path.id}
                        className={cn(
                          'flex cursor-pointer items-start gap-3 rounded-md border px-4 py-3 mkt-motion-color-standard focus-within:ring-2 focus-within:ring-border-focus',
                          active
                            ? 'border-accent bg-surface-raised'
                            : 'border-border-default hover:border-accent/50',
                        )}
                      >
                        <input
                          type="radio"
                          name="developer-path"
                          value={path.id}
                          checked={active}
                          onChange={() => setActiveId(path.id)}
                          className="peer sr-only"
                        />
                        <span
                          aria-hidden="true"
                          className={cn(
                            'mt-0.5 h-4 w-4 shrink-0 rounded-full border border-border-default bg-surface-base mkt-motion-color-standard peer-checked:border-accent peer-checked:bg-accent',
                          )}
                        />
                        <span className="text-sm font-medium text-text-primary">{path.label}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            </div>

            {/* Active path panel */}
            <div className="lg:col-span-7">
              <div className="h-full rounded-md border border-border-default bg-surface-raised p-6 md:p-8">
                <Eyebrow>{activePath.eyebrow}</Eyebrow>
                <h2 className="mkt-h2 mt-3">{activePath.label}</h2>
                <p className="mkt-lead mt-4">{activePath.description}</p>
                <ol className="mt-8 space-y-6">
                  {activePath.steps.map((step, index) => (
                    <li key={step.heading} className="border-l-2 border-border-default pl-4">
                      <p className="font-mono text-xs text-text-muted">Step {index + 1}</p>
                      <h3 className="mkt-body mt-1 font-medium text-text-primary">{step.heading}</h3>
                      <p className="mt-1 text-sm leading-relaxed text-text-secondary">{step.text}</p>
                    </li>
                  ))}
                </ol>
                <div className="mt-8 rounded-md border border-border-default bg-surface-base p-4">
                  <p className="mkt-eyebrow">Current state</p>
                  <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                    {activePath.state}
                  </p>
                </div>
                <div className="mt-6">
                  <Button asChild variant="secondary" size="md">
                    <a href={AETHER_DOCS_URL} target="_blank" rel="noreferrer">
                      Read the documentation
                    </a>
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* /developers editorial copy — kept identical to section-page.tsx */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          {section.paragraphs !== undefined && (
            <div className="mkt-measure space-y-5">
              {section.paragraphs.map((p) => (
                <p key={p} className="mkt-body text-text-secondary">
                  {p}
                </p>
              ))}
            </div>
          )}
          {section.bullets !== undefined && (
            <ul className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {section.bullets.map((b) => (
                <li key={b.heading} className="rounded-md border border-border-default p-6">
                  <h2 className="mkt-body font-medium text-text-primary">{b.heading}</h2>
                  <p className="mt-2 text-sm leading-relaxed text-text-secondary">{b.text}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* Closing call-to-action — mirrors the /developers SECTIONS entry. The
          primary points at the canonical docs; the secondary opens the public
          /signup threshold. */}
      <CtaBand
        title="Go deeper in the documentation"
        body="Aether’s documentation site carries the technical depth behind the platform — the event model, identity resolution, consent, connectors, and validation."
        primary={{
          label: cta?.label ?? 'Read the technical documentation',
          to: cta?.to ?? AETHER_DOCS_URL,
          external: true,
        }}
        secondary={{ label: 'Start building', to: '/signup' }}
      />
    </>
  );
}
