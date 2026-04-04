import { cn } from '@shiki/lib/utils';
import { Button } from './button';

interface ErrorStateProps {
  readonly title?: string;
  readonly message: string;
  readonly onRetry?: () => void;
  readonly className?: string;
}

export function ErrorState({ title = 'Error', message, onRetry, className }: ErrorStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center py-12 text-center', className)}>
      <div className="text-3xl text-danger mb-3 font-mono">{'\u26A0'}</div>
      <div className="text-sm font-medium text-danger">{title}</div>
      <div className="text-xs text-text-secondary mt-1 max-w-md">{message}</div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry} className="mt-4">
          Retry
        </Button>
      )}
    </div>
  );
}
