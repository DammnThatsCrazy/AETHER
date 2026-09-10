export {
  resolveDeploymentEnvironment,
  describeEnvironment,
  readEnvVar,
  readOptionalEnvVar,
} from './env';
export type { DeploymentEnvironment, EnvironmentConfig } from './env';

export { buildAmplifyEnvironmentConfig } from './amplify';
export type { AmplifyEnvironmentConfig } from './amplify';

export { PRODUCTION_DOMAINS, buildDomainMap, originFor } from './domains';
export type { DomainMap, ProductSubdomain } from './domains';
