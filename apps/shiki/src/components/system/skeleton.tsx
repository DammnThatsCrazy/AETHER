import { cn } from '@shiki/lib/utils';

interface SkeletonProps {
  readonly className?: string;
  readonly width?: string;
  readonly height?: string;
}

export function Skeleton({ className, width, height }: SkeletonProps) {
  return (
    <div
      className={cn('animate-pulse rounded bg-border-default', className)}
      style={{ width, height }}
      aria-hidden="true"
    />
  );
}
