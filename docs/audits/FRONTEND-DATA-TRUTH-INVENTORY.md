# Frontend Data Truth Inventory

This audit classifies runtime mock-mode, fixture, and synthetic-data findings across Aether, Kyber, and Demo. The machine-readable inventory is `docs/_generated/frontend-data-truth-inventory.json`.

## Summary

- Total findings classified: 714
- PR1 remediates fail-closed environment startup, browser MSW startup removal, public worker deletion, and legacy worker cleanup.
- Remaining runtime fixture-backed data hooks are assigned to PR2/PR3 for API-only conversion and backend seed migration.

## Classification Policy

- Runtime synthetic operational data: remove from production entrypoints or migrate to backend demo seed.
- Test-only fixture: retain only under isolated test paths.
- Static product metadata/UI copy: retain if it does not assert tenant-specific operational state.
- Backend/demo dataset: migrate to explicit backend seed ownership.

## Current Inventory

| Path | Line | App | Classification | Remediation | Target | Status |
|---|---:|---|---|---|---|---|
| `frontend/aether/playwright.config.ts` | 25 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/vite.config.ts` | 41 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/vite.config.ts` | 42 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/src/lib/browser/legacy-mock-cleanup.ts` | 1 | aether | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/aether/src/lib/auth/auth0-provider.tsx` | 14 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/src/lib/auth/use-auth.ts` | 9 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/src/lib/auth/use-auth.ts` | 48 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/src/lib/env/index.ts` | 1 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/src/lib/env/config.ts` | 58 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/src/lib/env/config.ts` | 62 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/README.md` | 46 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/ARCHITECTURE.md` | 40 | kyber | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/kyber/ARCHITECTURE.md` | 53 | kyber | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/kyber/ARCHITECTURE.md` | 67 | kyber | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/kyber/ARCHITECTURE.md` | 75 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/ARCHITECTURE.md` | 170 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/ARCHITECTURE.md` | 209 | kyber | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/kyber/ARCHITECTURE.md` | 210 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/ARCHITECTURE.md` | 306 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/ARCHITECTURE.md` | 324 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/ARCHITECTURE.md` | 329 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/ARCHITECTURE.md` | 382 | kyber | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/kyber/ARCHITECTURE.md` | 404 | kyber | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/kyber/AUTH.md` | 17 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/ENVIRONMENT.md` | 7 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/ENVIRONMENT.md` | 21 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/ENVIRONMENT.md` | 22 | kyber | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/kyber/src/fixtures/review.ts` | 147 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/review.ts` | 191 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/review.ts` | 235 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/review.ts` | 264 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/review.ts` | 284 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/review.ts` | 304 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/review.ts` | 324 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/review.ts` | 344 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/review.ts` | 364 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/review.ts` | 384 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 2 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 17 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 20 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 36 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 52 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 54 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 59 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 68 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 70 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 84 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 86 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 111 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 112 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 120 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 121 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 129 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 131 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 144 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 146 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 163 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 190 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 217 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 219 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 220 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 221 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 222 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 225 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 226 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 250 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 251 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/commerce.ts` | 252 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/graph.ts` | 8 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/graph.ts` | 46 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/graph.ts` | 94 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/graph.ts` | 137 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/graph.ts` | 138 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/graph.ts` | 139 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/graph.ts` | 144 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/graph.ts` | 152 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/graph.ts` | 153 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 19 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 249 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 329 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 430 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 478 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 521 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 565 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 651 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 655 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 656 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 660 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 664 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 668 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 669 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 673 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 677 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entities.ts` | 678 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 2 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 6 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 8 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 10 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 11 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 20 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 21 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 30 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 31 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 40 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 41 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 50 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 51 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 52 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 53 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/settlement.ts` | 56 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 17 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 156 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 225 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 272 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 293 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 297 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 301 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 302 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 306 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 307 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/controllers.ts` | 311 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/auth.ts` | 3 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/notifications.ts` | 6 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/features/auth/auth-context.tsx` | 3 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/src/features/auth/auth-context.tsx` | 6 | aether | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/aether/src/features/auth/auth-context.tsx` | 36 | aether | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/aether/src/features/auth/auth-context.tsx` | 48 | aether | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/aether/src/features/auth/auth-context.tsx` | 167 | aether | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/src/features/auth/auth-context.tsx` | 171 | aether | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/aether/src/features/auth/auth-context.tsx` | 180 | aether | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/aether/src/features/auth/auth-context.tsx` | 241 | aether | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/aether/src/features/auth/auth-context.tsx` | 280 | aether | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/aether/src/features/auth/auth-context.tsx` | 293 | aether | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/kyber/src/fixtures/approvals.ts` | 2 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 7 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 8 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 9 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 10 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 11 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 12 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 15 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 17 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 18 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 26 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 27 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 37 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 38 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 44 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 45 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 53 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 54 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 55 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 56 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 57 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 60 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 61 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 62 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/approvals.ts` | 63 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 2 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 6 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 8 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 10 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 11 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 17 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 18 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 26 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 27 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 36 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 37 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 45 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 46 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 47 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/entitlements.ts` | 48 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/events.ts` | 7 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/events.ts` | 10 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/events.ts` | 353 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/events.ts` | 354 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/events.ts` | 358 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/events.ts` | 363 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/events.ts` | 366 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 2 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 6 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 8 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 10 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 12 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 27 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 29 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 44 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 45 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 51 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 52 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 53 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 54 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 57 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/fixtures/resources.ts` | 70 | kyber | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/kyber/src/lib/browser/legacy-mock-cleanup.ts` | 1 | kyber | false positive or UI copy | review during route/data-source conversion | PR2/PR3 | classified |
| `frontend/kyber/src/lib/adapters/index.ts` | 1 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/src/lib/adapters/index.ts` | 6 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/src/lib/api/rest/client.ts` | 4 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/src/lib/api/rest/client.ts` | 47 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/src/lib/auth/auth0-provider.tsx` | 13 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/src/lib/auth/auth0-provider.tsx` | 26 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/src/lib/auth/use-auth.ts` | 9 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/src/lib/auth/use-auth.ts` | 48 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/src/lib/env/index.ts` | 1 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/src/lib/env/config.ts` | 60 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/kyber/src/lib/env/config.ts` | 68 | kyber | runtime mock environment control | fail closed and remove mock branch/banner | PR1 | remediated in PR1 |
| `frontend/aether/src/mocks/handlers.ts` | 8 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 9 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 10 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 11 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 46 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 88 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 89 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 92 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 117 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 142 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 167 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 169 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 170 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 173 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 174 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 177 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 190 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 194 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 198 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 201 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 241 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 281 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 321 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 361 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 401 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 404 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 420 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 436 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 455 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 471 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 487 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 489 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 507 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 525 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 543 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 561 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 580 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 636 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 640 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 653 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 656 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 682 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 708 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 734 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 760 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 762 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 786 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 810 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 835 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 865 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 918 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 949 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 951 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 977 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 979 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 998 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1013 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1015 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1027 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1033 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1036 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1054 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1057 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1069 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1072 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1091 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1093 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1119 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1121 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1143 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1146 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1151 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1157 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1166 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1185 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1188 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1193 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1199 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1204 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1210 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1215 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1221 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1232 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1233 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1234 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1238 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1239 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1242 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1260 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1262 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1266 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1267 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |
| `frontend/aether/src/mocks/handlers.ts` | 1270 | aether | runtime synthetic operational data | remove runtime dependency or migrate to backend seed dataset | PR2/PR3 | pending PR2/PR3 |

Inventory table truncated for readability; see JSON for all 714 findings.
