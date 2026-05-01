import { createContext, useContext, useReducer, useCallback, useEffect, type ReactNode } from 'react';
import type { KyberNotification, NotificationState, Severity, NotificationChannel } from '@kyber/types';
import { isLocalMocked } from '@kyber/lib/env';
import { MOCK_NOTIFICATIONS } from '@kyber/fixtures/notifications';

interface NotificationContextValue extends NotificationState {
  addNotification: (notification: KyberNotification) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  dismiss: (id: string) => void;
  clearAll: () => void;
}

type NotifAction =
  | { type: 'ADD'; notification: KyberNotification }
  | { type: 'MARK_READ'; id: string }
  | { type: 'MARK_ALL_READ' }
  | { type: 'DISMISS'; id: string }
  | { type: 'CLEAR_ALL' }
  | { type: 'SET_CONNECTED'; connected: boolean }
  | { type: 'BULK_ADD'; notifications: readonly KyberNotification[] };

function dedupeNotification(existing: readonly KyberNotification[], incoming: KyberNotification): boolean {
  return existing.some(n => n.dedupeKey === incoming.dedupeKey && !n.dismissed);
}

function notifReducer(state: NotificationState, action: NotifAction): NotificationState {
  switch (action.type) {
    case 'ADD': {
      if (dedupeNotification(state.notifications, action.notification)) return state;
      const notifications = [action.notification, ...state.notifications].slice(0, 500);
      return { ...state, notifications, unreadCount: notifications.filter(n => !n.read).length };
    }
    case 'BULK_ADD': {
      const newNotifs = action.notifications.filter(n => !dedupeNotification(state.notifications, n));
      const notifications = [...newNotifs, ...state.notifications].slice(0, 500);
      return { ...state, notifications, unreadCount: notifications.filter(n => !n.read).length };
    }
    case 'MARK_READ': {
      const notifications = state.notifications.map(n => n.id === action.id ? { ...n, read: true } : n);
      return { ...state, notifications, unreadCount: notifications.filter(n => !n.read).length };
    }
    case 'MARK_ALL_READ': {
      const notifications = state.notifications.map(n => ({ ...n, read: true }));
      return { ...state, notifications, unreadCount: 0 };
    }
    case 'DISMISS': {
      const notifications = state.notifications.map(n => n.id === action.id ? { ...n, dismissed: true } : n);
      return { ...state, notifications, unreadCount: notifications.filter(n => !n.read && !n.dismissed).length };
    }
    case 'CLEAR_ALL':
      return { ...state, notifications: [], unreadCount: 0 };
    case 'SET_CONNECTED':
      return { ...state, isConnected: action.connected };
  }
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

// Severity routing rules
const SEVERITY_CHANNELS: Record<Severity, readonly NotificationChannel[]> = {
  P0: ['in-app', 'browser', 'email', 'slack'],
  P1: ['in-app', 'browser', 'email', 'slack'],
  P2: ['in-app', 'slack'],
  P3: ['in-app'],
  info: ['in-app'],
};

// Throttle: max 1 notification per dedupeKey per 60s
const throttleMap = new Map<string, number>();
const THROTTLE_WINDOW_MS = 60_000;

function shouldThrottle(dedupeKey: string): boolean {
  const now = Date.now();
  const last = throttleMap.get(dedupeKey);
  if (last && now - last < THROTTLE_WINDOW_MS) return true;
  throttleMap.set(dedupeKey, now);
  return false;
}

function routeToExternalChannels(notification: KyberNotification): void {
  const channels = SEVERITY_CHANNELS[notification.severity];

  if (channels.includes('browser') && 'Notification' in window && Notification.permission === 'granted') {
    try {
      new Notification(notification.title, {
        body: notification.body,
        tag: notification.dedupeKey,
      });
    } catch { /* browser notification not available */ }
  }

  if (channels.includes('slack')) {
    // Deliver via backend notification service
    fetch('/v1/notifications/alerts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: notification.title,
        condition: `severity:${notification.severity}`,
        channels: ['slack'],
        recipients: [],
      }),
    }).catch(() => { /* Slack relay failure is non-blocking */ });
  }

  if (channels.includes('email')) {
    fetch('/v1/notifications/alerts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: notification.title,
        condition: `severity:${notification.severity}`,
        channels: ['email'],
        recipients: [],
      }),
    }).catch(() => { /* Email relay failure is non-blocking */ });
  }
}

