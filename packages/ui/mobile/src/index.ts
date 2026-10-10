/**
 * @aether/mobile-ui — shared mobile UI kit for the Aether and Kyber apps.
 *
 * Typed dark theme, a lightweight typed navigator (no external navigation library),
 * and shared components (ScreenHeader / Card / Button). Depends only on react +
 * react-native. The platform-agnostic parts (theme, navigator registry) carry no
 * react-native import and are unit-testable in plain Node.
 */
export { theme, useTheme, type Theme } from './theme';

export {
  createNavigatorRegistry,
  type NavigatorRegistry,
  type NavigatorState,
  type RouteMap,
  type RouteParams,
  type RouteState,
} from './navigation';

export {
  createNavigator,
  type Navigator,
  type StackScreenProps,
} from './navigation-container';

export { ScreenHeader, type ScreenHeaderProps } from './components/ScreenHeader';
export { Card, type CardProps } from './components/Card';
export { Button, type ButtonVariant, type ButtonProps } from './components/Button';
