import { useEffect, useMemo, useRef, useState } from 'react';
import { BrandMark } from '@aether-app/components/brand-mark';
import { InlineNotice, LinkButton, Panel } from '@aether-app/components/ae-ui';
import type { ActivationPlan, ActivationPlanIntegration } from '@aether-app/features/activation/use-activation-intents';
import { ConnectPopover } from './connect-popover';
import { CsvImportPanel } from './csv-import-panel';
import { authenticationLabel, sourceRowState, type SourceRowState } from './onboarding-model';
import { StepHeading } from './step-heading';

const IMPORT_CARD = '__import_files';

interface Card {
  readonly id: string;
  readonly name: string;
  readonly marks: readonly { readonly token: string; readonly label: string }[];
  readonly sub: string;
  readonly suggested: boolean;
  readonly anyConnected: boolean;
}

const ROW_BUTTON: Record<SourceRowState, { readonly label: string; readonly fg: string; readonly bg: string; readonly bd: string }> = {
  available: { label: 'Connect', fg: '#fff', bg: 'var(--ae-action)', bd: 'var(--ae-action)' },
  in_progress: { label: 'Continue', fg: '#fff', bg: 'var(--ae-action)', bd: 'var(--ae-action)' },
  syncing: { label: 'Syncing', fg: 'var(--ae-mute)', bg: 'var(--ae-shell)', bd: 'var(--ae-edge)' },
  connected: { label: '● Connected', fg: 'var(--ae-sage)', bg: 'var(--ae-sage-tint)', bd: 'var(--ae-sage-tint)' },
  attention: { label: 'Fix', fg: 'var(--ae-amber)', bg: 'var(--ae-amber-tint)', bd: 'var(--ae-amber)' },
  unavailable: { label: 'Not yet', fg: 'var(--ae-faint)', bg: 'transparent', bd: 'var(--ae-edge)' },
};

export interface SourcesStepProps {
  readonly plan: ActivationPlan | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly onRetry: () => void;
  readonly onBackToGoals: () => void;
}

