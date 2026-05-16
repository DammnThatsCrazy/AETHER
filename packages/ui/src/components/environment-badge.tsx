import { Badge } from './badge';

type Environment = 'local-mocked' | 'local-live' | 'staging' | 'production';

const envVariant: Record<Environment, 'success' | 'info' | 'warning' | 'danger'> = {
  'local-mocked': 'success',
  'local-live': 'info',
  staging: 'warning',
  production: 'danger',
};

const envLabel: Record<Environment, string> = {
  'local-mocked': 'LOCAL MOCK',
  'local-live': 'LOCAL LIVE',
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
