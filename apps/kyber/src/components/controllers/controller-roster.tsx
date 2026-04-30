import type { Controller, ControllerDisplayMode } from '@kyber/types';
import { ControllerCard } from './controller-card';
import { cn } from '@kyber/lib/utils';

interface ControllerRosterProps {
  readonly controllers: readonly Controller[];
  readonly displayMode: ControllerDisplayMode;
  readonly className?: string;
}

export function ControllerRoster({ controllers, displayMode, className }: ControllerRosterProps) {
  return (
    <div className={cn('grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3', className)}>
      {controllers.map((ctrl) => (
        <ControllerCard key={ctrl.name} controller={ctrl} displayMode={displayMode} />
      ))}
    </div>
  );
}
