export type ShikiRole =
  | 'shiki_executive_operator'
  | 'shiki_engineering_command'
  | 'shiki_specialist_operator'
  | 'shiki_observer';

export interface ShikiUser {
  readonly id: string;
  readonly email: string;
  readonly displayName: string;
  readonly role: ShikiRole;
  readonly groups: readonly string[];
  readonly avatarUrl?: string | undefined;
  readonly lastLogin?: string | undefined;
}

export interface AuthState {
  readonly isAuthenticated: boolean;
  readonly user: ShikiUser | null;
  readonly isLoading: boolean;
  readonly error: string | null;
}

export interface OIDCConfig {
  readonly authority: string;
  readonly clientId: string;
  readonly redirectUri: string;
  readonly postLogoutRedirectUri: string;
  readonly scope: string;
  readonly responseType: string;
}

export interface AuthTokens {
  readonly accessToken: string;
  readonly idToken: string;
  readonly refreshToken?: string | undefined;
  readonly expiresAt: number;
}
