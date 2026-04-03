// =============================================================================
// AETHER SDK — CONSENT MODULE (GDPR / CCPA)
// =============================================================================

import type { ConsentState, ConsentConfig, ConsentBannerConfig, ConsentCallback } from './WebSDKTypes(CoreTypeDefinitions)';
import { storage, now } from './SDKUtilityFunctions';

const CONSENT_KEY = 'consent';

export class ConsentModule {
  private state: ConsentState;
  private config: ConsentConfig;
  private listeners: ConsentCallback[] = [];
  private bannerElement: HTMLElement | null = null;

  constructor(config?: Partial<ConsentConfig>) {
    this.config = {
      purposes: ['analytics', 'marketing', 'web3'],
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
  hasConsent(purpose: string): boolean {
    return (this.state as Record<string, unknown>)[purpose] === true;
  }

  /** Check if any consent has been given/recorded */
  hasRecordedConsent(): boolean {
    return !!storage.get(CONSENT_KEY);
  }

  /** Grant consent for specified purposes */
  grant(purposes: string[]): void {
    for (const p of purposes) {
      (this.state as Record<string, unknown>)[p] = true;
    }
    this.state.updatedAt = now();
    this.state.policyVersion = this.config.policyVersion;
    this.persist();
    this.notify();
  }

  /** Revoke consent for specified purposes */
  revoke(purposes: string[]): void {
    for (const p of purposes) {
      (this.state as Record<string, unknown>)[p] = false;
    }
    this.state.updatedAt = now();
    this.persist();
    this.notify();
  }

  /** Grant all purposes */
  grantAll(): void {
    this.grant(this.config.purposes);
  }

  /** Revoke all purposes */
  revokeAll(): void {
    this.revoke(this.config.purposes);
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
    const position = c.position ?? 'bottom';
    const theme = c.theme ?? 'light';
    const accent = c.accentColor ?? '#2E75B6';

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
    const stored = storage.get<ConsentState>(CONSENT_KEY);
    if (stored) return stored;

    // Default: no consent granted
    return {
      analytics: false,
      marketing: false,
      web3: false,
      updatedAt: now(),
      policyVersion: this.config.policyVersion,
    };
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
}
