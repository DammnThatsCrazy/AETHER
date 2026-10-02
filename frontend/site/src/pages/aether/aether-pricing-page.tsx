import { useState, type CSSProperties } from 'react';
import { PageShell } from '@site/components/page-shell';
import { ACCENTS, tint } from '@site/site/palette';
import {
  CONTRACT_PLANS,
  SELF_SERVE_PLANS,
  SUGGESTED_PLAN,
  formatPrice,
  formatQuota,
  pricesPublished,
  type Interval,
  type SelfServePlan,
} from '@site/site/plans';
import { useSite } from '@site/site/site-context';
import { pilotOnly, planChoicePath } from '@site/site/access';

/**
 * Aether Pricing.dc.html. Choosing a plan continues to /app/signup, where
 * sign-up, plan and payment share one card (handoff README, "/app"); a
 * pilot-only build sends the choice to a pilot request instead.
 */

const CONTRACT_COPY: Record<string, { body: string; type: string; cta: string }> = {
  epsilon: { body: 'Higher volume, more teams, stronger support.', type: 'product', cta: 'Talk through scope' },
  omicron: { body: 'Dedicated or governed deployment, procurement review, assurance artifacts.', type: 'security', cta: 'Request a review' },
  omega: { body: 'Private or regulated environments with negotiated isolation, residency, and control.', type: 'security', cta: 'Request a review' },
};

const SCOPE = [
  'Platform and tenant scope',
  'Evidence volume and retention',
  'Intelligence and workflow surfaces',
  'Governance, audit, and support',
  'Deployment complexity',
  'Capabilities enabled for the tenant',
];

function priceParts(plan: SelfServePlan, interval: Interval, published: boolean) {
  if (!published) return { price: 'On request', per: '', note: 'Pricing shared during onboarding' };
  const amount = interval === 'annual' ? plan.annual : plan.monthly;
  if (plan.monthly === 0) return { price: '$0', per: '', note: 'No charge · card not required' };
  return {
    price: formatPrice(amount),
    per: interval === 'annual' ? '/ year' : '/ month',
    note: interval === 'annual' ? 'Billed yearly' : 'Billed monthly',
  };
}

