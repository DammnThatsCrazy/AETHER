/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Visibility tier baked into this bundle at build time: P | C | I */
  readonly VITE_TIER: 'P' | 'C' | 'I';
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
