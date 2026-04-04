import { cn } from '@shiki/lib/utils';
import type { ReactNode } from 'react';

interface ScrollAreaProps {
  readonly children: ReactNode;
  readonly className?: string | undefined;
  readonly maxHeight?: string | undefined;
}

export function ScrollArea({ children, className, maxHeight = '400px' }: ScrollAreaProps) {
  return (
    <div className={cn('overflow-auto', className)} style={{ maxHeight }}>
      {children}
    </div>
  );
}
