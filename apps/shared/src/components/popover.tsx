import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react';
import { cn } from '../utils/cn';

interface PopoverProps {
  trigger: ReactElement;
  content: ReactNode;
  className?: string;
}

export function Popover({ trigger, content, className }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    function onOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        close();
      }
    }
    function onEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    document.addEventListener('mousedown', onOutside);
    document.addEventListener('keydown', onEscape);
    return () => {
      document.removeEventListener('mousedown', onOutside);
      document.removeEventListener('keydown', onEscape);
    };
  }, [open, close]);

  const triggerEl = isValidElement(trigger)
    ? cloneElement(trigger as ReactElement<{ onClick?: () => void }>, {
        onClick: () => setOpen(v => !v),
      })
    : trigger;

  return (
    <div ref={containerRef} className="relative inline-block">
      {triggerEl}
      {open && (
        <div
          className={cn(
            'absolute z-50 right-0 top-full mt-1 bg-surface-overlay border border-border-default rounded p-3 text-xs shadow-lg min-w-[160px]',
            className,
          )}
        >
          {content}
        </div>
      )}
    </div>
  );
}
