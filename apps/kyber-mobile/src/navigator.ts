/**
 * The app's typed navigator — one module-scope `createNavigator` instance shared
 * by every screen (see `packages/mobile-ui/src/navigation-container.tsx`).
 *
 * `Screen` renders the theme-consistent header shell; `navigate` pushes typed
 * routes and `goBack` pops. The root tabs switch via `navigate(tab)`; a back
 * affordance appears only for pushed (non-root) routes, which M4a does not use.
 */
import { createNavigator } from '@aether/mobile-ui';

import type { KyberRoutes } from './routes';

export const { Screen, navigate, goBack } = createNavigator<KyberRoutes>();
