import { useState, type ReactNode } from 'react';
import { cn } from '@shiki/lib/utils';

interface TooltipProps {
  readonly content: string;
  readonly children: ReactNode;
  readonly className?: string;
}

export function Tooltip({ content, children, className }: TooltipProps) {
  const [show, setShow] = useState(false);
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
    >
      {children}
      {show && (
        <span
          role="tooltip"
          className={cn(
            'absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 text-xs bg-surface-sunken text-text-primary border border-border-default rounded whitespace-nowrap z-50',
            className,
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}
