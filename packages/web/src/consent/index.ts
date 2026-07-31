// =============================================================================
// Aether SDK — CONSENT MODULE (GDPR / CCPA / CPRA)
// =============================================================================

import type { ConsentState, ConsentConfig, ConsentPurpose, ConsentBannerConfig, ConsentCallback } from '../types';
import { storage, now } from '../utils';

const CONSENT_KEY = 'consent';
const CONSENT_RECORDED_KEY = 'consent_recorded';
const FP_STORAGE_KEY = '_aether_fp';

// financial_activity, credit, location, economic_observability,
// cross_chain_observability, and fraud_prevention always require explicit
// opt-in — never granted by accept-all.
const EXPLICIT_OPT_IN_PURPOSES: readonly ConsentPurpose[] = [
  'financial_activity', 'credit', 'location', 'economic_observability', 'cross_chain_observability',
  'fraud_prevention',
];

const ALL_PURPOSES: readonly ConsentPurpose[] = [
  'analytics', 'marketing', 'personalization', 'web3', 'agent', 'commerce', 'financial_activity', 'credit', 'location',
  'economic_observability', 'cross_chain_observability', 'fraud_prevention',
];

export class ConsentModule {
  private state: ConsentState;
  private config: ConsentConfig;
  private listeners: ConsentCallback[] = [];
  private bannerElement: HTMLElement | null = null;

  constructor(config?: Partial<ConsentConfig>) {
    this.config = {
      purposes: [...ALL_PURPOSES],
      policyUrl: '/privacy',
      policyVersion: '1.0',
      ...config,
    };
    this.state = this.loadConsent();
  }

  /** Get current consent state */
  getState(): ConsentState {
    return { ...this.state };
  }

  /** Check if a specific purpose is consented */
  hasConsent(purpose: ConsentPurpose): boolean {
    return this.state[purpose] === true;
  }

  /** Check if user has explicitly accepted or rejected (banner was acted on) */
  hasRecordedConsent(): boolean {
    return !!storage.get(CONSENT_RECORDED_KEY);
  }

  /** Grant consent for specified purposes */
  grant(purposes: ConsentPurpose[]): void {
    for (const p of purposes) {
      this.state[p] = true;
    }
    this.state.updatedAt = now();
    this.state.policyVersion = this.config.policyVersion;
    this.persist();
    this.notify();
  }

  /** Revoke consent for specified purposes. Revoking personalization deletes cached fingerprint. */
  revoke(purposes: ConsentPurpose[]): void {
    const revokingPersonalization = purposes.includes('personalization') && this.state.personalization;
    for (const p of purposes) {
      this.state[p] = false;
    }
    this.state.updatedAt = now();
    this.persist();
    if (revokingPersonalization) {
      this.clearFingerprintCache();
    }
    this.notify();
  }

  /**
   * Grant all purposes that do NOT require explicit opt-in (financial_activity, credit, and location are excluded).
   * To grant credit or location, call grant(['financial_activity']), grant(['credit']), or grant(['location']) explicitly.
   */
  grantAll(): void {
    const grantable = this.config.purposes.filter(
      (p) => !EXPLICIT_OPT_IN_PURPOSES.includes(p)
    );
    this.grant(grantable);
    storage.set(CONSENT_RECORDED_KEY, true);
  }

  /** Revoke all purposes */
  revokeAll(): void {
    this.revoke([...this.config.purposes]);
    storage.set(CONSENT_RECORDED_KEY, true);
  }

