/**
 * Shared frontend time system — viewer context provider.
 *
 * Resolves the active TimeContext once per app using the canonical order:
 * manual preference → device zone (automatic) → tenant display default →
 * UTC fallback. The active lens can be switched (viewer/tenant/event/utc);
 * the resolution that produced the context stays visible so surfaces can
 * disclose WHICH clock the user is looking at.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import type { ResolvedViewerTime, TimeContext, TimeLens, TimeZoneResolution } from './types';
import { UTC_CONTEXT } from './types';

export interface TimeProviderPreferences {
  /** From /v1/preferences/temporal (when the feature flag is on). */
  mode?: 'automatic' | 'manual';
  manualTimeZone?: string | null;
  locale?: string | null;
  hourCycle?: 'h12' | 'h23' | null;
  weekStart?: number | null;
  /** Tenant display default (from tenant temporal defaults). */
  tenantDisplayTimeZone?: string | null;
  tenantBusinessTimeZone?: string | null;
}

interface TimeContextValue {
  resolved: ResolvedViewerTime;
  lens: TimeLens;
  setLens: (lens: TimeLens) => void;
  /** Context for an arbitrary lens (event lens needs the event's zone). */
  contextFor: (lens: TimeLens, eventTimeZone?: string | null) => TimeContext;
}

const TimeReactContext = createContext<TimeContextValue | null>(null);

function deviceZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? null;
  } catch {
    return null;
  }
}

function deviceLocale(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().locale ?? 'en-US';
  } catch {
    return 'en-US';
  }
}

export function resolveViewerContext(
  preferences: TimeProviderPreferences | undefined,
  device: { zone: string | null; locale: string },
): ResolvedViewerTime {
  const locale = preferences?.locale ?? device.locale;
  const base = {
    locale,
    lens: 'viewer' as const,
    ...(preferences?.hourCycle ? { hourCycle: preferences.hourCycle } : {}),
    ...(preferences?.weekStart != null ? { weekStart: preferences.weekStart } : {}),
  };
  let timeZone: string | null = null;
  let resolution: TimeZoneResolution = 'utc_fallback';
  if (preferences?.mode === 'manual' && preferences.manualTimeZone) {
    timeZone = preferences.manualTimeZone;
    resolution = 'manual_preference';
  } else if (device.zone) {
    timeZone = device.zone;
    resolution = 'device_automatic';
  } else if (preferences?.tenantDisplayTimeZone) {
    timeZone = preferences.tenantDisplayTimeZone;
    resolution = 'tenant_display_default';
  }
  if (!timeZone) {
    return { context: { ...UTC_CONTEXT, locale }, resolution: 'utc_fallback' };
  }
  return { context: { ...base, timeZone }, resolution };
}

export function TimeProvider({
  children,
  preferences,
}: {
  children: ReactNode;
  preferences?: TimeProviderPreferences;
}) {
  const [device, setDevice] = useState(() => ({ zone: deviceZone(), locale: deviceLocale() }));
  const [lens, setLens] = useState<TimeLens>('viewer');

  // Automatic mode must follow the device when its zone changes (travel,
  // OS settings). Re-check when the tab regains visibility — no polling.
  useEffect(() => {
    const recheck = () => {
      const zone = deviceZone();
      setDevice((current) => (current.zone === zone ? current : { ...current, zone }));
    };
    document.addEventListener('visibilitychange', recheck);
    return () => document.removeEventListener('visibilitychange', recheck);
  }, []);

  const resolved = useMemo(
    () => resolveViewerContext(preferences, device),
    [preferences, device],
  );

  const contextFor = useCallback(
    (target: TimeLens, eventTimeZone?: string | null): TimeContext => {
      switch (target) {
        case 'viewer':
          return resolved.context;
        case 'tenant':
          return preferences?.tenantBusinessTimeZone
            ? { ...resolved.context, timeZone: preferences.tenantBusinessTimeZone, lens: 'tenant' }
            : { ...resolved.context, lens: 'tenant' };
        case 'event':
          return eventTimeZone
            ? { ...resolved.context, timeZone: eventTimeZone, lens: 'event' }
            : { ...UTC_CONTEXT, locale: resolved.context.locale, lens: 'event' };
        case 'utc':
          return { ...UTC_CONTEXT, locale: resolved.context.locale };
      }
    },
    [resolved, preferences],
  );

  const value = useMemo(
    () => ({ resolved, lens, setLens, contextFor }),
    [resolved, lens, contextFor],
  );

  return <TimeReactContext.Provider value={value}>{children}</TimeReactContext.Provider>;
}

export function useTime(): TimeContextValue {
  const value = useContext(TimeReactContext);
  if (!value) {
    throw new Error('useTime must be used inside <TimeProvider>');
  }
  return value;
}

/** The active rendering context for the current lens. */
export function useTimeContext(eventTimeZone?: string | null): TimeContext {
  const { lens, contextFor } = useTime();
  return contextFor(lens, eventTimeZone);
}
