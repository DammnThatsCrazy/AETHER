// =============================================================================
// AETHER SDK — SESSION MANAGER
// =============================================================================

import type { Session, DeviceContext, CampaignContext } from './WebSDKTypes(CoreTypeDefinitions)';
import { generateId, now, storage, getDeviceContext, getCampaignContext } from './SDKUtilityFunctions';

const SESSION_KEY = 'session';
const SESSION_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

export class SessionManager {
  private session: Session | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private heartbeatInterval: number;
  private onHeartbeat?: (session: Session) => void;

  constructor(heartbeatInterval = 30000, onHeartbeat?: (session: Session) => void) {
    this.heartbeatInterval = heartbeatInterval;
    this.onHeartbeat = onHeartbeat;
  }

  /** Initialize or resume a session */
  start(): Session {
    const existing = this.loadSession();

    if (existing && this.isSessionValid(existing)) {
      this.session = {
        ...existing,
        lastActivityAt: now(),
        isActive: true,
      };
    } else {
      this.session = this.createSession();
    }

    this.saveSession();
    this.startHeartbeat();
    return this.session;
  }

  /** Get current session */
  getSession(): Session | null {
    return this.session;
  }

  /** Record activity (extends session timeout) */
  touch(): void {
    if (!this.session) return;
    this.session.lastActivityAt = now();
    this.session.isActive = true;
    this.saveSession();
  }

  /** Increment page count */
  recordPageView(url: string): void {
    if (!this.session) return;
    this.session.pageCount++;
    this.session.currentPage = url;
    this.touch();
  }

  /** Increment event count */
  recordEvent(): void {
    if (!this.session) return;
    this.session.eventCount++;
    this.touch();
  }

  /** End the current session */
  end(): void {
    if (!this.session) return;
    this.session.isActive = false;
    this.saveSession();
    this.stopHeartbeat();
  }

  /** Reset session (new anonymous session) */
  reset(): Session {
    this.end();
    storage.remove(SESSION_KEY);
    this.session = this.createSession();
    this.saveSession();
    this.startHeartbeat();
    return this.session;
  }

  /** Destroy session manager */
  destroy(): void {
    this.end();
    this.stopHeartbeat();
    this.session = null;
  }

  /** Get session duration in ms */
  getDuration(): number {
    if (!this.session) return 0;
    return new Date(this.session.lastActivityAt).getTime() - new Date(this.session.startedAt).getTime();
  }

  // ===========================================================================
  // PRIVATE
  // ===========================================================================

  private createSession(): Session {
    const device = typeof window !== 'undefined' ? getDeviceContext() : ({} as DeviceContext);
    const campaign = typeof window !== 'undefined' ? getCampaignContext() : ({} as CampaignContext);
    const currentUrl = typeof window !== 'undefined' ? window.location.href : '';

    return {
      id: generateId(),
      startedAt: now(),
      lastActivityAt: now(),
      pageCount: 0,
      eventCount: 0,
      landingPage: currentUrl,
      currentPage: currentUrl,
      referrer: typeof document !== 'undefined' ? document.referrer : '',
      campaign: campaign.source ? campaign : undefined,
      device,
      isActive: true,
    };
  }

  private isSessionValid(session: Session): boolean {
    const lastActivity = new Date(session.lastActivityAt).getTime();
    const elapsed = Date.now() - lastActivity;
    return elapsed < SESSION_TIMEOUT_MS && session.isActive;
  }

  private loadSession(): Session | null {
    return storage.get<Session>(SESSION_KEY);
  }

  private saveSession(): void {
    if (this.session) {
      storage.set(SESSION_KEY, this.session);
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.session?.isActive && this.onHeartbeat) {
        this.touch();
        this.onHeartbeat(this.session);
      }
    }, this.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }
}
