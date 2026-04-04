/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SHIKI_ENV: string;
  readonly VITE_API_BASE_URL: string;
  readonly VITE_WS_BASE_URL: string;
  readonly VITE_GRAPHQL_URL: string;
  readonly VITE_OIDC_AUTHORITY: string;
  readonly VITE_OIDC_CLIENT_ID: string;
  readonly VITE_OIDC_REDIRECT_URI: string;
  readonly VITE_OIDC_SCOPE: string;
  readonly VITE_SLACK_WEBHOOK_URL: string;
  readonly VITE_AUTOMATION_POSTURE: string;
  readonly VITE_FEATURE_FLAGS: string;
  [key: string]: string | undefined;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
