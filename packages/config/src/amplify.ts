import { describeEnvironment, readEnvVar, readOptionalEnvVar, type DeploymentEnvironment } from './env';
import { buildDomainMap, type DomainMap } from './domains';

/**
 * AWS Amplify environment configuration surface — the values an Amplify
 * Hosting build needs beyond the static build spec in `amplify.yml`: which
 * API origin the built app should call, which Cognito user pool backs
 * authentication, and which deployment environment (and Amplify branch) the
 * build belongs to.
 *
 * No default here points at a real AWS resource — a Cognito pool id,
 * identity pool id, and API URL are deployment-specific and unknown to this
 * package. Every field is either derived from `domains.ts` (already-real
 * origins) or explicitly optional/placeholder, so a build that has not wired
 * Amplify yet gets an honestly incomplete config rather than a fabricated one.
 */

export interface AmplifyEnvironmentConfig {
  readonly environment: DeploymentEnvironment;
  readonly branch: string;
  /** The API origin this build should call. Falls back to the Aether app
   * origin's domain when no API-specific override is supplied — most deploys
   * front the API behind the same origin family. */
  readonly apiUrl: string;
  /** AWS region the Cognito resources live in. */
  readonly authRegion: string;
  /** Cognito user pool id, e.g. `us-east-1_abc123`. Undefined until a real
   * pool is provisioned for this environment — never a placeholder value. */
  readonly userPoolId: string | undefined;
  /** Cognito app client id for this build. */
  readonly userPoolClientId: string | undefined;
  /** Cognito identity pool id, when federated/guest AWS credentials are used. */
  readonly identityPoolId: string | undefined;
  readonly domains: DomainMap;
}

/** Default AWS region for Cognito resources when a deploy does not override it. */
const DEFAULT_AUTH_REGION = 'us-east-1';

/**
 * Build an `AmplifyEnvironmentConfig` from an env-ish source record — the
 * same `process.env` / `import.meta.env` / plain-object contract every
 * function in `env.ts` follows. Recognized keys:
 *
 *   AMPLIFY_ENV | VITE_AMPLIFY_ENV        deployment environment name
 *   AWS_BRANCH                            Amplify Hosting's own branch var
 *   VITE_API_BASE_URL                     API origin override
 *   VITE_COGNITO_REGION                   Cognito region override
 *   VITE_COGNITO_USER_POOL_ID
 *   VITE_COGNITO_USER_POOL_CLIENT_ID
 *   VITE_COGNITO_IDENTITY_POOL_ID
 */
export function buildAmplifyEnvironmentConfig(
  source: Readonly<Record<string, string | undefined>>,
  domainOverrides: Partial<DomainMap> = {},
): AmplifyEnvironmentConfig {
  const { name: environment } = describeEnvironment(
    readOptionalEnvVar(source, 'AMPLIFY_ENV') ?? readOptionalEnvVar(source, 'VITE_AMPLIFY_ENV'),
  );
  const domains = buildDomainMap(domainOverrides);

  return {
    environment,
    branch: readEnvVar(source, 'AWS_BRANCH', 'main'),
    apiUrl: readEnvVar(source, 'VITE_API_BASE_URL', domains.aetherApp),
    authRegion: readEnvVar(source, 'VITE_COGNITO_REGION', DEFAULT_AUTH_REGION),
    userPoolId: readOptionalEnvVar(source, 'VITE_COGNITO_USER_POOL_ID'),
    userPoolClientId: readOptionalEnvVar(source, 'VITE_COGNITO_USER_POOL_CLIENT_ID'),
    identityPoolId: readOptionalEnvVar(source, 'VITE_COGNITO_IDENTITY_POOL_ID'),
    domains,
  };
}
