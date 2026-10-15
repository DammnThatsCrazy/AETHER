import { cn } from '../utils/cn';
import { Button } from './button';
import { Icon } from './icon';

interface ErrorStateProps {
  readonly title?: string;
  readonly message: string;
  readonly onRetry?: () => void;
  readonly className?: string;
}

export function ErrorState({ title = 'Error', message, onRetry, className }: ErrorStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center py-12 text-center', className)}>
      <Icon name="triangle-alert" size="xl" decorative className="mb-3 text-danger" />
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
