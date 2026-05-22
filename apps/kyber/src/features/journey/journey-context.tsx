import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import Aether from '@aether/web';
import type { ResolvedIdentity } from '@aether/web';
import { useAuth } from '@kyber/features/auth';
import { env } from '@kyber/lib/env';

interface JourneyContextValue {
  /** The identity resolved from a prior device, or null if this is a fresh session. */
  resumedFrom: ResolvedIdentity | null;
  /** True if a prior journey was detected and merged this session. */
  hasResumed: boolean;
  /**
   * Persist an arbitrary value into SDK traits so it is restored when the
   * same user returns on another device.
   * Example: setJourneyTrait('onboarding_step', 'review')
   */
  setJourneyTrait: (key: string, value: unknown) => void;
}

const JourneyContext = createContext<JourneyContextValue>({
  resumedFrom: null,
  hasResumed: false,
  setJourneyTrait: () => {},
});

export function JourneyProvider({ children }: { readonly children: ReactNode }) {
  const { user } = useAuth();
  const [resumedFrom, setResumedFrom] = useState<ResolvedIdentity | null>(null);
  const initialized = useRef(false);

  // Initialize SDK exactly once per app lifetime.
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    Aether.init({
      apiKey: env.VITE_AETHER_API_KEY,
      endpoint: env.VITE_AETHER_ENDPOINT,
      environment: env.VITE_KYBER_ENV === 'production' ? 'production'
        : env.VITE_KYBER_ENV === 'staging' ? 'staging'
        : 'development',
      autoResumeJourney: true,
      onJourneyResumed: (identity) => {
        setResumedFrom(identity);
      },
      modules: {
        autoDiscovery: true,
        performance: true,
      },
    });

    return () => {
      Aether.destroy();
      initialized.current = false;
    };
  }, []);

  // Bridge authenticated user into SDK identity so userId flows into all events.
  useEffect(() => {
    if (!user) return;
    Aether.hydrateIdentity({
      userId: user.id,
      traits: {
        email: user.email,
        displayName: user.displayName,
      },
    });
  }, [user?.id]);

  const setJourneyTrait = (key: string, value: unknown) => {
    Aether.hydrateIdentity({ traits: { [key]: value } });
  };

  return (
    <JourneyContext.Provider value={{ resumedFrom, hasResumed: resumedFrom !== null, setJourneyTrait }}>
      {children}
    </JourneyContext.Provider>
  );
}

export function useJourney(): JourneyContextValue {
  return useContext(JourneyContext);
}
