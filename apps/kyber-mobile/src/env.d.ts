/**
 * Build-time environment variables (EXPO_PUBLIC_*). Inlined by the Expo toolchain at
 * bundle time. Only names intended to ship in the client binary may be declared here —
 * anything EXPO_PUBLIC_ is visible in the shipped bundle, so secrets must never be added.
 */
declare const process: {
  env: {
    EXPO_PUBLIC_API_BASE_URL?: string;
    EXPO_PUBLIC_ENVIRONMENT?: string;
  };
};
