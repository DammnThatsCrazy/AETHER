// The demo app's single data-source entrypoint.
//
// Profiles that policy allows to ship compiled-in synthetic data
// (`local-mocked`, `demo-static`) resolve this module to `./fixtures`.
// `demo-live` builds alias `@demo/data/dataset` to `./dataset.live` in
// `vite.config.ts`, so the fixture module is never resolved and never emitted.
// Application code must import from here, never from `./fixtures` directly.
export * from './fixtures';
