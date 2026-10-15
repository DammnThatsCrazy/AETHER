/**
 * React Native stack container built on the pure navigator registry.
 *
 * `createNavigator<RouteMap>()` binds a registry to a lightweight RN screen shell: a
 * typed header (title / subtitle / back) above the app's screen content. The registry
 * itself is pure (`./navigation.ts`) — this container only subscribes to it so the
 * back affordance reflects the live stack.
 */
import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { createNavigatorRegistry, type NavigatorRegistry, type NavigatorState, type RouteMap } from './navigation';
import { ScreenHeader } from './components/ScreenHeader';
import { theme } from './theme';

/** Props for the typed screen shell. */
export interface StackScreenProps {
  /** Header title. */
  title: string;
  /** Optional header subtitle. */
  subtitle?: string;
  /** Called when the header back affordance is pressed. */
  onBack?: () => void;
  /** Optional right-side header accessory (actions / badges). */
  accessory?: React.ReactNode;
  /** Screen body. */
  children: React.ReactNode;
}

/** The value returned by {@link createNavigator}. */
export interface Navigator<M extends RouteMap> {
  /** Lightweight RN stack container (header + content). */
  Screen: React.ComponentType<StackScreenProps>;
  /** Typed push: `navigate('Home', { id })`. */
  navigate: NavigatorRegistry<M>['navigate'];
  /** Typed pop. */
  goBack: NavigatorRegistry<M>['goBack'];
}

function useNavigatorState<M extends RouteMap>(registry: NavigatorRegistry<M>): NavigatorState<M> {
  const [state, setState] = useState<NavigatorState<M>>(() => registry.snapshot());
  useEffect(() => registry.subscribe(setState), [registry]);
  return state;
}

/**
 * Bind a typed registry to a screen shell. Call once at module scope in each app,
 * e.g. `const { Screen, navigate, goBack } = createNavigator<AppRoutes>()`.
 */
export function createNavigator<M extends RouteMap>(): Navigator<M> {
  const registry = createNavigatorRegistry<M>();

  function StackScreen(props: StackScreenProps): React.JSX.Element {
    const { title, subtitle, onBack, accessory, children } = props;
    const state = useNavigatorState(registry);
    const canGoBack = onBack !== undefined && state.stack.length > 1;
    return (
      <View style={styles.root}>
        <ScreenHeader
          title={title}
          subtitle={subtitle}
          onBack={canGoBack ? onBack : undefined}
          accessory={accessory}
        />
        <View style={styles.content}>{children}</View>
      </View>
    );
  }

  return {
    Screen: StackScreen,
    navigate: registry.navigate,
    goBack: registry.goBack,
  };
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.colors.background },
  content: { flex: 1 },
});
