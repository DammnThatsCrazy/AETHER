import type { Session } from '../types';
export declare class SessionManager {
    private session;
    private heartbeatTimer;
    private heartbeatInterval;
    private onHeartbeat?;
    constructor(heartbeatInterval?: number, onHeartbeat?: (session: Session) => void);
    /** Initialize or resume a session */
    start(): Session;
    /** Get current session */
    getSession(): Session | null;
    /** Record activity (extends session timeout) */
    touch(): void;
    /** Increment page count */
    recordPageView(url: string): void;
    /** Increment event count */
    recordEvent(): void;
    /** End the current session */
    end(): void;
    /** Reset session (new anonymous session) */
    reset(): Session;
    /** Destroy session manager */
    destroy(): void;
    /** Get session duration in ms */
    getDuration(): number;
    private createSession;
    private isSessionValid;
    private loadSession;
    private saveSession;
    private startHeartbeat;
    private stopHeartbeat;
}
