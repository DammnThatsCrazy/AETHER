import { cn } from '@shiki/lib/utils';
import { Skeleton } from './skeleton';

interface LoadingStateProps {
  readonly lines?: number;
  readonly className?: string;
}

export function LoadingState({ lines = 3, className }: LoadingStateProps) {
  return (
    <div className={cn('space-y-3 py-4', className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className="h-4" width={`${80 - i * 15}%`} />
      ))}
    </div>
  );
}