export function SourcesStep({ plan, loading, error, onRetry, onBackToGoals }: SourcesStepProps) {
  const [active, setActive] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<ActivationPlanIntegration | null>(null);
  const carousel = useRef<HTMLDivElement>(null);

  const categories = plan && !plan.needs_selection ? plan.categories : [];
  const cards: Card[] = useMemo(() => {
    const fromPlan = categories.map(cat => ({
      id: cat.experience_category,
      name: cat.display_name,
      marks: cat.integrations.slice(0, 3).map(i => ({ token: i.family, label: i.display_name })),
      sub: `${cat.connected_count} of ${cat.integration_count} connected`,
      suggested: cat.recommended_by_intents.length > 0,
      anyConnected: cat.connected_count > 0,
    }));
    return [
      ...fromPlan,
      { id: IMPORT_CARD, name: 'Import files', marks: [{ token: 'csv', label: 'CSV' }], sub: 'CSV and files', suggested: false, anyConnected: false },
    ];
  }, [categories]);

  const activeId = active && cards.some(c => c.id === active) ? active : (cards[0]?.id ?? IMPORT_CARD);
  const activeIndex = Math.max(0, cards.findIndex(c => c.id === activeId));
  const activeCategory = categories.find(c => c.experience_category === activeId) ?? null;

  const connected = categories.reduce((n, c) => n + c.connected_count, 0);
  const total = categories.reduce((n, c) => n + c.integration_count, 0);

  // Keep the selected card centred in the carousel.
  useEffect(() => {
    const root = carousel.current;
    if (!root) return;
    const el = Array.from(root.querySelectorAll<HTMLElement>('[data-cat]')).find(node => node.dataset.cat === activeId);
    if (el && typeof root.scrollTo === 'function') {
      root.scrollTo({ left: el.offsetLeft - (root.clientWidth - el.offsetWidth) / 2, behavior: 'smooth' });
    }
  }, [activeId]);

  function step(delta: number) {
    const next = cards[(activeIndex + delta + cards.length) % cards.length];
    if (next) setActive(next.id);
  }

  return (
    <div className="ae-rise flex flex-col gap-[18px]" data-testid="onboarding-step-sources">
      <StepHeading
        step={2}
        kicker="sources"
        title="Connect your data"
        description="Every source is read-only. Approve once and it syncs on its own. You can skip this and use SDKs alone."
        summary={plan && !plan.needs_selection ? `${connected} of ${total} connected` : undefined}
      />

      {error && (
        <InlineNotice tone="ember">
          Could not load your recommended sources. <LinkButton onClick={onRetry}>Try again</LinkButton>
        </InlineNotice>
      )}
      {!error && loading && !plan && (
        <span className="text-center text-[12px]" style={{ color: 'var(--ae-mute)' }}>Loading recommended sources…</span>
      )}
      {plan?.needs_selection && (
        <InlineNotice tone="blue">
          Pick at least one goal so Aether can recommend sources. <LinkButton onClick={onBackToGoals}>Choose goals</LinkButton>
        </InlineNotice>
      )}

      <div className="relative">
        {cards.length > 1 && (
          <>
            <CarouselArrow side="left" onClick={() => step(-1)} />
            <CarouselArrow side="right" onClick={() => step(1)} />
          </>
        )}
        <div
          ref={carousel}
          role="tablist"
          aria-label="Source categories"
          className="ae-scroll-none flex snap-x snap-mandatory gap-3 overflow-x-auto px-11 pb-3 pt-2"
        >
          {cards.map(card => {
            const on = card.id === activeId;
            return (
              <button
                key={card.id}
                type="button"
                role="tab"
                aria-selected={on}
                data-cat={card.id}
                onClick={() => setActive(card.id)}
                className="ae-glass-card ae-focus flex w-[184px] flex-none snap-center flex-col gap-3.5 rounded-[20px] p-4 text-left transition-[opacity,box-shadow,border-color] duration-200"
                style={{
                  borderColor: on ? 'var(--ae-blue)' : undefined,
                  boxShadow: on ? 'inset 0 2px 0 var(--ae-blue), 0 12px 30px rgba(37,99,235,.14)' : undefined,
                  opacity: on ? 1 : 0.72,
                }}
              >
                <span className="flex items-center justify-between">
                  <span className="flex">
                    {card.marks.map(m => (
                      <BrandMark key={m.token} token={m.token} label={m.label} size={30} markSize={16} shape="round" className="-mr-[9px]" />
                    ))}
                  </span>
                  {card.suggested && <span className="text-[10px]" style={{ color: 'var(--ae-blue-ink)' }}>● suggested</span>}
                </span>
                <span className="flex flex-col leading-snug">
                  <span className="text-[14px] font-medium">{card.name}</span>
                  <span className="ae-mono text-[11px]" style={{ color: card.anyConnected ? 'var(--ae-sage)' : 'var(--ae-mute)' }}>
                    {card.sub}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {activeId === IMPORT_CARD ? (
        <CsvImportPanel />
      ) : activeCategory ? (
        <Panel className="flex flex-col" style={{ padding: '6px clamp(14px,3vw,22px)' }}>
          {activeCategory.integrations.length === 0 && (
            <p className="py-4 text-center text-[13px]" style={{ color: 'var(--ae-mute)' }}>
              No self-serve sources are available in this category yet.
            </p>
          )}
          {activeCategory.integrations.map((integration, i) => {
            const state = sourceRowState(integration);
            const button = ROW_BUTTON[state];
            const actionable = (state === 'available' || state === 'in_progress' || state === 'attention') && integration.can_act;
            return (
              <div
                key={integration.family}
                data-provider-family={integration.family}
                data-connection-state={state}
                className="flex items-center gap-3.5 py-[13px]"
                style={{ borderTop: i ? '1px solid var(--ae-edge)' : undefined }}
              >
                <BrandMark token={integration.family} label={integration.display_name} size={34} markSize={20} />
                <span className="flex min-w-0 flex-1 flex-col leading-snug">
                  <span className="text-[14px] font-medium">{integration.display_name}</span>
                  <span className="truncate text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                    {!integration.connectable
                      ? integration.connect_unavailable_reason === 'managed_by_other_flow'
                        ? 'Connects through its own flow in Settings'
                        : 'Not available to connect yet'
                      : integration.product.replace(/_/g, ' ')}
                  </span>
                </span>
                <span className="ae-mono hidden whitespace-nowrap text-[11px] sm:inline" style={{ color: 'var(--ae-mute)' }}>
                  {authenticationLabel(integration.authentication)}
                </span>
                <button
                  type="button"
                  disabled={!actionable}
                  onClick={() => setConnecting(integration)}
                  className="ae-focus min-w-[84px] whitespace-nowrap rounded border px-3.5 py-1.5 text-center text-[12px] font-medium disabled:cursor-default"
                  style={{ color: button.fg, background: button.bg, borderColor: button.bd }}
                >
                  {button.label}
                </button>
              </div>
            );
          })}
        </Panel>
      ) : null}

      {connecting && <ConnectPopover integration={connecting} onClose={() => setConnecting(null)} />}
    </div>
  );
}

function CarouselArrow({ side, onClick }: { readonly side: 'left' | 'right'; readonly onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={side === 'left' ? 'Previous category' : 'Next category'}
      onClick={onClick}
      className="ae-focus absolute top-1/2 z-[2] flex h-[34px] w-[34px] -translate-y-1/2 items-center justify-center rounded-full border text-[14px] hover:bg-[var(--ae-raised)]"
      style={{
        [side]: 0,
        background: 'var(--ae-glass)',
        backdropFilter: 'blur(20px) saturate(1.4)',
        borderColor: 'var(--ae-edge)',
        boxShadow: '0 6px 18px rgba(26,26,30,.12)',
      }}
    >
      {side === 'left' ? '‹' : '›'}
    </button>
  );
}
