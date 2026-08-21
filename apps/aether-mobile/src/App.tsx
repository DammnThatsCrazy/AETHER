/**
 * Aether Mobile root — typed navigator wiring the five M3b feature screens
 * (Today / Copilot / Explore / Alerts / Account).
 *
 * Navigation uses `createNavigator<AppRoutes>()` from `@aether/mobile-ui`: the app
 * holds the active tab, pushes typed routes through the navigator, and renders the
 * matching screen inside the shared `Screen` shell. All screens are read-only
 * (M2 "no offline mutation" invariant); M6 adds governed actions.
 */
import React, { useState } from 'react';
import { SafeAreaView, StyleSheet, View } from 'react-native';

import { theme } from '@aether/mobile-ui';

import { TabBar } from './components/TabBar';
import { navigate } from './navigator';
import type { AppTab } from './routes';
import AccountScreen from './screens/AccountScreen';
import AlertsScreen from './screens/AlertsScreen';
import CopilotScreen from './screens/CopilotScreen';
import ExploreScreen from './screens/ExploreScreen';
import TodayScreen from './screens/TodayScreen';

export default function App(): React.JSX.Element {
  const [tab, setTab] = useState<AppTab>('Today');

  const selectTab = (next: AppTab): void => {
    setTab(next);
    // Keep the typed navigator in sync — root tabs are pushed routes, so deep-link
    // / goBack semantics stay coherent with the registry in `packages/mobile-ui`.
    navigate(next);
  };

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.body}>
        {tab === 'Today' && <TodayScreen />}
        {tab === 'Copilot' && <CopilotScreen />}
        {tab === 'Explore' && <ExploreScreen />}
        {tab === 'Alerts' && <AlertsScreen />}
        {tab === 'Account' && <AccountScreen />}
      </View>
      <TabBar active={tab} onSelect={selectTab} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.colors.background },
  body: { flex: 1 },
});
