export type KyberRole =
  | 'kyber_executive_operator'
  | 'kyber_engineering_command'
  | 'kyber_specialist_operator'
  | 'kyber_observer';

export interface KyberUser {
  readonly id: string;
  readonly email: string;
  readonly displayName: string;
  readonly role: KyberRole;
  readonly groups: readonly string[];
  readonly avatarUrl?: string | undefined;
  readonly lastLogin?: string | undefined;
}

export interface AuthState {
  readonly isAuthenticated: boolean;
  readonly user: KyberUser | null;
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
