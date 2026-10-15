/**
 * Built from design/designs/Aether Customer Intelligence.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { asset, css, portalLabel, useLink } from '@site/design/runtime';
import { markSrc } from '@site/components/brand-mark';
import { usePageMeta } from '@site/design/page-meta';
import { AetherScene } from '@site/components/aether-scene';
import { Profile360 } from '@site/components/profile-360';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-customer-intelligence-page.css';

const STEPS: [t: string, l: string, src: string][] = [['09:01', 'Sees an ad', 'google ads'], ['09:04', 'Visits anonymously', 'web sdk'], ['09:09', 'Creates an account', 'web sdk'], ['09:15', 'Uses the mobile app', 'ios sdk'], ['11:43', 'Receives an email', 'klaviyo'], ['14:22', 'Speaks with an AI agent', 'agent'], ['16:08', 'Buys a product', 'stripe'], ['17:30', 'Contacts support', 'zendesk']];
const HOW = ['Open Profiles', 'Search for the customer', 'Open Profile 360', 'Review identity evidence', 'Open Timeline', 'Open Journeys', 'Select acquisition journey', 'Inspect touchpoints', 'Open Value', 'Review attribution', 'Apply campaign lens'];
const SEES: [g: string, l: string, c: string][] = [['⬡', 'who this is', '#3a6896'], ['◉', 'what happened', '#4f7a5e'], ['↔', 'how everything relates', '#3a6896'], ['→', 'what led to the outcome', '#4f7a5e'], ['⬡', 'what my agents did', '#a8783e'], ['↑', 'what value resulted', '#4f7a5e'], ['▲', 'what I should investigate', '#a3473c']];

// Logo beside each step's source system.
const SRC_LOGO: Record<string, string> = { 'google ads': 'assets/brand/googleads.svg', 'web sdk': 'AE', 'ios sdk': 'assets/brand/apple.svg', klaviyo: 'assets/brand/klaviyo.svg', agent: 'AE', stripe: 'assets/brand/stripe.svg', zendesk: 'assets/brand/zendesk.svg' };

export function AetherCustomerIntelligencePage() {
  const link = useLink();
  usePageMeta('aether-customer-intelligence');
  const steps = STEPS.map(([t, l, src]) => ({ t, l, src, logo: (SRC_LOGO[src] ?? 'AE') === 'AE' ? markSrc('aether') : asset(SRC_LOGO[src]!) }));
  const how = HOW.map((l, i) => ({ l, n: String(i + 1).padStart(2, '0') }));
  const sees = SEES.map(([g, l, c]) => ({ g, l, gStyle: 'font-family: var(--font-mono); color: ' + c + ';' }));
  return (
    <div className="dc pg-aether-customer-intelligence">
    <div data-page="aether-customer-intelligence" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="Applications" />
      <main id="main" tabIndex={-1}>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 9vw, 120px) 24px clamp(40px, 6vw, 72px); display: flex; flex-direction: column; gap: 22px;")}>
            <span style={css("display: flex; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              <a href={link("Aether Applications.dc.html")} style={css("color: #6b6a65; text-decoration: none;")}>
                {"Applications"}
              </a>
              <span>
                {"/"}
              </span>
              <span style={css("color: #3a6896;")}>
                {"Customer intelligence"}
              </span>
            </span>
            <h1 style={css("font-size: clamp(44px, 6.4vw, 84px); font-weight: 500; line-height: 0.96; letter-spacing: -0.045em; margin: 0; max-width: 980px; text-wrap: balance;")}>
              {"See every customer’s full story."}
            </h1>
            <p style={css("font-size: 17px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 600px;")}>
              {"An ad, a website visit, a sign-up, the app, a chat with an AI agent, an email, a purchase, a support ticket. Aether sees one person’s journey — not eight unrelated records."}
            </p>
          </div>
        </section>
        <section id="problem" style={css("border-bottom: 1px solid #d8d6d0; background: linear-gradient(155deg, #f1ebdd 0%, #e6e0ea 55%, #d6d2ec 100%);")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(48px, 7vw, 88px) 24px; display: flex; flex-wrap: wrap; gap: 12px;")}>
            <div style={css("flex: 1 1 420px; display: flex; flex-direction: column; gap: 18px; padding: 28px; border-radius: 26px; box-sizing: border-box; background: rgba(255,255,255,0.5); border: 1px solid rgba(255,255,255,0.85); -webkit-backdrop-filter: blur(18px) saturate(1.5); backdrop-filter: blur(18px) saturate(1.5); box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(40,34,70,0.08);")}>
              <span style={css("font-family: var(--font-mono); font-size: 12px; color: #a3473c;")}>
                {"■ before"}
              </span>
              <div style={css("display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 8px; text-align: center;")}>
                <span style={css("display: flex; flex-direction: column; align-items: center; gap: 6px; font-size: 12px; font-weight: 500;")}>
                  <span style={css("width: 32px; height: 32px; border-radius: 10px; background: #fff; border: 1px solid #e2e0da; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;")}>
                    <img src={asset("assets/brand/hubspot.svg")} alt="" style={css("width: 18px; height: 18px; object-fit: contain;")} />
                  </span>
                  {"CRM"}
                </span>
                <span style={css("display: flex; flex-direction: column; align-items: center; gap: 6px; font-size: 12px; font-weight: 500;")}>
                  <span style={css("width: 32px; height: 32px; border-radius: 10px; background: #fff; border: 1px solid #e2e0da; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;")}>
                    <img src={asset("assets/brand/googleanalytics.svg")} alt="" style={css("width: 18px; height: 18px; object-fit: contain;")} />
                  </span>
                  {"Analytics"}
                </span>
                <span style={css("display: flex; flex-direction: column; align-items: center; gap: 6px; font-size: 12px; font-weight: 500;")}>
                  <span style={css("width: 32px; height: 32px; border-radius: 10px; background: #fff; border: 1px solid #e2e0da; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;")}>
                    <img src={asset("assets/brand/stripe.svg")} alt="" style={css("width: 18px; height: 18px; object-fit: contain;")} />
                  </span>
                  {"Stripe"}
                </span>
                <span style={css("display: flex; flex-direction: column; align-items: center; gap: 6px; font-size: 12px; font-weight: 500;")}>
                  <span style={css("width: 32px; height: 32px; border-radius: 10px; background: #fff; border: 1px solid #e2e0da; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;")}>
                    <img src={markSrc("aether")} alt="" style={css("width: 18px; height: 18px; object-fit: contain;")} />
                  </span>
                  {"Agents"}
                </span>
                <span style={css("font-family: var(--font-mono); color: #9c9b95;")}>
                  {"↓"}
                </span>
                <span style={css("font-family: var(--font-mono); color: #9c9b95;")}>
                  {"↓"}
                </span>
                <span style={css("font-family: var(--font-mono); color: #9c9b95;")}>
                  {"↓"}
                </span>
                <span style={css("font-family: var(--font-mono); color: #9c9b95;")}>
                  {"↓"}
                </span>
                <span style={css("font-family: var(--font-mono); font-size: 11px; padding: 8px 2px; border: 1px dashed rgba(26,26,30,0.3); border-radius: 12px; background: rgba(255,255,255,0.4);")}>
                  {"customer A"}
                </span>
                <span style={css("font-family: var(--font-mono); font-size: 11px; padding: 8px 2px; border: 1px dashed rgba(26,26,30,0.3); border-radius: 12px; background: rgba(255,255,255,0.4);")}>
                  {"user 884"}
                </span>
                <span style={css("font-family: var(--font-mono); font-size: 11px; padding: 8px 2px; border: 1px dashed rgba(26,26,30,0.3); border-radius: 12px; background: rgba(255,255,255,0.4);")}>
                  {"cus_12"}
                </span>
                <span style={css("font-family: var(--font-mono); font-size: 11px; padding: 8px 2px; border: 1px dashed rgba(26,26,30,0.3); border-radius: 12px; background: rgba(255,255,255,0.4);")}>
                  {"task 91"}
                </span>
              </div>
              <span style={css("font-size: 20px; font-weight: 500; letter-spacing: -0.3px; margin-top: auto;")}>
                {"Five systems. Five identities. Unknown relationships."}
              </span>
            </div>
            <div style={css("flex: 1 1 420px; display: flex; flex-direction: column; gap: 18px; padding: 28px; border-radius: 26px; border: 1px solid rgba(255,255,255,0.1); background: radial-gradient(60% 50% at 85% 18%, rgba(58,104,150,0.42), transparent 70%), radial-gradient(50% 45% at 8% 92%, rgba(107,154,124,0.24), transparent 70%), radial-gradient(45% 40% at 92% 92%, rgba(201,151,90,0.24), transparent 70%), #111114; color: #e8e6e1; box-sizing: border-box;")}>
              <span style={css("font-family: var(--font-mono); font-size: 12px; color: #9cc4a9;")}>
                {"● with Aether"}
              </span>
              <div style={css("display: flex; flex-direction: column; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: 12px;")}>
                <span style={css("padding: 8px 14px; border-radius: 14px; background: rgba(255,255,255,0.92); color: #1a1a1e; box-shadow: 0 8px 24px rgba(0,0,0,0.35); font-family: var(--font-sans); font-size: 14px; font-weight: 500;")}>
                  {"Sofia Marchetti"}
                </span>
                <span style={css("color: #6b6a65;")}>
                  {"↙ ↓ ↘"}
                </span>
                <span style={css("display: flex; gap: 8px; color: #a09f99;")}>
                  <span style={css("display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px 5px 6px; border-radius: 12px; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);")}>
                    <span style={css("width: 20px; height: 20px; border-radius: 6px; background: #fff; display: inline-flex; align-items: center; justify-content: center;")}>
                      <img src={asset("assets/brand/hubspot.svg")} alt="" style={css("width: 13px; height: 13px; object-fit: contain;")} />
                    </span>
                    {"CRM"}
                  </span>
                  <span style={css("display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px 5px 6px; border-radius: 12px; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);")}>
                    <span style={css("width: 20px; height: 20px; border-radius: 6px; background: #fff; display: inline-flex; align-items: center; justify-content: center;")}>
                      <img src={asset("assets/brand/stripe.svg")} alt="" style={css("width: 13px; height: 13px; object-fit: contain;")} />
                    </span>
                    {"Stripe"}
                  </span>
                  <span style={css("display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px 5px 6px; border-radius: 12px; color: #f0c995; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);")}>
                    <span style={css("width: 20px; height: 20px; border-radius: 6px; background: #fff; display: inline-flex; align-items: center; justify-content: center;")}>
                      <img src={markSrc("aether")} alt="" style={css("width: 13px; height: 13px; object-fit: contain;")} />
                    </span>
                    {"Agent"}
                  </span>
                </span>
                <span style={css("color: #6b6a65;")}>
                  {"↓"}
                </span>
                <span style={css("display: flex; gap: 6px; align-items: center; color: #e8e6e1;")}>
                  <span>
                    {"journey"}
                  </span>
                  <span style={css("color: #6b6a65;")}>
                    {"───"}
                  </span>
                  <span style={css("color: #9cc4a9;")}>
                    {"value"}
                  </span>
                  <span style={css("color: #6b6a65;")}>
                    {"───"}
                  </span>
                  <span>
                    {"outcome"}
                  </span>
                </span>
              </div>
              <span style={css("font-size: 20px; font-weight: 500; letter-spacing: -0.3px; margin-top: auto; color: #e8e6e1;")}>
                {"Five systems. One resolved Profile."}
              </span>
            </div>
          </div>
        </section>
        <section id="scenario" data-theme="dark" style={css("background: radial-gradient(60% 50% at 85% 18%, rgba(58,104,150,0.42), transparent 70%), radial-gradient(50% 45% at 8% 92%, rgba(107,154,124,0.24), transparent 70%), radial-gradient(45% 40% at 92% 92%, rgba(201,151,90,0.24), transparent 70%), #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 104px) 24px; display: flex; flex-wrap: wrap; gap: clamp(24px, 4vw, 56px); align-items: center;")}>
            <div style={css("flex: 1 1 320px; display: flex; flex-direction: column; gap: 18px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #c9975a;")}>
                {"◉ The scenario"}
              </span>
              <h2 style={css("font-size: clamp(28px, 3.4vw, 44px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0; color: #e8e6e1; text-wrap: balance;")}>
                {"Watch eight records turn into one story."}
              </h2>
              <ol style={css("list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px;")}>
                {(steps).map((s: any, sIndex: number) => (
                  <Fragment key={sIndex}>
                    <li style={css("display: grid; grid-template-columns: 52px minmax(0,1fr) auto; gap: 12px; align-items: baseline; padding: 10px 14px; border-radius: 14px; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);")}>
                      <span style={css("font-family: var(--font-mono); font-size: 11px; color: #6b6a65;")}>
                        {s.t}
                      </span>
                      <span style={css("font-size: 14px; color: #e8e6e1;")}>
                        {s.l}
                      </span>
                      <span style={css("display: inline-flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                        <span style={css("width: 22px; height: 22px; border-radius: 6px; background: #fff; display: inline-flex; align-items: center; justify-content: center;")}>
                          <img src={s.logo} alt="" style={css("width: 14px; height: 14px; object-fit: contain;")} />
                        </span>
                        {s.src}
                      </span>
                    </li>
                  </Fragment>
                ))}
              </ol>
            </div>
            <div style={css("flex: 1.4 1 480px; min-width: 0;")}>
              <AetherScene dark={true} story="customer" autoplay={true} rotate={false} controls={true} />
            </div>
          </div>
        </section>
        <section id="product" style={css("border-bottom: 1px solid #d8d6d0; background: linear-gradient(155deg, #f1ebdd 0%, #e6e0ea 55%, #d6d2ec 100%);")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 104px) 24px; display: flex; flex-wrap: wrap; gap: clamp(24px, 4vw, 56px); align-items: flex-start;")}>
            <div style={css("flex: 1.3 1 460px; min-width: 0;")}>
              <Profile360 />
            </div>
            <div style={css("flex: 1 1 320px; display: flex; flex-direction: column; gap: 16px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #3a6896;")}>
                {"In the product"}
              </span>
              <h2 style={css("font-size: clamp(28px, 3.4vw, 44px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0; text-wrap: balance;")}>
                {"Follow a customer from first click to purchase."}
              </h2>
              <ol style={css("list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 6px 16px;")}>
                {(how).map((h: any, hIndex: number) => (
                  <Fragment key={hIndex}>
                    <li style={css("display: flex; gap: 8px; font-size: 13px; line-height: 1.45; padding: 6px 0; border-bottom: 1px solid #d8d6d0;")}>
                      <span style={css("font-family: var(--font-mono); font-size: 11px; color: #9c9b95; min-width: 18px;")}>
                        {h.n}
                      </span>
                      {h.l}
                    </li>
                  </Fragment>
                ))}
              </ol>
              <a href={link("Docs.dc.html?page=profiles")} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #1a1a1e; text-decoration: none;")} className="hv-cc8e330e">
                {"Read the guide"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
            </div>
          </div>
        </section>
        <section id="outcome" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 104px) 24px; display: flex; flex-direction: column; gap: 28px;")}>
            <div style={css("display: flex; flex-direction: column; gap: 12px; max-width: 720px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #4f7a5e;")}>
                {"The outcome"}
              </span>
              <h2 style={css("font-size: clamp(28px, 3.4vw, 44px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0; text-wrap: balance;")}>
                {"Connect your tools, and you can see:"}
              </h2>
            </div>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: 10px;")}>
              {(sees).map((s: any, sIndex: number) => (
                <Fragment key={sIndex}>
                  <div style={css("display: flex; gap: 12px; align-items: baseline; padding: 18px 20px; border-radius: 20px; background: rgba(255,255,255,0.5); border: 1px solid rgba(255,255,255,0.85); -webkit-backdrop-filter: blur(18px) saturate(1.5); backdrop-filter: blur(18px) saturate(1.5); box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(40,34,70,0.08);")}>
                    <span style={css(s.gStyle)}>
                      {s.g}
                    </span>
                    <span style={css("font-size: 17px; font-weight: 500; letter-spacing: -0.2px;")}>
                      {s.l}
                    </span>
                  </div>
                </Fragment>
              ))}
            </div>
            <div style={css("display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px;")}>
              <a href={link("Aether Portal.dc.html?mode=signup")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {portalLabel("Get started")}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Contact.dc.html?brand=aether&type=pilot")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #eceae5; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-4d1362f5">
                {"Request a pilot"}
              </a>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
