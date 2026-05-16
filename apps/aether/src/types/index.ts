// Customer domain types — add as features are built out.

export type AetherEnvironment = 'local-mocked' | 'local-live' | 'staging' | 'production';

export interface AetherUser {
  readonly id: string;
  readonly email: string;
  readonly displayName: string;
  readonly avatarUrl?: string | undefined;
}

export interface AuthTokens {
  readonly accessToken: string;
  readonly idToken: string;
  readonly refreshToken?: string | undefined;
  readonly expiresAt: number;
}

export interface AuthState {
  readonly isAuthenticated: boolean;
  readonly user: AetherUser | null;
  readonly isLoading: boolean;
  readonly error: string | null;
}