  /** Register a listener for consent changes */
  onUpdate(callback: ConsentCallback): () => void {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== callback);
    };
  }

  /** Show the consent banner */
  showBanner(config?: ConsentBannerConfig): void {
    if (this.bannerElement) return;
    if (typeof document === 'undefined') return;

    const c = { ...this.config.bannerConfig, ...config };
    const position = ['top', 'bottom'].includes(c.position ?? '') ? c.position! : 'bottom';
    const theme = ['light', 'dark'].includes(c.theme ?? '') ? c.theme! : 'light';
    const accent = /^#[0-9a-fA-F]{3,8}$/.test(c.accentColor ?? '') ? c.accentColor! : '#2E75B6';

    const banner = document.createElement('div');
    banner.id = 'aether-consent-banner';
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-label', 'Cookie consent');

    const bgColor = theme === 'dark' ? '#1a1a2e' : '#ffffff';
    const textColor = theme === 'dark' ? '#e0e0e0' : '#333333';
    const borderColor = theme === 'dark' ? '#333' : '#e0e0e0';

    banner.innerHTML = `
      <style>
        #aether-consent-banner {
          position: fixed; ${position}: 0; left: 0; right: 0;
          background: ${bgColor}; color: ${textColor};
          border-${position === 'bottom' ? 'top' : 'bottom'}: 1px solid ${borderColor};
          padding: 16px 24px; z-index: 999999;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          font-size: 14px; line-height: 1.5;
          box-shadow: 0 ${position === 'bottom' ? '-2px' : '2px'} 10px rgba(0,0,0,0.1);
          display: flex; align-items: center; justify-content: space-between;
          flex-wrap: wrap; gap: 12px;
        }
        #aether-consent-banner .acb-text { flex: 1; min-width: 300px; }
        #aether-consent-banner .acb-text h4 { margin: 0 0 4px; font-size: 15px; }
        #aether-consent-banner .acb-text p { margin: 0; opacity: 0.85; font-size: 13px; }
        #aether-consent-banner .acb-text a { color: ${accent}; }
        #aether-consent-banner .acb-buttons { display: flex; gap: 8px; flex-shrink: 0; }
        #aether-consent-banner button {
          padding: 8px 20px; border-radius: 6px; font-size: 13px;
          cursor: pointer; font-weight: 500; border: none; transition: opacity 0.2s;
        }
        #aether-consent-banner button:hover { opacity: 0.85; }
        #aether-consent-banner .acb-accept { background: ${accent}; color: #fff; }
        #aether-consent-banner .acb-reject { background: transparent; color: ${textColor}; border: 1px solid ${borderColor}; }
        #aether-consent-banner .acb-customize { background: transparent; color: ${accent}; text-decoration: underline; font-size: 12px; padding: 4px 8px; }
      </style>
      <div class="acb-text">
        <h4>${c.title ?? 'We value your privacy'}</h4>
        <p>${c.description ?? 'We use cookies and similar technologies to improve your experience, analyze traffic, and personalize content.'}
          <a href="${this.config.policyUrl}" target="_blank" rel="noopener">Privacy Policy</a>
        </p>
      </div>
      <div class="acb-buttons">
        <button class="acb-reject">${c.rejectAllText ?? 'Reject All'}</button>
        <button class="acb-accept">${c.acceptAllText ?? 'Accept All'}</button>
      </div>
    `;

    const acceptBtn = banner.querySelector('.acb-accept');
    const rejectBtn = banner.querySelector('.acb-reject');

    acceptBtn?.addEventListener('click', () => {
      this.grantAll();
      this.hideBanner();
    });

    rejectBtn?.addEventListener('click', () => {
      this.revokeAll();
      this.hideBanner();
    });

    document.body.appendChild(banner);
    this.bannerElement = banner;
  }

  /** Hide the consent banner */
  hideBanner(): void {
    if (this.bannerElement) {
      this.bannerElement.remove();
      this.bannerElement = null;
    }
  }

  /** Destroy the consent module */
  destroy(): void {
    this.hideBanner();
    this.listeners = [];
  }

  // ===========================================================================
  // PRIVATE
  // ===========================================================================

  private loadConsent(): ConsentState {
    const defaults: ConsentState = {
      analytics: false,
      marketing: false,
      personalization: false,
      web3: false,
      agent: false,
      commerce: false,
      financial_activity: false,
      credit: false,
      location: false,
      economic_observability: false,
      cross_chain_observability: false,
      fraud_prevention: false,
      updatedAt: now(),
      policyVersion: this.config.policyVersion,
    };
    const stored = storage.get<ConsentState>(CONSENT_KEY);
    // A state persisted before a purpose existed lacks its key entirely.
    // Merging over defaults makes every newly introduced purpose an explicit
    // false — denied — rather than an undefined hole in the state object.
    if (stored) return { ...defaults, ...stored };
    return defaults;
  }

  private persist(): void {
    storage.set(CONSENT_KEY, this.state);
  }

  private notify(): void {
    const state = this.getState();
    this.listeners.forEach((cb) => {
      try { cb(state); } catch { /* ignore listener errors */ }
    });
  }

  private clearFingerprintCache(): void {
    try {
      localStorage.removeItem(FP_STORAGE_KEY);
    } catch {
      // Silent fail — best-effort cleanup
    }
  }
}
