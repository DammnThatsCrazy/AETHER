import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { cn } from '../utils/cn';

type ToastVariant = 'success' | 'error' | 'info';

interface Toast {
  id: string;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  toast: {
    success: (message: string) => void;
    error: (message: string) => void;
    info: (message: string) => void;
  };
}

const ToastContext = createContext<ToastContextValue | null>(null);

let toastCounter = 0;

export function ToastProvider({ children }: { readonly children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const add = useCallback((message: string, variant: ToastVariant) => {
    const id = `toast-${++toastCounter}`;
    setToasts(prev => {
      const next = [...prev, { id, message, variant }];
      return next.slice(-3);
    });
    const timer = setTimeout(() => dismiss(id), 3000);
    timers.current.set(id, timer);
  }, [dismiss]);

  useEffect(() => {
    return () => {
      timers.current.forEach(t => clearTimeout(t));
    };
  }, []);

  const toast = {
    success: (msg: string) => add(msg, 'success'),
    error: (msg: string) => add(msg, 'error'),
    info: (msg: string) => add(msg, 'info'),
  };

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80"
      >
        {toasts.map(t => (
          <div
            key={t.id}
            className="bg-surface-overlay border border-border-default rounded font-mono text-xs px-3 py-2 flex items-start gap-2 shadow-lg"
          >
            <span
              className={cn(
                'shrink-0 mt-px',
                t.variant === 'success' && 'text-success',
                t.variant === 'error' && 'text-danger',
                t.variant === 'info' && 'text-text-muted',
              )}
            >
              {t.variant === 'success' ? '[✓]' : t.variant === 'error' ? '[!]' : '[·]'}
            </span>
            <span className="flex-1 text-text-primary">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              className="shrink-0 text-text-muted hover:text-text-primary"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

export { ToastProvider as Toaster };
