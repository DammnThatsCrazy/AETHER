import { Badge } from './badge';

type Environment = 'local' | 'staging' | 'production' | 'test';

const envVariant: Record<Environment, 'success' | 'info' | 'warning' | 'danger'> = {
  local: 'info',
  test: 'success',
  staging: 'warning',
  production: 'danger',
};

const envLabel: Record<Environment, string> = {
  local: 'LOCAL',
  test: 'TEST',
  staging: 'STAGING',
  production: 'PRODUCTION',
};

interface EnvironmentBadgeProps {
  readonly environment: Environment;
  readonly className?: string | undefined;
}

export function EnvironmentBadge({ environment, className }: EnvironmentBadgeProps) {
  return (
    <Badge variant={envVariant[environment]} className={className}>
      {envLabel[environment]}
    </Badge>
  );
}