export function AetherPricingPage() {
  const { href } = useSite();
  const [interval, setInterval] = useState<Interval>('monthly');
  const published = pricesPublished();

  const rows: Array<[label: string, hint: string, cell: (p: SelfServePlan) => string]> = [
    ['Included events', 'per month', (p) => formatQuota(p.monthlyQuota)],
    ['Members', 'workspace seats', (p) => String(p.memberCap)],
    ['Burst rate', 'requests / min', (p) => p.burstRpm.toLocaleString('en-US')],
    ['Services enabled', 'service catalog', (p) => String(p.serviceCount)],
    ...(published ? [['Event overage', 'per 1k events', (p: SelfServePlan) => `$${p.eventOveragePer1k}`] as [string, string, (p: SelfServePlan) => string]] : []),
    ['Connector fees', '', () => 'none'],
  ];

  const pilot = pilotOnly();
  const choose = (plan: SelfServePlan) => href('aether', planChoicePath(plan.id, interval));

  const chooseButton = (plan: SelfServePlan) => {
    const c = ACCENTS[plan.accent];
    const primary = plan.id === SUGGESTED_PLAN;
    return (
      <a
        href={choose(plan)}
        className="mt-auto inline-flex min-h-10 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-control border px-3.5 text-body-sm font-medium no-underline transition-colors duration-120 hover:[border-color:var(--hover-border)]"
        style={
          {
            background: primary ? c.ink : tint(plan.accent, 0.12),
            color: primary ? '#f5f4f1' : c.ink,
            borderColor: primary ? c.ink : `${c.base}66`,
            '--hover-border': c.base,
          } as CSSProperties
        }
      >
        Choose {plan.name}
      </a>
    );
  };

  return (
    <PageShell title="Pricing and packages — Aether" active="Pricing">
      <section className="border-b border-line">
        <div className="mx-auto flex max-w-page flex-col gap-[18px] px-6 pb-8 pt-[clamp(40px,6vw,72px)]">
          <span className="text-label uppercase text-slate">Pricing and packages</span>
          <h1 className="m-0 max-w-[820px] text-balance text-[clamp(34px,5vw,56px)] font-medium leading-[1.04] tracking-[-0.03em]">
            Package the infrastructure around the relationship question
          </h1>
          <p className="m-0 max-w-[620px] text-[16px] leading-[1.6] text-slate">
            Scope reflects what it takes to connect evidence, form perspectives, govern decisions, and observe outcomes. It is not a
            connector fee or an SDK tax. Start with the smallest useful package.
          </p>
          <div className="mt-2.5 flex flex-wrap items-center justify-between gap-4">
            {published ? (
              <div role="radiogroup" aria-label="Billing interval" className="inline-flex rounded border border-line bg-stone-100 p-0.5">
                {(['monthly', 'annual'] as Interval[]).map((i) => (
                  <button
                    key={i}
                    type="button"
                    role="radio"
                    aria-checked={interval === i}
                    onClick={() => setInterval(i)}
                    className={`cursor-pointer rounded-[3px] border-0 px-3 py-1.5 text-body-sm font-medium ${interval === i ? 'bg-stone-50 text-ink shadow-[0_0_0_1px_#d8d6d0]' : 'bg-transparent text-slate'}`}
                  >
                    {i === 'monthly' ? 'Monthly' : 'Annual'}
                  </button>
                ))}
              </div>
            ) : (
              <span />
            )}
            <a href={href('aether', '/contact?type=pilot')} className="text-body-sm font-medium text-cobalt no-underline hover:text-cobalt-ink">
              Not sure where to start? Talk through a pilot →
            </a>
          </div>
        </div>
      </section>

      <section className="border-b border-line">
        <div className="mx-auto max-w-page px-6 pb-[clamp(48px,6vw,72px)] pt-8">
          {/* Wide: comparison table */}
          <div className="hidden overflow-hidden rounded border border-line min-[1100px]:block">
            <div className="grid bg-stone-100 [grid-template-columns:200px_repeat(4,minmax(0,1fr))]">
              <div className="flex flex-col justify-end border-r border-line p-5">
                <span className="text-label uppercase text-slate">{pilot ? 'Packages' : 'Self-service'}</span>
                <span className="mt-1.5 text-body-sm text-slate">{pilot ? 'Start with a pilot on any package.' : 'Pay online and start today.'}</span>
              </div>
              {SELF_SERVE_PLANS.map((p) => {
                const c = ACCENTS[p.accent];
                const { price, per, note } = priceParts(p, interval, published);
                return (
                  <div
                    key={p.id}
                    className="box-border flex h-full flex-col gap-2 border-r border-line p-5 last:border-r-0"
                    style={{ background: tint(p.accent, 0.12), boxShadow: `inset 0 ${p.id === SUGGESTED_PLAN ? 4 : 3}px 0 ${c.base}` }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[18px] font-medium tracking-[-0.3px]">{p.name}</span>
                      {p.id === SUGGESTED_PLAN && <span className="whitespace-nowrap text-label uppercase text-cobalt-ink">Common start</span>}
                    </div>
                    <span className="min-h-10 text-body-sm text-slate">{p.fit}</span>
                    <div className="flex items-baseline gap-1">
                      <span className="text-[28px] font-medium tracking-[-0.6px]">{price}</span>
                      <span className="text-body-sm text-slate">{per}</span>
                    </div>
                    <span className="min-h-4 text-caption text-slate">{note}</span>
                    {chooseButton(p)}
                  </div>
                );
              })}
            </div>
            <table className="w-full border-collapse text-body-sm">
              <caption className="sr-only">Plan limits</caption>
              <tbody>
                {rows.map(([label, hint, cell]) => (
                  <tr key={label} className="grid border-t border-line [grid-template-columns:200px_repeat(4,minmax(0,1fr))]">
                    <th scope="row" className="flex flex-col gap-0.5 border-r border-line px-5 py-[11px] text-left font-normal text-slate">
                      <span className="text-ink">{label}</span>
                      {hint && <span className="text-caption">{hint}</span>}
                    </th>
                    {SELF_SERVE_PLANS.map((p) => (
                      <td key={p.id} className="flex items-center border-r border-stone-200 px-5 py-[11px] font-mono last:border-r-0">
                        {cell(p)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Narrow: one card per plan */}
          <div className="flex flex-col gap-2 min-[1100px]:hidden">
            {SELF_SERVE_PLANS.map((p) => {
              const { price, per } = priceParts(p, interval, published);
              return (
                <div key={p.id} className="flex flex-col gap-2.5 rounded border border-line bg-stone-100 p-[18px]">
                  <div className="flex items-baseline justify-between">
                    <span className="text-[18px] font-medium">{p.name}</span>
                    <span className="text-[22px] font-medium">
                      {price}
                      <span className="text-body-sm font-normal text-slate"> {per}</span>
                    </span>
                  </div>
                  <span className="text-body-sm text-slate">{p.fit}</span>
                  <dl className="m-0 grid gap-x-3 gap-y-1.5 border-y border-line py-2.5 text-body-sm [grid-template-columns:1fr_auto]">
                    {rows.slice(0, 4).map(([label, , cell]) => (
                      <div key={label} className="contents">
                        <dt className="text-slate">{label === 'Included events' ? 'Events / month' : label === 'Burst rate' ? 'Burst' : label === 'Services enabled' ? 'Services' : label}</dt>
                        <dd className="m-0 font-mono">{label === 'Burst rate' ? `${cell(p)} rpm` : cell(p)}</dd>
                      </div>
                    ))}
                  </dl>
                  {chooseButton(p)}
                </div>
              );
            })}
          </div>

          <div className="mt-6 flex flex-col gap-2.5">
            <span className="text-label uppercase text-slate">Contract scope · no online checkout</span>
            <div className="grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr))]">
              {CONTRACT_PLANS.map((p) => {
                const copy = CONTRACT_COPY[p.id]!;
                return (
                  <div key={p.id} className="flex flex-col gap-2 rounded border border-line p-[18px]">
                    <span className="text-[16px] font-medium">{p.name}</span>
                    <span className="text-body-sm leading-[1.5] text-slate">
                      {copy.body}
                      {p.monthly_quota > 0 && <span className="font-mono text-caption"> {formatQuota(p.monthly_quota)} events / mo</span>}
                    </span>
                    <a
                      href={href('aether', `/contact?type=${copy.type}&plan=${p.id}`)}
                      className="mt-auto text-body-sm font-medium text-cobalt no-underline hover:text-cobalt-ink"
                    >
                      {copy.cta} →
                    </a>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      <section className="border-b border-line bg-stone-100">
        <div className="mx-auto grid max-w-page gap-10 px-6 py-[clamp(48px,6vw,72px)] [grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr))]">
          <div className="flex flex-col gap-3">
            <h2 className="m-0 text-[clamp(22px,2.6vw,28px)] font-medium tracking-[-0.5px]">What package scope reflects</h2>
            <p className="m-0 max-w-[440px] text-[14px] leading-[1.6] text-slate">
              A connection is valuable when it answers a relationship question or makes an outcome observable. No package charges per
              connector.
            </p>
          </div>
          <ul className="m-0 grid list-none border-t border-line p-0 [grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr))]">
            {SCOPE.map((x) => (
              <li key={x} className="border-b border-line py-3 pr-3 text-body-sm">
                {x}
              </li>
            ))}
          </ul>
        </div>
      </section>
    </PageShell>
  );
}