// Escalation: if a P1+ notification is unread for >5 minutes, escalate
function startEscalationTimer(notification: KyberNotification, escalate: (id: string) => void): ReturnType<typeof setTimeout> | null {
  if (notification.severity !== 'P0' && notification.severity !== 'P1') return null;
  const delay = notification.severity === 'P0' ? 2 * 60_000 : 5 * 60_000;
  return setTimeout(() => escalate(notification.id), delay);
}

export function NotificationProvider({ children }: { readonly children: ReactNode }) {
  const [state, dispatch] = useReducer(notifReducer, {
    notifications: [],
    unreadCount: 0,
    isConnected: false,
  });

  // Load notifications — mock in local, real alerts in live mode
  useEffect(() => {
    if (isLocalMocked()) {
      dispatch({ type: 'BULK_ADD', notifications: MOCK_NOTIFICATIONS });
      dispatch({ type: 'SET_CONNECTED', connected: true });
      return;
    }

    // Live mode: fetch real alerts from backend
    fetch('/v1/notifications/alerts')
      .then(r => r.json())
      .then((response: { data?: unknown[] }) => {
        const alerts = Array.isArray(response.data) ? response.data : [];
        const mapped: KyberNotification[] = alerts.map((raw: unknown, idx: number) => {
          const a = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
          return {
            id: String(a['id'] ?? `alert-${idx}`),
            title: String(a['name'] ?? 'Alert'),
            body: String(a['condition'] ?? ''),
            severity: String(a['severity'] ?? 'info') as Severity,
            class: 'alert' as const,
            channels: ['in-app' as const],
            timestamp: String(a['created_at'] ?? new Date().toISOString()),
            read: false,
            dismissed: false,
            deepLink: '/diagnostics',
            what: String(a['name'] ?? 'Alert triggered'),
            why: String(a['condition'] ?? 'Condition met'),
            impact: 'See diagnostics for details',
            dedupeKey: `backend-alert-${a['id'] ?? idx}`,
          };
        });
        if (mapped.length > 0) {
          dispatch({ type: 'BULK_ADD', notifications: mapped });
        }
        dispatch({ type: 'SET_CONNECTED', connected: true });
      })
      .catch(() => {
        dispatch({ type: 'SET_CONNECTED', connected: false });
      });
  }, []);

  const escalationTimers = new Map<string, ReturnType<typeof setTimeout>>();

  const addNotification = useCallback((notification: KyberNotification) => {
    if (shouldThrottle(notification.dedupeKey)) return;
    dispatch({ type: 'ADD', notification });
    routeToExternalChannels(notification);

    const timer = startEscalationTimer(notification, (id) => {
      // Re-dispatch with elevated urgency
      window.dispatchEvent(new CustomEvent('kyber:notification:escalate', { detail: { id } }));
    });
    if (timer) escalationTimers.set(notification.id, timer);
  }, []);

  const markRead = useCallback((id: string) => {
    dispatch({ type: 'MARK_READ', id });
    const timer = escalationTimers.get(id);
    if (timer) {
      clearTimeout(timer);
      escalationTimers.delete(id);
    }
  }, []);

  const markAllRead = useCallback(() => {
    dispatch({ type: 'MARK_ALL_READ' });
    escalationTimers.forEach(t => clearTimeout(t));
    escalationTimers.clear();
  }, []);

  const dismiss = useCallback((id: string) => dispatch({ type: 'DISMISS', id }), []);
  const clearAll = useCallback(() => dispatch({ type: 'CLEAR_ALL' }), []);

  return (
    <NotificationContext.Provider value={{ ...state, addNotification, markRead, markAllRead, dismiss, clearAll }}>
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error('useNotifications must be used within NotificationProvider');
  return ctx;
}
