/**
 * Built from design/designs/Aether Pricing.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { asset, css, useDesignState, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-pricing-page.css';

import { useSite } from '@site/site/site-context';
import { planChoicePath } from '@site/site/access';
import { SELF_SERVE_PLANS, SUGGESTED_PLAN, formatPrice, formatQuota, pricesPublished, type Interval } from '@site/site/plans';

// Plan tint: [dot / ring, ink, wash].
const TC: Record<string, [string, string, string]> = { alpha: ['#6b9a7c', '#4f7a5e', 'rgba(107,154,124,0.12)'], beta: ['#3a6896', '#2d5373', 'rgba(58,104,150,0.10)'], gamma: ['#c9975a', '#8a6433', 'rgba(201,151,90,0.12)'], delta: ['#a88a5a', '#7d6538', 'rgba(168,138,90,0.14)'] };
const btn = (primary: boolean, id?: string) => { const t = id ? TC[id] : undefined; return 'font-family: inherit; white-space: nowrap; font-size: 14px; font-weight: 500; min-height: 44px; padding: 0 14px; border-radius: 10px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; flex-shrink: 0; text-decoration: none; box-sizing: border-box; ' + (t ? (primary ? 'background: ' + t[1] + '; color: #f5f4f1; border: 1px solid ' + t[1] + ';' : 'background: ' + t[2] + '; color: ' + t[1] + '; border: 1px solid ' + t[0] + '66;') : (primary ? 'background: #1a1a1e; color: #f5f4f1; border: 1px solid #1a1a1e;' : 'background: #eceae5; color: #1a1a1e; border: 1px solid #d8d6d0;')); };
const seg = (on: boolean) => 'font-family: inherit; font-size: 13px; font-weight: 500; padding: 7px 16px; border-radius: 999px; border: 0; cursor: pointer; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1); ' + (on ? 'background: #fbfaf8; color: #1a1a1e; box-shadow: 0 0 0 1px #d8d6d0;' : 'background: transparent; color: #6b6a65;');
const STAGES = [['01', 'start', 'Explore', 'Connect your first tool and see your first customer. No card needed.', 'alpha', '#4f7a5e'], ['02', 'connect', 'Build', 'For teams connecting more tools and more of their customers.', 'beta', '#2d5373'], ['03', 'understand', 'Operate', 'For teams using Aether every day, at higher volume.', 'gamma · delta', '#8a6433'], ['04', 'operate', 'Enterprise', 'For larger companies that need custom limits and a security review.', 'epsilon · omicron', '#7d6538'], ['05', 'scale', 'Sovereign', 'For organizations that need Aether run in their own environment.', 'omega', '#a3473c']].map(([n, k, name, who, plans]) => ({ n, k, name, who, plans }));

export function AetherPricingPage() {
  const link = useLink();
  usePageMeta('aether-pricing');
  const { href } = useSite();
  const [state, setState] = useDesignState<{ interval: Interval }>({ interval: 'monthly' });
  const annual = state.interval === 'annual';
  // Prices show only in builds that publish them (VITE_PUBLISH_PRICES); the rest say "On request".
  const published = pricesPublished();
  const plans = SELF_SERVE_PLANS.map((p) => ({
    id: p.id,
    name: p.name,
    fit: p.fit,
    suggested: p.id === SUGGESTED_PLAN,
    price: !published ? 'On request' : formatPrice(annual ? p.annual : p.monthly),
    per: !published || p.monthly === 0 ? '' : annual ? '/ year' : '/ month',
    note: !published ? 'Pricing shared during onboarding' : p.monthly === 0 ? 'No charge · card not required' : annual ? 'Billed yearly' : 'Billed monthly',
    cta: 'Choose ' + p.name,
    btnStyle: btn(p.id === SUGGESTED_PLAN, p.id) + ' -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px);',
    dot: 'width: 9px; height: 9px; border-radius: 999px; flex-shrink: 0; background: ' + (TC[p.id]?.[0] ?? '#9c9b95') + '; box-shadow: 0 0 0 4px ' + (TC[p.id]?.[0] ?? '#9c9b95') + '33;',
    href: href('aether', planChoicePath(p.id, state.interval)),
    specs: [
      { k: 'Events / month', v: formatQuota(p.monthlyQuota) },
      { k: 'Members', v: String(p.memberCap) },
      { k: 'Burst rate', v: p.burstRpm.toLocaleString('en-US') + ' / min' },
      { k: 'Services', v: String(p.serviceCount) },
      ...(published ? [{ k: 'Overage / 1k events', v: '$' + p.eventOveragePer1k }] : []),
      { k: 'Integration fees', v: 'none' },
    ],
    cardStyle: 'display: flex; flex-direction: column; gap: 14px; padding: 24px; border-radius: 24px; box-sizing: border-box; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1); ' + (p.id === SUGGESTED_PLAN ? 'background: rgba(255,255,255,0.72); border: 1px solid #fff; -webkit-backdrop-filter: blur(18px) saturate(1.5); backdrop-filter: blur(18px) saturate(1.5); box-shadow: 0 0 0 2px rgba(58,104,150,0.4), 0 16px 40px rgba(40,34,70,0.14);' : 'background: rgba(255,255,255,0.5); border: 1px solid rgba(255,255,255,0.85); -webkit-backdrop-filter: blur(18px) saturate(1.5); backdrop-filter: blur(18px) saturate(1.5); box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(40,34,70,0.08);'),
  }));
  const stages = STAGES;
  const monthlyChecked = annual ? 'false' : 'true';
  const annualChecked = annual ? 'true' : 'false';
  const monthlyStyle = seg(!annual);
  const annualStyle = seg(annual);
  const setMonthly = () => setState({ interval: 'monthly' });
  const setAnnual = () => setState({ interval: 'annual' });
  return (
    <div className="dc pg-aether-pricing">
    <div data-page="aether-pricing" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="Pricing" />
          <main id="main" tabIndex={-1}>
            <section>
              <div style={css("max-width: 1000px; margin: 0 auto; padding: clamp(80px, 12vw, 152px) 24px 40px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 22px;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                  {"Pricing"}
                </span>
                <h1 style={css("font-size: clamp(44px, 6.8vw, 92px); font-weight: 500; line-height: 0.95; letter-spacing: -0.048em; margin: 0; text-wrap: balance;")}>
                  {"Choose how you want to start."}
                </h1>
                <p style={css("font-size: 17px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 520px;")}>
                  {"Start free and grow when you need to. No plan charges per integration."}
                </p>
                <div style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 6px 22px; margin-top: 4px;")}>
                  {(stages).map((st: any, stIndex: number) => (
                    <Fragment key={stIndex}>
                      <span style={css("display: inline-flex; gap: 8px; align-items: baseline; font-size: 13px; color: #6b6a65;")} title={st.who}>
                        <span style={css("font-family: var(--font-mono); font-size: 11px; color: #9c9b95;")}>
                          {st.n}
                        </span>
                        <span style={css("color: #1a1a1e; font-weight: 500;")}>
                          {st.name}
                        </span>
                        {st.plans}
                      </span>
                    </Fragment>
                  ))}
                </div>
                {published ? (
                <div role="radiogroup" aria-label="Billing interval" style={css("display: inline-flex; border-radius: 999px; padding: 3px; margin-top: 10px; background: rgba(255,255,255,0.5); border: 1px solid rgba(255,255,255,0.85); -webkit-backdrop-filter: blur(18px) saturate(1.5); backdrop-filter: blur(18px) saturate(1.5); box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(40,34,70,0.08);")}>
                  <button type="button" role="radio" aria-checked={monthlyChecked} onClick={setMonthly} style={css(monthlyStyle)}>
                    {"Monthly"}
                  </button>
                  <button type="button" role="radio" aria-checked={annualChecked} onClick={setAnnual} style={css(annualStyle)}>
                    {"Annual"}
                  </button>
                </div>
                ) : null}
              </div>
            </section>
            <section style={css("border-bottom: 1px solid #d8d6d0; background: radial-gradient(34% 46% at 12% 22%, rgba(107,154,124,0.42), transparent 72%), radial-gradient(34% 46% at 38% 28%, rgba(58,104,150,0.38), transparent 72%), radial-gradient(34% 46% at 64% 72%, rgba(201,151,90,0.4), transparent 72%), radial-gradient(34% 46% at 90% 80%, rgba(168,138,90,0.38), transparent 72%), linear-gradient(155deg, #f1ebdd 0%, #e6e0ea 55%, #d6d2ec 100%);")}>
              <div style={css("max-width: 1200px; margin: 0 auto; padding: 24px 24px clamp(64px, 8vw, 96px);")}>
                <div className="pr-plans" style={css("display: grid; gap: 12px; align-items: stretch;")}>
                  {(plans).map((p: any, pIndex: number) => (
                    <Fragment key={pIndex}>
                      <div style={css(p.cardStyle)} className="hv-pr-card">
                        <div style={css("display: flex; justify-content: space-between; align-items: center; gap: 8px;")}>
                          <span style={css("display: flex; align-items: center; gap: 10px; font-size: 20px; font-weight: 500; letter-spacing: -0.3px;")}>
                            <span style={css(p.dot)} />
                            {p.name}
                          </span>
                          {(p.suggested) ? (
                            <>
                              <span style={css("font-size: 11px; font-weight: 500; padding: 3px 9px; border-radius: 999px; background: #2d5373; color: #f5f4f1;")}>
                                {"Most teams start here"}
                              </span>
                            </>
                          ) : null}
                        </div>
                        <span style={css("font-size: 14px; line-height: 1.5; color: #6b6a65; min-height: 42px;")}>
                          {p.fit}
                        </span>
                        <div style={css("display: flex; align-items: baseline; gap: 4px;")}>
                          <span style={css("font-size: 40px; font-weight: 500; letter-spacing: -0.04em;")}>
                            {p.price}
                          </span>
                          <span style={css("font-size: 13px; color: #6b6a65;")}>
                            {p.per}
                          </span>
                        </div>
                        <span style={css("font-size: 12px; color: #6b6a65; margin-top: -8px;")}>
                          {p.note}
                        </span>
                        <a href={p.href} style={css(p.btnStyle)}>
                          {p.cta}
                        </a>
                        <div style={css("display: flex; flex-direction: column; border-top: 1px solid #e2e0da; margin-top: 4px;")}>
                          {(p.specs).map((s: any, sIndex: number) => (
                            <Fragment key={sIndex}>
                              <span style={css("display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid #ecebe6; font-size: 13px;")}>
                                <span style={css("color: #6b6a65;")}>
                                  {s.k}
                                </span>
                                <span style={css("font-family: var(--font-mono); color: #1a1a1e;")}>
                                  {s.v}
                                </span>
                              </span>
                            </Fragment>
                          ))}
                        </div>
                      </div>
                    </Fragment>
                  ))}
                </div>
                <div style={css("margin-top: 24px; display: flex; flex-direction: column; gap: 10px;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                    {"Contract scope · no online checkout"}
                  </span>
                  <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: 8px;")}>
                    <div style={css("border-radius: 20px; padding: 18px; display: flex; flex-direction: column; gap: 8px; background: rgba(255,255,255,0.5); border: 1px solid rgba(255,255,255,0.85); -webkit-backdrop-filter: blur(18px) saturate(1.5); backdrop-filter: blur(18px) saturate(1.5); box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(40,34,70,0.08);")}>
                      <span style={css("font-size: 16px; font-weight: 500;")}>
                        {"Epsilon"}
                      </span>
                      <span style={css("font-size: 13px; line-height: 1.5; color: #6b6a65;")}>
                        {"Higher volume, more teams, stronger support. "}
                        <span style={css("font-family: var(--font-mono); font-size: 12px;")}>
                          {"54M events / mo"}
                        </span>
                      </span>
                      <a href={link("Contact.dc.html?brand=aether&type=product&plan=epsilon")} style={css("font-size: 13px; font-weight: 500; text-decoration: none; margin-top: auto;")}>
                        {"Talk through scope →"}
                      </a>
                    </div>
                    <div style={css("border-radius: 20px; padding: 18px; display: flex; flex-direction: column; gap: 8px; background: rgba(255,255,255,0.5); border: 1px solid rgba(255,255,255,0.85); -webkit-backdrop-filter: blur(18px) saturate(1.5); backdrop-filter: blur(18px) saturate(1.5); box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(40,34,70,0.08);")}>
                      <span style={css("font-size: 16px; font-weight: 500;")}>
                        {"Omicron"}
                      </span>
                      <span style={css("font-size: 13px; line-height: 1.5; color: #6b6a65;")}>
                        {"Dedicated or governed deployment, procurement review, assurance artifacts."}
                      </span>
                      <a href={link("Contact.dc.html?brand=aether&type=security&plan=omicron")} style={css("font-size: 13px; font-weight: 500; text-decoration: none; margin-top: auto;")}>
                        {"Request a review →"}
                      </a>
                    </div>
                    <div style={css("border-radius: 20px; padding: 18px; display: flex; flex-direction: column; gap: 8px; background: rgba(255,255,255,0.5); border: 1px solid rgba(255,255,255,0.85); -webkit-backdrop-filter: blur(18px) saturate(1.5); backdrop-filter: blur(18px) saturate(1.5); box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(40,34,70,0.08);")}>
                      <span style={css("font-size: 16px; font-weight: 500;")}>
                        {"Omega"}
                      </span>
                      <span style={css("font-size: 13px; line-height: 1.5; color: #6b6a65;")}>
                        {"Private or regulated environments with negotiated isolation, residency, and control."}
                      </span>
                      <a href={link("Contact.dc.html?brand=aether&type=security&plan=omega")} style={css("font-size: 13px; font-weight: 500; text-decoration: none; margin-top: auto;")}>
                        {"Request a review →"}
                      </a>
                    </div>
                  </div>
                </div>
              </div>
            </section>
            <section data-theme="dark" style={css("background: radial-gradient(60% 50% at 85% 18%, rgba(58,104,150,0.42), transparent 70%), radial-gradient(50% 45% at 8% 92%, rgba(107,154,124,0.24), transparent 70%), radial-gradient(45% 40% at 92% 92%, rgba(201,151,90,0.24), transparent 70%), #111114; color: #e8e6e1;")}>
              <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(48px, 6vw, 72px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 40px;")}>
                <div style={css("display: flex; flex-direction: column; gap: 12px;")}>
                  <h2 style={css("font-size: clamp(22px, 2.6vw, 28px); font-weight: 500; letter-spacing: -0.5px; margin: 0; color: #e8e6e1;")}>
                    {"What you’re paying for"}
                  </h2>
                  <p style={css("font-size: 14px; line-height: 1.6; color: #a09f99; margin: 0; max-width: 440px;")}>
                    {"You pay for how much Aether does for you — not for how many tools you connect."}
                  </p>
                </div>
                <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 8px;")}>
                  <span style={css("padding: 14px 16px; border-radius: 16px; font-size: 13px; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);")}>
                    {"Platform and tenant scope"}
                  </span>
                  <span style={css("padding: 14px 16px; border-radius: 16px; font-size: 13px; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);")}>
                    {"Evidence volume and retention"}
                  </span>
                  <span style={css("padding: 14px 16px; border-radius: 16px; font-size: 13px; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);")}>
                    {"Intelligence and workflow surfaces"}
                  </span>
                  <span style={css("padding: 14px 16px; border-radius: 16px; font-size: 13px; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);")}>
                    {"Governance, audit, and support"}
                  </span>
                  <span style={css("padding: 14px 16px; border-radius: 16px; font-size: 13px; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);")}>
                    {"Deployment complexity"}
                  </span>
                  <span style={css("padding: 14px 16px; border-radius: 16px; font-size: 13px; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);")}>
                    {"Capabilities enabled for the tenant"}
                  </span>
                </div>
              </div>
            </section>
          </main>
      <SiteFooter />
    </div>
    </div>
  );
}
