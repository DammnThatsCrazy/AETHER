/**
 * The app's typed navigator — one module-scope `createNavigator` instance shared by
 * every screen (see `packages/mobile-ui/src/navigation-container.tsx`).
 *
 * `Screen` renders the theme-consistent header shell; `navigate` pushes typed routes
 * and `goBack` pops. Screens import the same `Screen` so the header reflects the
 * live stack. The root tabs switch via `navigate(tab)`; a back affordance appears
 * only for pushed (non-root) routes, which M3b does not use.
 */
import { createNavigator } from '@aether/mobile-ui';

import type { AppRoutes } from './routes';

export const { Screen, navigate, goBack } = createNavigator<AppRoutes>();
